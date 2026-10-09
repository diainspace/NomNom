"""Measured progress regressions using only synthetic files."""
import tempfile
import unittest
from pathlib import Path
from threading import Event
from nomnom.config import Config
from nomnom.detection.simulated import SimulatedDetector
from nomnom.engine.configured import run
from nomnom.progress import Progress


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nomnom-progress-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source'
        self.source.mkdir()
        self.dest = self.root / 'dest'
        self.card = SimulatedDetector(self.source, 'synthetic').inserted()
        self.config = Config(mode='preserve', destination=str(self.dest))

    def test_phases_counts_bytes_and_duplicates(self):
        payload = b'synthetic' * 200000
        (self.source / 'one.jpg').write_bytes(payload)
        (self.source / 'two.jpg').write_bytes(b'other')
        (self.source / 'ignore.txt').write_bytes(b'ignore')
        updates = []
        result = run(self.card, self.config, self.root / 'state', progress=updates.append)
        self.assertTrue(result.complete)
        self.assertIsNone(updates[0].files_total)
        phases = [p.phase for p in updates]
        for phase in ('Preparing transfer', 'Scanning source', 'Fingerprinting source', 'Copying', 'Verifying copied file', 'Recording verified transfer', 'Complete'):
            self.assertIn(phase, phases)
        self.assertEqual(updates[-1].files_done, 2)
        self.assertEqual(updates[-1].files_total, 2)
        self.assertEqual(updates[-1].bytes_transferred, len(payload) + 5)
        self.assertEqual(updates[-1].verified, 2)
        self.assertEqual(sorted(p.bytes_transferred for p in updates), [p.bytes_transferred for p in updates])
        repeat = []
        result = run(self.card, self.config, self.root / 'state', progress=repeat.append)
        self.assertEqual(result.duplicates, 2)
        self.assertEqual(repeat[-1].bytes_transferred, 0)
        self.assertEqual(repeat[-1].files_done, 2)

    def test_failure_and_cancellation_are_not_completion(self):
        (self.source / 'one.jpg').write_bytes(b'one')
        (self.source / 'two.jpg').write_bytes(b'two')
        self.dest.mkdir()
        (self.dest / 'one.jpg').write_bytes(b'collision')
        updates = []
        result = run(self.card, self.config, self.root / 'state', progress=updates.append)
        self.assertFalse(result.complete)
        self.assertEqual(updates[-1].phase, 'Finished with failures')
        self.assertEqual(updates[-1].files_done, 2)
        self.assertEqual(updates[-1].failures, 1)
        event = Event()
        cancelled = []
        def callback(update):
            cancelled.append(update)
            if update.files_done == 1:
                event.set()
        result = run(self.card, self.config, self.root / 'state', cancel=event, progress=callback)
        self.assertTrue(result.cancelled)
        self.assertEqual(cancelled[-1].phase, 'Cancelled')
        self.assertEqual(cancelled[-1].files_done, 1)

    def test_unknown_total_does_not_invent_percentage(self):
        text = Progress().text()
        self.assertIn('not known yet', text)
        self.assertNotIn('%', text)
