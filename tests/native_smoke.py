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
from nomnom.destinations import configure_destination_panel
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
        assert app.title == 'NomNom'
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
            assert 'Verified: 3' in alert.call_args[0][1]
            app.last_transfer(None)
            assert alert.call_count == 2
        with patch.object(rumps, 'notification', side_effect=RuntimeError('synthetic notification unavailable')), patch.object(rumps, 'alert') as alert:
            app.present_summary(summarize(result))
            alert.assert_called_once()
        print('Native menu bar, window, mode/rule editing, preview, save/reload passed', flush=True)
    except Exception as error:
        errors.append(error)
        print('Native smoke failure: ' + repr(error), flush=True)
    def finish():
        app.timer.stop()
        if app.settings:
            app.settings.window.orderOut_(None)
        app.executor.shutdown(wait=True)
        runtime.cleanup()
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
