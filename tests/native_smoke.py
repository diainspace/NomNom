"""Optional real AppKit smoke test; opens a window, then exits without ingestion.
Run on macOS: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/native_smoke.py
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, Mock
from types import SimpleNamespace
import rumps
from PyObjCTools import AppHelper
from nomnom.platforms import macos_app
from nomnom.config import Config
from nomnom.destinations import configure_destination_panel
from nomnom.detection.simulated import SimulatedDetector
from nomnom.engine.configured import RunResult
from nomnom.reporting import summarize
import AppKit
from Foundation import NSURL

runtime = tempfile.TemporaryDirectory(prefix='nomnom-native-smoke-')
state = Path(runtime.name) / 'state'
errors = []

@rumps.events.before_start
def exercise():
    app = getattr(rumps.App, '*app_instance')
    app.timer.stop()
    app.ui_timer.stop()
    app.ensure_access()
    try:
        app.configure(None)
        window = app.settings
        destination = Path(runtime.name) / 'never-created'
        window.destination.setStringValue_(str(destination))
        sample = Path(runtime.name) / 'sample.JPG'
        sample.write_bytes(b'synthetic-native-test')
        window.sample = sample
        window.refreshPreview_(None)
        assert 'sample.JPG' in str(window.preview_label.stringValue())
        window.mode.selectItemAtIndex_(1)
        window.modeChanged_(None)
        assert window.read().mode == 'preserve'
        window.mode.selectItemAtIndex_(2)
        window.modeChanged_(None)
        assert window.read().mode == 'backup'
        window.addRule_(None)
        assert len(window.rules()) == 4
        window.save_(None)
        window.reload_(None)
        assert window.read().mode == 'backup'
        assert len(window.rules()) == 4
        assert not destination.exists()
        assert app._icon_nsimage is not None
        assert AppKit.NSApplication.sharedApplication().applicationIconImage().isValid()
        # Inspect actual native picker configuration without opening or navigating a card.
        chosen = Path(runtime.name) / 'chosen'
        chosen.mkdir()
        panel = AppKit.NSOpenPanel.openPanel()
        configure_destination_panel(panel, NSURL.fileURLWithPath_, str(chosen))
        assert Path(str(panel.directoryURL().path())).resolve() == chosen.resolve()
        assert panel.canCreateDirectories() and not panel.canChooseFiles()
        configure_destination_panel(panel, NSURL.fileURLWithPath_, '', home=Path(runtime.name))
        assert Path(str(panel.directoryURL().path())).resolve() == Path(runtime.name).resolve()
        app.source_root = Path(runtime.name) / 'synthetic-card'
        window.destination.setStringValue_(str(chosen))
        fake_panel = Mock()
        fake_panel.runModal.return_value = AppKit.NSModalResponseCancel
        with patch.object(AppKit, 'NSOpenPanel', SimpleNamespace(openPanel=lambda: fake_panel)):
            assert window.picker(True, destination=True) is None
        assert Path(str(fake_panel.setDirectoryURL_.call_args[0][0].path())).resolve() == chosen.resolve()
        result = RunResult(copied=2, verified=3, duplicates=1, skipped=1, complete=True, destination=str(chosen))
        with patch.object(rumps, 'notification') as notification, patch.object(rumps, 'alert') as alert:
            app.present_summary(summarize(result))
            notification.assert_called_once()
            assert 'Verified: 3' in str(app.status.details.string())
            app.status.window.performClose_(None)
            app.last_transfer(None)
            assert app.status.window.isVisible()
            alert.assert_not_called()
        with patch.object(rumps, 'notification', side_effect=RuntimeError('synthetic notification unavailable')), patch.object(rumps, 'alert') as alert:
            app.present_summary(summarize(result))
            assert app.status.window.isVisible()
            alert.assert_not_called()
        # Selecting a destination without a pending card persists immediately, too.
        new_destination = Path(runtime.name) / 'new-local-destination'
        new_destination.mkdir()
        fake_panel.runModal.return_value = AppKit.NSModalResponseOK
        fake_panel.URL.return_value = NSURL.fileURLWithPath_(str(new_destination))
        app.source_root = None
        with patch.object(AppKit, 'NSOpenPanel', SimpleNamespace(openPanel=lambda: fake_panel)), patch.object(rumps, 'alert') as alert:
            window.chooseDestination_(None)
            alert.assert_not_called()
        assert Path(app.config.destination) == new_destination.resolve()
        assert Config.load(app.settings_path).destination == str(new_destination.resolve())
        # Cancelling selection leaves memory, disk, source and transfer dispatch untouched.
        saved_settings = app.settings_path.read_bytes()
        fake_panel.runModal.return_value = AppKit.NSModalResponseCancel
        with patch.object(AppKit, 'NSOpenPanel', SimpleNamespace(openPanel=lambda: fake_panel)), patch.object(app.executor, 'submit') as submit:
            window.chooseDestination_(None)
            submit.assert_not_called()
        assert app.settings_path.read_bytes() == saved_settings and not app.busy
        assert Path(app.config.destination) == new_destination.resolve()
        # Regression: detection always opens setup before a Start prompt, even with saved settings.
        source = Path(runtime.name) / 'pending-card'
        source.mkdir()
        card = SimulatedDetector(source, 'synthetic-pending').inserted()
        with patch.object(rumps, 'alert', return_value=1) as alert:
            app.offer(card, detected=True)
            assert alert.call_count == 1 and alert.call_args.args[0] == 'NomNom has identified a snack'
        assert app.pending_card == card and not app.busy
        assert 'Save & review' in str(window.save_button.title())
        assert str(source.resolve()) in str(window.source_label.stringValue())
        # Destination is persisted without saving other edits or offering Start.
        fake_panel.runModal.return_value = AppKit.NSModalResponseOK
        fake_panel.URL.return_value = NSURL.fileURLWithPath_(str(chosen))
        window.date_format.setStringValue_('%Y-%m')
        with patch.object(AppKit, 'NSOpenPanel', SimpleNamespace(openPanel=lambda: fake_panel)), patch.object(AppHelper, 'callAfter') as later, patch.object(rumps, 'alert') as alert, patch.object(app.executor, 'submit') as submit:
            window.chooseDestination_(None)
            alert.assert_not_called()
            later.assert_not_called()
            submit.assert_not_called()
        assert app.pending_card == card and not app.busy
        assert Path(app.config.destination) == chosen.resolve()
        assert str(window.date_format.stringValue()) == '%Y-%m'
        assert app.config.date_format != '%Y-%m'
        previous_summary = app.last_summary
        # Only the bottom action saves all settings and cues review. Not now
        # returns to the same editable form, without notifications or a result.
        with patch.object(AppHelper, 'callAfter', side_effect=lambda callback: callback()), patch.object(rumps, 'alert', return_value=0) as alert, patch.object(rumps, 'notification') as notification, patch.object(app.executor, 'submit') as submit:
            window.save_(None)
            assert alert.call_count == 1 and alert.call_args.args[0] == 'Review transfer'
            notification.assert_not_called()
            submit.assert_not_called()
        assert app.config.date_format == '%Y-%m'
        assert app.last_summary is previous_summary
        assert app.pending_card == card and not app.busy and window.window.isVisible()
        assert 'No transfer started' in str(window.preview_label.stringValue())
        assert 'cancel' not in str(app.menu['Ready for a nibble'].title).lower()
        # Manual source selection must not poison the pending card by selecting the destination.
        with patch.object(AppKit, 'NSOpenPanel', SimpleNamespace(openPanel=lambda: fake_panel)), patch.object(rumps, 'alert') as alert:
            app.folder(None)
            assert alert.call_args.args[0] == 'Choose the source, not the destination'
        assert app.pending_card == card and app.source_root == card.root
        # Source and destination dialogs have distinct titles, prompts and starting directories.
        assert fake_panel.setTitle_.call_args.args[0] == 'Choose source folder'
        assert Path(str(fake_panel.setDirectoryURL_.call_args.args[0].path())).resolve() == card.root
        with patch.object(rumps, 'alert', return_value=1) as alert, patch.object(app.executor, 'submit') as submit:
            app.review_pending()
            submit.assert_called_once()
            assert alert.call_args.args[0] == 'Review transfer'
        # Manual ingest reuses the confirmed destination directly, without another picker/setup.
        app.busy = False
        with patch.object(rumps, 'alert', return_value=1) as alert, patch.object(app.executor, 'submit') as submit:
            app.offer(card, detected=False)
            submit.assert_called_once()
            assert alert.call_args.args[0] == 'Review transfer'
            assert 'Destination: ' + str(chosen.resolve()) in alert.call_args.args[1]
        assert app.busy and app.pending_card is None
        app.busy = False
        app.scanning = True  # Prevent this synthetic tick from dispatching diskutil.
        with patch.object(rumps, 'alert', return_value=1):
            app.offer(card, detected=True)
        app.events.put(('cards', []))
        app.tick(None)
        assert app.pending_card is None and app.source_root is None
        # Not now never starts work or creates a cancellation summary.
        previous_summary = app.last_summary
        with patch.object(rumps, 'alert', return_value=0), patch.object(app.executor, 'submit') as submit:
            app.offer(card, detected=True)
            submit.assert_not_called()
        assert app.pending_card is None and app.last_summary is previous_summary
        # Global suppression is persisted and suppresses subsequent insertions.
        with patch.object(rumps, 'alert', return_value=-1), patch.object(app.executor, 'submit') as submit:
            app.offer(card, detected=True)
            submit.assert_not_called()
        assert not app.config.prompt_on_insert
        assert not Config.load(app.settings_path).prompt_on_insert
        with patch.object(rumps, 'alert') as alert:
            app.offer(card, detected=True)
            alert.assert_not_called()
        # Settings can re-enable prompts without starting a transfer.
        window.insertion_prompt.setState_(AppKit.NSControlStateValueOn)
        window.insertionPrompt_(None)
        assert app.config.prompt_on_insert and Config.load(app.settings_path).prompt_on_insert
        print('Native icons, immediate destination persistence, cancellation, startup and automatic/manual transfer regressions passed', flush=True)
    except Exception as error:
        errors.append(error)
        print('Native smoke failure: ' + repr(error), flush=True)
    def finish():
        app.timer.stop()
        app.ui_timer.stop()
        if app.status:
            app.status.window.orderOut_(None)
        if app.settings:
            app.settings.window.orderOut_(None)
        app.executor.shutdown(wait=True)
        runtime.cleanup()
        if os.environ.get('NOMNOM_SMOKE_REPORT'):
            Path(os.environ['NOMNOM_SMOKE_REPORT']).write_text('FAILED: ' + repr(errors) if errors else 'PASSED')
        if errors:
            os._exit(1)
        AppHelper.stopEventLoop()
    AppHelper.callLater(float(os.environ.get('NOMNOM_SMOKE_HOLD', '2')), finish)

try:
    with patch.object(macos_app, 'state_directory', return_value=state), patch.object(macos_app.MacOSDetector, 'mounted_cards', return_value=[]):
        macos_app.main()
finally:
    runtime.cleanup()
if errors:
    raise errors[0]
