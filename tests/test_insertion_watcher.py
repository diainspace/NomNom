"""Synthetic external-device insertion and preference regressions."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from nomnom.config import Config
from nomnom.detection.simulated import Card
from nomnom.platforms.macos_watcher import InsertionWatcher, launch_if_needed
from tools.install_macos_watcher import agent_spec


class InsertionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nomnom-insert-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = self.root / 'settings.json'
        self.card = Card('synthetic-uuid', self.root / 'synthetic-card')
        self.detector, self.launch = Mock(), Mock()
        self.watcher = InsertionWatcher(self.detector, self.settings, self.launch)

    def test_launch_on_insertion_once_and_after_reinsertion(self):
        for cards in ([], [self.card], [self.card], [], [self.card]):
            self.detector.mounted_cards.return_value = cards
            self.watcher.poll()
        self.assertEqual(self.launch.call_count, 2)
        self.assertFalse(self.card.root.exists())

    def test_disabled_preference_is_persistent_and_reversible(self):
        Config(prompt_on_insert=False).save(self.settings)
        self.detector.mounted_cards.return_value = [self.card]
        self.watcher.poll()
        self.launch.assert_not_called()
        Config(prompt_on_insert=True).save(self.settings)
        self.detector.mounted_cards.return_value = []
        self.watcher.poll()
        self.detector.mounted_cards.return_value = [self.card]
        self.watcher.poll()
        self.launch.assert_called_once()

    def test_old_configuration_defaults_to_prompting(self):
        self.assertTrue(Config.from_dict({'version': 1}).prompt_on_insert)
        self.assertRaises(ValueError, Config.from_dict, {'prompt_on_insert': 'yes'})

    def test_multiple_new_devices_only_launch_once(self):
        self.detector.mounted_cards.return_value = [self.card, Card('other', self.root / 'other')]
        self.watcher.poll()
        self.launch.assert_called_once()

    def test_failed_launch_is_retried(self):
        self.detector.mounted_cards.return_value = [self.card]
        self.launch.side_effect = RuntimeError('synthetic launch failure')
        self.assertRaises(RuntimeError, self.watcher.poll)
        self.launch.side_effect = None
        self.watcher.poll()
        self.assertEqual(self.launch.call_count, 2)

    def test_existing_ui_is_not_reopened_or_duplicated(self):
        with patch('nomnom.platforms.macos_watcher.subprocess.run', return_value=Mock(returncode=0)) as run:
            launch_if_needed(self.root / 'NomNom.app')
            self.assertEqual(run.call_count, 1)
        with patch('nomnom.platforms.macos_watcher.subprocess.run', side_effect=[Mock(returncode=1), Mock(returncode=0)]) as run:
            launch_if_needed(self.root / 'NomNom.app')
            self.assertEqual(run.call_args.args[0][:2], ['/usr/bin/open', '-g'])

    def test_prompt_toggle_does_not_invalidate_backup_resume(self):
        from nomnom.detection.simulated import SimulatedDetector
        from nomnom.engine.configured import run
        source = self.root / 'synthetic-backup-card'
        source.mkdir()
        (source / 'sample.txt').write_bytes(b'synthetic backup bytes')
        card = SimulatedDetector(source, 'synthetic-backup').inserted()
        config = Config(mode='backup', destination=str(self.root / 'destination'))
        result = run(card, config, self.root / 'state')
        config.prompt_on_insert = False
        resumed = run(card, config, self.root / 'state', resume=result.session_id)
        self.assertTrue(resumed.complete)
        self.assertEqual(resumed.duplicates, 1)

    def test_agent_is_user_scoped_and_only_runs_local_watcher(self):
        spec = agent_spec(self.root, '/synthetic/python', self.root / 'state')
        self.assertTrue(spec['RunAtLoad'])
        self.assertTrue(spec['KeepAlive'])
        self.assertEqual(spec['ProgramArguments'][2], 'nomnom.platforms.macos_watcher')
        self.assertNotIn('UserName', spec)
        self.assertNotIn('source', spec)
