"""Pure selection and destination planning shared by CLI and macOS UI."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from .config import safe_relative


def capture_date(source, sources):
    for kind in sources:
        if kind == 'exif':
            try:
                from PIL import Image
                with Image.open(source) as image:
                    exif = image.getexif()
                    # DateTimeOriginal is normally in the EXIF sub-IFD.
                    tags = exif.get_ifd(34665) if hasattr(exif, 'get_ifd') else exif
                    value = tags.get(36867) or exif.get(36867)
                    if value:
                        return datetime.strptime(str(value), '%Y:%m:%d %H:%M:%S'), 'exif'
            except (ImportError, OSError, ValueError, TypeError, KeyError, AttributeError):
                pass
        if kind == 'mtime':
            return datetime.fromtimestamp(source.stat().st_mtime), 'mtime'
    raise ValueError('No usable date source')


@dataclass(frozen=True)
class PlannedFile:
    source: Path
    relative: Path
    date_source: str = ''


def plan_file(config, source, root):
    config.validate(True)
    source, root = Path(source), Path(root)
    relative = source.relative_to(root)
    safe_relative(relative.as_posix())
    if config.mode == 'backup':
        return PlannedFile(source, relative)
    rule = next((r for r in config.rules if r.enabled and r.extension == source.suffix.lower()), None)
    if rule is None:
        # An explicitly disabled extension stays excluded, even with include-unmatched.
        if any(r.extension == source.suffix.lower() for r in config.rules):
            return None
        if config.unmatched == 'skip':
            return None
        if config.unmatched == 'error':
            raise ValueError('No matching rule for ' + source.name)
    if config.mode == 'preserve':
        return PlannedFile(source, relative)
    folder = Path(rule.folder if rule else config.unmatched_folder)
    date, kind = ('', '')
    if config.hierarchy in ('date-extension', 'extension-date', 'date'):
        moment, kind = capture_date(source, config.date_sources)
        date = moment.strftime(config.date_format)
        safe_relative(date)
    components = {'date-extension': [Path(date), folder], 'extension-date': [folder, Path(date)],
                  'date': [Path(date)], 'extension': [folder], 'none': []}[config.hierarchy]
    output = Path(*components) / source.name
    safe_relative(output.as_posix())
    return PlannedFile(source, output, kind)


def preview(config, source, root, backup_folder=None):
    planned = plan_file(config, Path(source), Path(root))
    if planned is None:
        return None, 'excluded'
    target = Path(config.destination).expanduser()
    if config.mode == 'backup':
        target /= backup_folder or ((config.backup_name + '-<session>') if config.backup_name else 'Backup-<timestamp>-<session>')
    return target / planned.relative, planned.date_source
