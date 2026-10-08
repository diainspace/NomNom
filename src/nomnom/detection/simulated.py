"""Detection adapters yield mounted sources; they never ingest files."""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

@dataclass(frozen=True)
class Card:
    identity: str
    root: Path

class Detector(Protocol):
    def inserted(self) -> Card: ...

class SimulatedDetector:
    def __init__(self, directory: Path, card_id: str):
        self.directory = directory
        self.card_id = card_id

    def inserted(self) -> Card:
        root = self.directory.resolve(strict=True)
        if not root.is_dir() or not self.card_id.strip():
            raise ValueError("A source directory and nonempty stable card ID are required")
        return Card(self.card_id, root)
