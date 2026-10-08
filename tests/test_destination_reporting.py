"""Synthetic regressions for picker policy, source-card safety, and outcomes."""
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

from nomnom.config import Config
from nomnom.destinations import configure_destination_panel, picker_start, validate_destination
from nomnom.detection.simulated import SimulatedDetector
from nomnom.engine.configured import run, RunResult
from nomnom.engine import configured, transfer
from nomnom.reporting import summarize, interrupted_summary


class DestinationReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nomnom-ux-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.source = self.root / 'card'
        self.source.mkdir()
        self.out = self.root / 'other-drive'
        self.state = self.root / 'state'
        self.card = SimulatedDetector(self.source, 'synthetic-card').inserted()
        self.config = Config(mode='preserve', destination=str(self.out))

    def photo(self, name, data=b'synthetic'):
        path = self.source / name
        path.write_bytes(data)
        return path

    def test_explicit_start_on_every_invocation_not_panel_history(self):
        self.out.mkdir()
        panel = Mock()
        configure_destination_panel(panel, lambda p: p, str(self.out), [self.source], self.home)
        panel.setDirectoryURL_.assert_called_with(str(self.out))
        # Same shared panel, but now missing destination: history must be replaced.
        configure_destination_panel(panel, lambda p: p, str(self.root / 'missing'), [self.source], self.home)
        panel.setDirectoryURL_.assert_called_with(str(self.home))
        self.assertEqual(panel.setDirectoryURL_.call_count, 2)
        panel.setCanCreateDirectories_.assert_called_with(True)
        panel.setCanChooseDirectories_.assert_called_with(True)
        panel.setCanChooseFiles_.assert_called_with(False)
        panel.setAllowsMultipleSelection_.assert_called_with(False)

    def test_fallback_for_empty_file_invalid_or_source_destination(self):
        file = self.root / 'not-a-directory'
        file.write_text('synthetic')
        for value in ('', 'tests', str(file), str(self.source), str(self.source / 'new'), '\x00'):
            with self.subTest(value=value):
                self.assertEqual(picker_start(value, [self.source], self.home), self.home)
        self.assertFalse((self.source / 'new').exists())

    def test_symlink_into_card_rejected_symlink_to_other_drive_allowed(self):
        alias = self.root / 'card-alias'
        alias.symlink_to(self.source)
        self.assertRaises(ValueError, validate_destination, alias / 'output', [self.source])
        self.assertEqual(picker_start(str(alias), [self.source], self.home), self.home)
        self.out.mkdir()
        external_alias = self.root / 'external-alias'
        external_alias.symlink_to(self.out)
        self.assertEqual(validate_destination(external_alias, [alias]), self.out)
        self.assertEqual(picker_start(str(external_alias), [alias], self.home), self.out)

    def test_entire_source_volume_rejected_other_volume_allowed(self):
        source = Path('/Volumes/SyntheticCard/DCIM')
        for destination in ('/Volumes/SyntheticCard', '/Volumes/SyntheticCard/Backup'):
            self.assertRaises(ValueError, validate_destination, destination, [source])
        self.assertEqual(validate_destination('/Volumes/OtherSyntheticDrive/NomNom', [source]), Path('/Volumes/OtherSyntheticDrive/NomNom'))

    def test_engine_source_rejection_before_state_or_destination_creation(self):
        self.photo('photo.jpg')
        alias = self.root / 'alias'
        alias.symlink_to(self.source)
        self.config.destination = str(alias / 'out')
        self.assertRaises(ValueError, run, self.card, self.config, self.state)
        self.assertFalse(self.state.exists())
        self.assertFalse((self.source / 'out').exists())

    def test_actual_copied_verified_existing_and_skipped_counts(self):
        self.photo('one.jpg')
        self.photo('two.jpg', b'other')
        self.photo('ignore.xyz')
        first = run(self.card, self.config, self.state)
        self.assertEqual((first.copied, first.verified, first.duplicates, first.skipped), (2, 2, 0, 1))
        repeat = run(self.card, self.config, self.state)
        self.assertEqual((repeat.copied, repeat.verified, repeat.duplicates, repeat.skipped), (0, 2, 2, 1))
        summary = summarize(repeat)
        self.assertEqual(summary.title, 'Transfer complete')
        for line in ('Copied: 0', 'Verified: 2', 'Already present: 2', 'Skipped: 1', 'Failed entries/issues: 0', str(self.out)):
            self.assertIn(line, summary.text)

    def test_partial_failure_and_total_failure(self):
        self.photo('one.jpg')
        self.photo('two.jpg', b'new')
        self.out.mkdir()
        (self.out / 'two.jpg').write_bytes(b'collision')
        result = run(self.card, self.config, self.state)
        self.assertEqual((result.copied, result.verified, len(result.failures)), (1, 1, 1))
        self.assertEqual(summarize(result).title, 'Transfer partially completed')
        (self.out / 'one.jpg').write_bytes(b'another collision')
        result = run(self.card, self.config, self.state)
        self.assertEqual(summarize(result).title, 'Transfer failed')
        self.assertEqual(result.verified, 0)

    def test_cancel_before_start_no_runtime_or_destination_created(self):
        self.photo('one.jpg')
        event = Event()
        event.set()
        result = run(self.card, self.config, self.state, cancel=event)
        self.assertTrue(result.cancelled)
        self.assertFalse(result.complete)
        self.assertEqual((result.copied, result.verified, result.not_processed), (0, 0, 1))
        self.assertEqual(summarize(result).title, 'Transfer cancelled')
        self.assertFalse(self.out.exists())
        self.assertFalse(self.state.exists())

    def test_cancel_between_files_retains_verified_copy_backup_incomplete(self):
        self.photo('one.jpg')
        self.photo('two.jpg', b'other')
        self.config.mode = 'backup'
        event = Event()
        original = configured.verified_transfer
        def cancel_after(*args):
            value = original(*args)
            event.set()
            return value
        with patch.object(configured, 'verified_transfer', side_effect=cancel_after):
            result = run(self.card, self.config, self.state, cancel=event)
        self.assertEqual((result.copied, result.verified, result.not_processed), (1, 1, 1))
        self.assertTrue(result.cancelled)
        self.assertFalse(result.complete)
        import sqlite3
        with sqlite3.connect(str(self.state / 'ledger.sqlite3')) as connection:
            self.assertEqual(connection.execute('SELECT status FROM backup_sessions').fetchone()[0], 'incomplete')
        self.assertEqual(summarize(result).title, 'Transfer cancelled')

    def test_publication_race_counts_matching_existing_file_as_present(self):
        source = self.photo('one.jpg')
        real_link = transfer.os.link
        def race(temporary, target):
            target.write_bytes(source.read_bytes())
            return real_link(temporary, target)
        with patch.object(transfer.os, 'link', side_effect=race):
            result = run(self.card, self.config, self.state)
        self.assertEqual((result.copied, result.verified, result.duplicates), (0, 1, 1))

    def test_verified_copy_with_ledger_failure_reports_actual_copy(self):
        self.photo('one.jpg')
        with patch.object(configured.Ledger, 'record_copy', side_effect=OSError('synthetic ledger error')):
            result = run(self.card, self.config, self.state)
        self.assertEqual((result.copied, result.verified, len(result.failures)), (1, 1, 1))
        self.assertFalse(result.complete)

    def test_not_now_and_unexpected_exception_never_report_completion(self):
        result = RunResult(cancelled=True, destination=str(self.out))
        self.assertEqual(summarize(result).title, 'Transfer cancelled')
        summary = interrupted_summary(self.out, 'synthetic failure')
        self.assertIn('unavailable', summary.text)
        self.assertNotIn('Copied: 0', summary.text)
        self.assertIn(str(self.out), summary.text)


if __name__ == '__main__':
    unittest.main()
