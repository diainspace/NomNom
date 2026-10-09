"""Platform-independent, measured transfer progress; no percentage estimates."""
from dataclasses import dataclass
from time import monotonic
from typing import Optional


@dataclass(frozen=True)
class Progress:
    phase: str = 'Preparing transfer'
    files_done: int = 0
    files_total: Optional[int] = None
    bytes_transferred: int = 0
    current_file: str = ''
    verified: int = 0
    failures: int = 0

    def text(self):
        total = str(self.files_total) if self.files_total is not None else 'not known yet'
        return ('Phase: {}\nFiles processed: {} / {}\nVerified: {}\nFailed entries/issues: {}\n'
                'Bytes transferred: {:,}\nCurrent file: {}').format(
                    self.phase, self.files_done, total, self.verified, self.failures,
                    self.bytes_transferred, self.current_file or '—')


class ProgressReporter:
    def __init__(self, callback=None):
        self.callback = callback
        self.phase = 'Preparing transfer'
        self.done = 0
        self.total = None
        self.bytes = 0
        self.current = ''
        self.verified = 0
        self.failures = 0
        self.last_sent = 0.0

    def emit(self, phase=None, current=None, delta=0, force=False):
        changed = phase is not None and phase != self.phase
        if phase is not None:
            self.phase = phase
        if current is not None:
            self.current = str(current)
        self.bytes += delta
        now = monotonic()
        if self.callback and (force or changed or now - self.last_sent >= 0.1):
            self.callback(Progress(self.phase, self.done, self.total, self.bytes,
                                   self.current, self.verified, self.failures))
            self.last_sent = now
