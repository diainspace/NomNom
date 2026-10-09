"""Portable, validated settings. Loading and previewing never create destinations."""
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List


def safe_relative(value, allow_empty=False):
    if not isinstance(value, str) or '\x00' in value or '\\' in value:
        raise ValueError('Folder must be a relative path')
    path = Path(value)
    if (not value and not allow_empty) or path.is_absolute() or '..' in path.parts:
        raise ValueError('Folder must stay beneath the destination')
    return path


@dataclass
class Rule:
    extension: str
    folder: str = ''
    enabled: bool = True
    condition: str = 'extension'

    def validate(self):
        if self.condition != 'extension':
            raise ValueError('Unsupported condition type: ' + self.condition)
        if not isinstance(self.enabled, bool):
            raise ValueError('Rule enabled must be a boolean')
        if not isinstance(self.extension, str):
            raise ValueError('Extension must be text')
        self.extension = self.extension.strip().lower()
        if not self.extension.startswith('.'):
            self.extension = '.' + self.extension
        if len(self.extension) < 2 or any(c in self.extension for c in '/\\\x00 *?'):
            raise ValueError('Enter a file extension such as jpg or cr2')
        safe_relative(self.folder, True)


@dataclass
class Config:
    version: int = 1
    mode: str = 'organize'
    destination: str = ''
    rules: List[Rule] = field(default_factory=lambda: [Rule('.jpg', 'JPEG'), Rule('.jpeg', 'JPEG'), Rule('.cr2', 'RAW')])
    unmatched: str = 'skip'
    unmatched_folder: str = 'Other'
    hierarchy: str = 'date-extension'
    date_format: str = '%Y/%m/%d'
    date_sources: List[str] = field(default_factory=lambda: ['exif', 'mtime'])
    backup_name: str = ''
    prompt_on_insert: bool = True

    def validate(self, require_destination=False):
        if type(self.version) is not int or self.version != 1:
            raise ValueError('Unsupported configuration schema version')
        if not isinstance(self.prompt_on_insert, bool):
            raise ValueError('Insertion prompt preference must be a boolean')
        if self.mode not in ('organize', 'preserve', 'backup'):
            raise ValueError('Choose Organize, Preserve, or Backup')
        if not isinstance(self.destination, str) or '\x00' in self.destination:
            raise ValueError('Invalid destination')
        if self.destination and not Path(self.destination).expanduser().is_absolute():
            raise ValueError('Choose an absolute destination directory')
        if require_destination and not self.destination:
            raise ValueError('Choose a destination first')
        if self.unmatched not in ('skip', 'include', 'error'):
            raise ValueError('Invalid unmatched-file policy')
        if self.hierarchy not in ('date-extension', 'extension-date', 'date', 'extension', 'none'):
            raise ValueError('Invalid folder hierarchy')
        if not isinstance(self.date_sources, list) or not self.date_sources or any(s not in ('exif', 'mtime') for s in self.date_sources) or self.date_sources[-1] != 'mtime':
            raise ValueError('Date sources must end with the mtime fallback')
        if not isinstance(self.date_format, str) or not self.date_format:
            raise ValueError('Date format cannot be empty')
        # Use a portable subset of strftime; reject platform-specific directives.
        index = 0
        while index < len(self.date_format):
            if self.date_format[index] == '%':
                index += 1
                if index >= len(self.date_format) or self.date_format[index] not in 'YymdHMSj%':
                    raise ValueError('Date directives supported: Y y m d H M S j %')
            index += 1
        from datetime import datetime
        safe_relative(datetime(2026, 10, 8).strftime(self.date_format))
        safe_relative(self.unmatched_folder, True)
        safe_relative(self.backup_name, True)
        if self.backup_name and len(Path(self.backup_name).parts) != 1:
            raise ValueError('Backup name must be one folder name')
        if not isinstance(self.rules, list):
            raise ValueError('Rules must be a list')
        for rule in self.rules:
            if not isinstance(rule, Rule):
                raise ValueError('Invalid rule')
            rule.validate()
        return self

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError('Configuration must be an object')
        try:
            values = dict(data)
            if 'rules' in values:
                values['rules'] = [Rule(**r) for r in values['rules']]
            return cls(**values).validate()
        except (TypeError, KeyError) as error:
            raise ValueError('Invalid configuration fields') from error

    @classmethod
    def load(cls, path):
        with Path(path).open() as stream:
            return cls.from_dict(json.load(stream))

    def save(self, path):
        self.validate()
        path = Path(path).expanduser().resolve()
        project = Path(__file__).resolve().parents[2]
        if path == project or project in path.parents:
            raise ValueError('Runtime settings must be outside the repository')
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.settings-', dir=str(path.parent))
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(asdict(self), stream, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)


def state_directory():
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local' / 'state'))) / 'nomnom'
