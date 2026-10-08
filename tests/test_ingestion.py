import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from nomnom.detection.simulated import SimulatedDetector
from nomnom.engine import ingestion
from nomnom.engine.ingestion import ingest, fingerprint

class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nomnom-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "card"
        self.source.mkdir()
        self.photo = self.source / "IMG_001.JPG"
        self.photo.write_bytes(b"synthetic camera content")
        self.destination = self.root / "photos"
        self.state = self.root / "state"
        self.card = SimulatedDetector(self.source, "card-a").inserted()

    def run_ingest(self, card=None, organizer=None):
        return ingest(card or self.card, self.destination, self.state, organizer)

    def counts(self):
        with sqlite3.connect(str(self.state / "ledger.sqlite3")) as db:
            return tuple(db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                         for table in ("contents", "occurrences"))

    def test_copy_verify_repeat_and_source_preservation(self):
        before = self.photo.stat()
        self.assertEqual(self.run_ingest().copied, 1)
        target = next(self.destination.glob("*.jpg"))
        self.assertEqual(fingerprint(target), fingerprint(self.photo))
        self.assertEqual(self.run_ingest().duplicates, 1)
        self.assertEqual(self.counts(), (1, 1))
        self.assertEqual(ingestion.signature(self.photo.stat()), ingestion.signature(before))

    def test_identical_content_on_second_card(self):
        self.run_ingest()
        other = self.root / "other-card"
        other.mkdir()
        (other / "renamed.JPG").write_bytes(self.photo.read_bytes())
        card = SimulatedDetector(other, "card-b").inserted()
        self.assertEqual(self.run_ingest(card).duplicates, 1)
        self.assertEqual(self.counts(), (1, 2))
        self.assertEqual(len(list(self.destination.glob("*.jpg"))), 1)

    def test_same_name_different_content(self):
        self.run_ingest()
        self.photo.write_bytes(b"different content")
        self.assertEqual(self.run_ingest().copied, 1)
        self.assertEqual(self.counts(), (2, 2))

    def test_changing_source_not_recorded(self):
        original = ingestion.fingerprint
        def changing(path):
            digest = original(path)
            if path.name.startswith(".nomnom-"):
                self.photo.write_bytes(b"source changed during transfer")
            return digest
        with patch.object(ingestion, "fingerprint", side_effect=changing):
            result = self.run_ingest()
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(self.counts(), (0, 0))
        self.assertFalse(list(self.destination.iterdir()))

    def test_bad_copy_not_recorded(self):
        original = ingestion.fingerprint
        with patch.object(ingestion, "fingerprint", side_effect=lambda p: "bad" if p.name.startswith(".nomnom-") else original(p)):
            self.assertEqual(len(self.run_ingest().failures), 1)
        self.assertEqual(self.counts(), (0, 0))

    def test_missing_destination_recopied(self):
        self.run_ingest()
        next(self.destination.glob("*.jpg")).unlink()
        self.assertEqual(self.run_ingest().copied, 1)

    def test_corrupt_existing_destination_preserved(self):
        self.run_ingest()
        target = next(self.destination.glob("*.jpg"))
        target.write_bytes(b"corrupt")
        self.assertEqual(len(self.run_ingest().failures), 1)
        self.assertEqual(target.read_bytes(), b"corrupt")

    def test_custom_organizer_and_collision(self):
        class Custom:
            def relative_path(self, source, digest):
                return Path("album") / source.name
        self.assertEqual(self.run_ingest(organizer=Custom()).copied, 1)
        self.photo.write_bytes(b"new photograph")
        self.assertEqual(len(self.run_ingest(organizer=Custom()).failures), 1)
        self.assertEqual((self.destination / "album" / self.photo.name).read_bytes(), b"synthetic camera content")

    def test_organizer_escape_rejected(self):
        class Escape:
            def relative_path(self, source, digest):
                return Path("../escaped.jpg")
        self.assertEqual(len(self.run_ingest(organizer=Escape()).failures), 1)
        self.assertFalse((self.root / "escaped.jpg").exists())

    def test_source_overlap_rejected(self):
        with self.assertRaises(ValueError):
            ingest(self.card, self.source / "output", self.state)

    def test_state_in_repository_rejected(self):
        with self.assertRaises(ValueError):
            ingest(self.card, self.destination, Path.cwd() / "runtime")

    def test_discovery_ignores_nonphotos_and_symlinks(self):
        (self.source / "notes.txt").write_text("ignore")
        (self.source / "linked.jpg").symlink_to(self.photo)
        self.assertEqual(self.run_ingest().copied, 1)

    def test_recovery_after_publication_before_record(self):
        with patch.object(ingestion.Ledger, "record", side_effect=RuntimeError("interrupted")):
            self.assertEqual(len(self.run_ingest().failures), 1)
        self.assertEqual(self.counts(), (0, 0))
        self.assertEqual(self.run_ingest().copied, 1)
        self.assertEqual(self.counts(), (1, 1))

if __name__ == "__main__":
    unittest.main()
