from pathlib import Path
from typing import Protocol

class Organizer(Protocol):
    def relative_path(self, source: Path, digest: str) -> Path: ...

class FlatOrganizer:
    """Content-addressed names avoid camera filename collisions."""
    def relative_path(self, source: Path, digest: str) -> Path:
        return Path(digest + source.suffix.lower())
