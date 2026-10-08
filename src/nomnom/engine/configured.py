"""Configurable local ingestion; v0.1 entry point remains unchanged."""
import json
import os
import sqlite3
import stat
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from ..planning import plan_file
from ..destinations import validate_destination
from .ingestion import fingerprint, signature, _inside
from .ledger import Ledger
from .transfer import stable, verified_transfer


@dataclass
class RunResult:
    copied: int = 0
    duplicates: int = 0
    skipped: int = 0
    failures: list = field(default_factory=list)
    session_id: str = ''
    destination: str = ''
    complete: bool = False
    verified: int = 0
    cancelled: bool = False
    not_processed: int = 0


def inventory(root):
    """Account for all entries without following symlinks, including empty dirs."""
    files, directories, failures = [], [], []
    def walk(directory):
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
            for entry in entries:
                path = Path(entry.path)
                try:
                    mode = entry.stat(follow_symlinks=False).st_mode
                    if stat.S_ISLNK(mode):
                        failures.append((str(path), 'Unsupported symbolic link'))
                    elif stat.S_ISDIR(mode):
                        directories.append(path)
                        walk(path)
                    elif stat.S_ISREG(mode):
                        files.append(path)
                    else:
                        failures.append((str(path), 'Unsupported special file'))
                except OSError as error:
                    failures.append((str(path), str(error)))
        except OSError as error:
            failures.append((str(directory), str(error)))
    walk(root)
    return files, directories, failures


def checked_target(root, relative):
    from ..config import safe_relative
    safe_relative(relative.as_posix())
    candidate = root / relative
    # Refuse symlinked destination components, including a symlinked file.
    for component in [candidate] + list(candidate.parents):
        if component.is_symlink():
            raise ValueError('Symlinked destination paths are unsupported')
        if component == root:
            break
    resolved = candidate.resolve()
    if not _inside(resolved, root) or resolved == root:
        raise ValueError('Destination path escapes root')
    return resolved


def manifest(root, files, directories, failures):
    output = {'directories': sorted(p.relative_to(root).as_posix() for p in directories),
              'files': {}, 'unsupported': sorted(failures)}
    for source in files:
        before = source.stat()
        digest = fingerprint(source)
        stable(source, before)
        output['files'][source.relative_to(root).as_posix()] = [digest, before.st_size, before.st_mtime_ns]
    return json.dumps(output, sort_keys=True)


def run(card, config, state, resume=None, cancel=None):
    config.validate(True)
    root = card.root.resolve(strict=True)
    if root != card.root or not root.is_dir():
        raise ValueError('Card root must be a resolved directory')
    destination = validate_destination(config.destination, [root])
    state = Path(state).expanduser().resolve()
    project = Path(__file__).resolve().parents[3]
    if _inside(state, project):
        raise ValueError('Runtime state must be outside the repository')
    if any(_inside(a, b) or _inside(b, a) for a, b in [(root, destination), (root, state), (destination, state)]):
        raise ValueError('Source, destination, and runtime state must not overlap')
    if resume and config.mode != 'backup':
        raise ValueError('Resume is only supported for Backup')
    files, directories, failures = inventory(root)
    result = RunResult(destination=str(destination), failures=failures)
    # Build plans before creating any destination folders.
    planned = []
    for source in files:
        try:
            item = plan_file(config, source, root)
            if item:
                planned.append(item)
            else:
                result.skipped += 1
        except (ValueError, OSError) as error:
            result.failures.append((str(source), str(error)))
    if cancel is not None and cancel.is_set():
        result.cancelled = True
        result.not_processed = len(planned)
        return result
    ledger = Ledger(state)
    try:
        original_manifest = None
        if config.mode == 'backup':
            original_manifest = manifest(root, files, directories, failures)
            settings = json.dumps(asdict(config), sort_keys=True)
            if resume:
                row = ledger.connection.execute('SELECT card_id, root, destination, config, manifest FROM backup_sessions WHERE id=?', (resume,)).fetchone()
                if not row or (row[0], row[1], row[3], row[4]) != (card.identity, str(root), settings, original_manifest):
                    raise ValueError('Backup resume requires the same card, settings, and unchanged source inventory')
                destination = Path(row[2])
                if destination.parent != Path(config.destination).expanduser().resolve() or destination.is_symlink():
                    raise ValueError('Invalid backup session destination')
                result.session_id = resume
            else:
                result.session_id = uuid.uuid4().hex
                name = config.backup_name or ('Backup-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
                destination /= name + '-' + result.session_id
                destination.mkdir(parents=True, exist_ok=False)
                with ledger.connection:
                    ledger.connection.execute('INSERT INTO backup_sessions VALUES (?, ?, ?, ?, ?, ?, ?)', (result.session_id, card.identity, str(root), str(destination), settings, original_manifest, 'incomplete'))
            result.destination = str(destination)
            for directory in directories:
                try:
                    checked_target(destination, directory.relative_to(root)).mkdir(parents=True, exist_ok=True)
                except (ValueError, OSError) as error:
                    result.failures.append((str(directory), str(error)))
        for index, item in enumerate(planned):
            if cancel is not None and cancel.is_set():
                result.cancelled = True
                result.not_processed = len(planned) - index
                break
            source = item.source
            try:
                before = source.stat()
                digest = fingerprint(source)
                stable(source, before)
                target = checked_target(destination, item.relative)
                if config.mode == 'organize':
                    # Deduplicate within the selected route, never another destination root.
                    known = next((p for p in ledger.copies(digest) if p.parent == target.parent and p.is_file() and not p.is_symlink() and fingerprint(p) == digest), None)
                    if known is not None:
                        stable(source, before, digest)
                        result.verified += 1
                        result.duplicates += 1
                        ledger.record_copy(card, source, digest, before.st_size, before.st_mtime_ns, known)
                        continue
                copied = verified_transfer(source, target, before, digest, config.mode == 'backup')
                stable(source, before)
                result.verified += 1
                if copied:
                    result.copied += 1
                else:
                    result.duplicates += 1
                ledger.record_copy(card, source, digest, before.st_size, before.st_mtime_ns, target)
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
                result.failures.append((str(source), str(error)))
        if config.mode == 'backup':
            # Re-scan catches entries inserted/removed during the backup, too.
            final_files, final_dirs, final_failures = inventory(root)
            try:
                if manifest(root, final_files, final_dirs, final_failures) != original_manifest:
                    result.failures.append((str(root), 'Source inventory changed during backup'))
            except (OSError, RuntimeError) as error:
                result.failures.append((str(root), str(error)))
            # Set directory timestamps last so populating children cannot change them.
            for directory in reversed(directories):
                try:
                    info = directory.stat()
                    os.utime(checked_target(destination, directory.relative_to(root)), ns=(info.st_atime_ns, info.st_mtime_ns))
                except (OSError, ValueError) as error:
                    result.failures.append((str(directory), 'Could not preserve directory timestamps: ' + str(error)))
            with ledger.connection:
                ledger.connection.execute('UPDATE backup_sessions SET status=? WHERE id=?', ('complete' if not result.failures and not result.cancelled else 'incomplete', result.session_id))
        result.complete = not result.failures and not result.cancelled
        return result
    finally:
        ledger.close()
