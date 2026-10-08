import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from .discovery import discover
from .ledger import Ledger
from .organization import FlatOrganizer

BLOCK_SIZE = 1024 * 1024

def signature(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

def fingerprint(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(BLOCK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()

@dataclass
class Result:
    copied: int = 0
    duplicates: int = 0
    failures: list = field(default_factory=list)

def _inside(path, root):
    return path == root or root in path.parents

def ingest(card, destination, state, organizer=None):
    destination, state = Path(destination).resolve(), Path(state).resolve()
    project = Path(__file__).resolve().parents[3]
    if _inside(state, project):
        raise ValueError("Runtime state must be outside the NomNom repository")
    if (_inside(destination, card.root) or _inside(card.root, destination)
            or _inside(state, card.root) or _inside(card.root, state)):
        raise ValueError("Source must not overlap destination or runtime state")
    destination.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(state)
    result = Result()
    organizer = organizer or FlatOrganizer()
    try:
        for source in discover(card.root):
            temporary = None
            try:
                before = source.stat()
                digest = fingerprint(source)
                if signature(source.stat()) != signature(before):
                    raise RuntimeError("Source changed while fingerprinting")
                known = ledger.destination(digest)
                if known and known.is_file() and fingerprint(known) == digest:
                    if signature(source.stat()) != signature(before):
                        raise RuntimeError("Source changed during duplicate verification")
                    ledger.record(card, source, digest, before.st_size, before.st_mtime_ns, known)
                    result.duplicates += 1
                    continue
                relative = Path(organizer.relative_path(source, digest))
                target = (destination / relative).resolve()
                if relative.is_absolute() or not _inside(target, destination) or target == destination:
                    raise ValueError("Organizer path must remain inside destination")
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, name = tempfile.mkstemp(prefix=".nomnom-", dir=str(target.parent))
                temporary = Path(name)
                with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
                    if signature(os.fstat(input_file.fileno())) != signature(before):
                        raise RuntimeError("Source changed before copying")
                    for block in iter(lambda: input_file.read(BLOCK_SIZE), b""):
                        output.write(block)
                    output.flush()
                    os.fsync(output.fileno())
                    if signature(os.fstat(input_file.fileno())) != signature(before):
                        raise RuntimeError("Source changed while copying")
                if temporary.stat().st_size != before.st_size or fingerprint(temporary) != digest:
                    raise RuntimeError("Destination verification failed")
                # Re-read source: metadata alone cannot establish stability.
                if fingerprint(source) != digest or signature(source.stat()) != signature(before):
                    raise RuntimeError("Source changed during transfer")
                try:
                    # Atomic publication without overwriting an existing file.
                    os.link(temporary, target)
                except FileExistsError:
                    if not target.is_file() or fingerprint(target) != digest:
                        raise RuntimeError("Destination collision; existing file preserved")
                if signature(source.stat()) != signature(before):
                    raise RuntimeError("Source changed before recording")
                ledger.record(card, source, digest, before.st_size, before.st_mtime_ns, target)
                result.copied += 1
            except (OSError, RuntimeError, ValueError) as error:
                result.failures.append((str(source), str(error)))
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    finally:
        ledger.close()
    return result
