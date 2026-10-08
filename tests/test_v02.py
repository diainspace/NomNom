import copy
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from nomnom.config import Config, Rule
from nomnom.planning import plan_file, preview, capture_date
from nomnom.detection.simulated import SimulatedDetector
from nomnom.engine.configured import run
from nomnom.engine.ingestion import fingerprint
from nomnom.engine.ledger import Ledger
from nomnom.platforms.macos_detection import MacOSDetector

class ConfiguredTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nomnom-v02-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'card'
        self.source.mkdir()
        self.destination = self.root / 'out'
        self.state = self.root / 'state'
        self.card = SimulatedDetector(self.source, 'card-a').inserted()
        self.config = Config(destination=str(self.destination), date_sources=['mtime'])

    def file(self, name='DCIM/100CANON/IMG_01.JPG', content=b'synthetic'):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        os.utime(path, (1609502400, 1609502400))
        return path

    def ingest(self, resume=None):
        return run(self.card, self.config, self.state, resume)

    def test_organize_date_extension_and_repeat(self):
        source = self.file()
        item = plan_file(self.config, source, self.source)
        self.assertEqual(item.relative, Path('2021/01/01/JPEG/IMG_01.JPG'))
        self.assertEqual(self.ingest().copied, 1)
        self.assertEqual(self.ingest().duplicates, 1)

    def test_extension_date_custom_format(self):
        source = self.file('book.PDF')
        self.config.rules = [Rule('.pdf', 'Documents')]
        self.config.hierarchy = 'extension-date'
        self.config.date_format = '%Y-%m'
        self.assertEqual(plan_file(self.config, source, self.source).relative, Path('Documents/2021-01/book.PDF'))

    def test_rule_precedence_disabled_and_unmatched(self):
        source = self.file('book.pdf')
        self.config.hierarchy = 'extension'
        self.config.rules = [Rule('PDF', 'First', False), Rule('.pdf', 'Second'), Rule('.pdf', 'Third')]
        self.assertEqual(plan_file(self.config, source, self.source).relative, Path('Second/book.pdf'))
        self.config.rules[1].enabled = self.config.rules[2].enabled = False
        self.config.unmatched = 'include'
        self.assertIsNone(plan_file(self.config, source, self.source))
        unknown = self.file('note.xyz')
        self.assertEqual(plan_file(self.config, unknown, self.source).relative, Path('Other/note.xyz'))
        self.config.unmatched = 'error'
        self.assertRaises(ValueError, plan_file, self.config, unknown, self.source)

    def test_preserve_structure_and_identical_names(self):
        self.config.mode = 'preserve'
        first = self.file('a/image.jpg')
        self.file('b/image.jpg')
        result = self.ingest()
        self.assertTrue(result.complete)
        self.assertEqual(result.copied, 2)
        self.assertEqual((self.destination / 'a/image.jpg').read_bytes(), first.read_bytes())
        self.assertEqual(self.ingest().duplicates, 2)

    def test_backup_all_entries_empty_dirs_and_timestamps(self):
        self.config.mode = 'backup'
        source = self.file('nested/no-extension')
        self.file('.hidden', b'hidden')
        self.file('same/data.bin')
        (self.source / 'empty').mkdir()
        result = self.ingest()
        self.assertTrue(result.complete)
        self.assertEqual(result.copied, 3)
        target = Path(result.destination)
        self.assertTrue((target / 'empty').is_dir())
        self.assertEqual(fingerprint(target / 'nested/no-extension'), fingerprint(source))
        self.assertEqual((target / 'nested/no-extension').stat().st_mtime_ns, source.stat().st_mtime_ns)
        with sqlite3.connect(str(self.state / 'ledger.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT status FROM backup_sessions').fetchone()[0], 'complete')

    def test_new_backup_sessions_do_not_mix(self):
        self.config.mode = 'backup'
        self.config.backup_name = 'Vacation'
        self.file()
        first = self.ingest()
        second = self.ingest()
        self.assertNotEqual(first.destination, second.destination)
        self.assertEqual(second.copied, 1)
        self.assertTrue(Path(first.destination).exists())
        self.assertEqual(self.ingest(first.session_id).duplicates, 1)

    def test_resume_rejects_changed_source_or_settings(self):
        self.config.mode = 'backup'
        source = self.file()
        result = self.ingest()
        source.write_bytes(b'changed')
        self.assertRaises(ValueError, self.ingest, result.session_id)
        self.assertEqual(next(Path(result.destination).rglob('*.JPG')).read_bytes(), b'synthetic')

    def test_backup_reports_symlink_and_fifo(self):
        self.config.mode = 'backup'
        source = self.file()
        (self.source / 'link').symlink_to(source)
        os.mkfifo(self.source / 'pipe')
        result = self.ingest()
        self.assertFalse(result.complete)
        self.assertEqual(len(result.failures), 2)
        self.assertIn('symbolic link', result.failures[0][1])
        self.assertIn('special file', result.failures[1][1])
        self.assertEqual(result.copied, 1)
        with sqlite3.connect(str(self.state / 'ledger.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT status FROM backup_sessions').fetchone()[0], 'incomplete')

    def test_collision_preserves_source_and_destination(self):
        self.config.mode = 'preserve'
        source = self.file('same.jpg')
        before = source.read_bytes(), source.stat().st_mtime_ns
        self.destination.mkdir()
        target = self.destination / 'same.jpg'
        target.write_bytes(b'existing')
        result = self.ingest()
        self.assertFalse(result.complete)
        self.assertEqual(target.read_bytes(), b'existing')
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), before)
        with sqlite3.connect(str(self.state / 'ledger.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM occurrences').fetchone()[0], 0)

    def test_preview_and_save_do_not_create_destination(self):
        source = self.file()
        target, date_source = preview(self.config, source, self.source)
        self.assertEqual(date_source, 'mtime')
        settings = self.state / 'settings.json'
        self.config.save(settings)
        restored = Config.load(settings)
        self.assertEqual(restored, self.config)
        self.assertFalse(self.destination.exists())
        self.assertTrue(str(target).startswith(str(self.destination)))

    def test_configuration_validation(self):
        for field, value in [('mode', 'oops'), ('destination', 'relative'), ('date_format', '../%Y'), ('date_format', '%Q'), ('backup_name', '../backup'), ('date_sources', ['exif']), ('version', 99)]:
            config = copy.deepcopy(self.config)
            setattr(config, field, value)
            with self.subTest(field=field, value=value):
                self.assertRaises(ValueError, config.validate)
        self.config.rules = [Rule('.jpg', '../escape')]
        self.assertRaises(ValueError, self.config.validate)
        self.assertRaises(ValueError, Config.from_dict, {'surprise': 1})
        self.assertRaises(ValueError, Config.from_dict, {'rules': [{'extension': '.jpg', 'condition': 'unknown'}]})

    def test_overlap_and_symlinked_target_rejected(self):
        source = self.file('nested/image.jpg')
        self.config.mode = 'preserve'
        self.config.destination = str(self.source / 'out')
        self.assertRaises(ValueError, self.ingest)
        self.assertFalse((self.source / 'out').exists())
        self.config.destination = str(self.destination)
        self.destination.mkdir()
        outside = self.root / 'outside'
        outside.mkdir()
        (self.destination / 'nested').symlink_to(outside)
        self.assertFalse(self.ingest().complete)
        self.assertFalse(list(outside.iterdir()))

    def test_corrupt_transfer_and_changing_source_not_recorded(self):
        self.config.mode = 'preserve'
        source = self.file()
        from nomnom.engine import transfer
        original = transfer.fingerprint
        def changed(path):
            value = original(path)
            if path.name.startswith('.nomnom-'):
                source.write_bytes(b'changing')
            return value
        with patch.object(transfer, 'fingerprint', side_effect=changed):
            self.assertFalse(self.ingest().complete)
        with sqlite3.connect(str(self.state / 'ledger.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM occurrences').fetchone()[0], 0)

    def test_additive_ledger_migration(self):
        self.state.mkdir()
        db = sqlite3.connect(str(self.state / 'ledger.sqlite3'))
        db.executescript('CREATE TABLE contents(digest TEXT PRIMARY KEY, size INTEGER NOT NULL, destination TEXT NOT NULL); CREATE TABLE occurrences(card_id TEXT, source_path TEXT, digest TEXT, size INTEGER, mtime_ns INTEGER, PRIMARY KEY(card_id, source_path, digest));')
        db.execute('INSERT INTO contents VALUES (?, ?, ?)', ('digest', 9, '/old/photo'))
        db.commit()
        db.close()
        ledger = Ledger(self.state)
        self.assertEqual(ledger.copies('digest'), [Path('/old/photo')])
        ledger.close()

    def test_exif_missing_falls_back(self):
        source = self.file()
        moment, kind = capture_date(source, ['exif', 'mtime'])
        self.assertEqual(kind, 'mtime')
        self.assertEqual(moment.year, 2021)

    def test_actual_synthetic_exif_date(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Optional Pillow is not installed')
        source = self.source / 'generated.jpg'
        exif = Image.Exif()
        exif[36867] = '2020:02:03 04:05:06'
        Image.new('RGB', (2, 2), 'blue').save(source, exif=exif)
        moment, kind = capture_date(source, ['exif', 'mtime'])
        self.assertEqual(kind, 'exif')
        self.assertEqual(moment.strftime('%Y-%m-%d'), '2020-02-03')

    def test_backup_partial_failure_resumes(self):
        self.config.mode = 'backup'
        self.file('a.bin')
        self.file('b.bin', b'other')
        from nomnom.engine import configured
        original = configured.verified_transfer
        def fail_one(source, *args):
            if source.name == 'b.bin':
                raise OSError('simulated interruption')
            return original(source, *args)
        with patch.object(configured, 'verified_transfer', side_effect=fail_one):
            first = self.ingest()
        self.assertFalse(first.complete)
        second = self.ingest(first.session_id)
        self.assertTrue(second.complete)
        self.assertEqual((second.copied, second.duplicates), (1, 1))

    def test_backup_detects_new_file_during_transfer(self):
        self.config.mode = 'backup'
        self.file()
        from nomnom.engine import configured
        original = configured.verified_transfer
        def insert_file(*args):
            result = original(*args)
            self.file('appeared.txt')
            return result
        with patch.object(configured, 'verified_transfer', side_effect=insert_file):
            result = self.ingest()
        self.assertFalse(result.complete)
        self.assertIn('inventory changed', result.failures[-1][1])

    def test_organize_dedup_across_cards_records_occurrences(self):
        self.file('a.jpg')
        self.ingest()
        other = self.root / 'other'
        other.mkdir()
        photo = other / 'renamed.jpg'
        photo.write_bytes(b'synthetic')
        os.utime(photo, (1609502400, 1609502400))
        card = SimulatedDetector(other, 'card-b').inserted()
        result = run(card, self.config, self.state)
        self.assertEqual(result.duplicates, 1)
        with sqlite3.connect(str(self.state / 'ledger.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM occurrences').fetchone()[0], 2)

    def test_new_destination_requires_its_own_copy(self):
        self.file()
        self.ingest()
        self.config.destination = str(self.root / 'new-output')
        self.assertEqual(self.ingest().copied, 1)

    def test_malformed_json_and_runtime_settings_location(self):
        settings = self.root / 'bad.json'
        settings.write_text('{')
        self.assertRaises(ValueError, Config.load, settings)
        self.assertRaises(ValueError, self.config.save, Path.cwd() / 'settings.json')

    def test_no_selection_creates_no_destination(self):
        self.file('ignored.xyz')
        result = self.ingest()
        self.assertEqual(result.skipped, 1)
        self.assertFalse(self.destination.exists())

    def test_unreadable_directory_makes_backup_incomplete(self):
        self.config.mode = 'backup'
        self.file()
        from nomnom.engine import configured
        original = configured.os.scandir
        def denied(path):
            if Path(path).name == 'DCIM':
                raise PermissionError('synthetic denied entry')
            return original(path)
        with patch.object(configured.os, 'scandir', side_effect=denied):
            result = self.ingest()
        self.assertFalse(result.complete)
        self.assertIn('denied', result.failures[0][1])

    def test_backup_preview_includes_unique_session_suffix(self):
        source = self.file()
        self.config.mode = 'backup'
        self.config.backup_name = 'Vacation'
        target, unused = preview(self.config, source, self.source)
        self.assertIn('Vacation-<session>', str(target))
        self.assertFalse(self.destination.exists())

    def test_detector_filters_local_diskutil_data(self):
        detector = MacOSDetector()
        listing = {'AllDisksAndPartitions': [{'Partitions': [{'DeviceIdentifier': 'disk4s1'}]}]}
        info = {'MountPoint': str(self.source), 'RemovableMedia': True, 'VolumeUUID': 'card-uuid'}
        with patch.object(detector, '_plist', side_effect=[listing, info]):
            self.assertEqual(detector.mounted_cards()[0].identity, 'card-uuid')
        with patch.object(detector, '_plist', side_effect=[listing, dict(info, RemovableMedia=False)]):
            self.assertEqual(detector.mounted_cards(), [])

if __name__ == '__main__':
    unittest.main()
