"""Optional real AppKit smoke test; opens a window, then exits without ingestion.
Run on macOS: PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/native_smoke.py
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
import rumps
from PyObjCTools import AppHelper
from nomnom.platforms import macos_app

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
        print('Native menu bar, window, mode/rule editing, preview, save/reload passed', flush=True)
    except Exception as error:
        errors.append(error)
        print('Native smoke failure: ' + repr(error), flush=True)
    def finish():
        app.timer.stop()
        if app.settings:
            app.settings.window.orderOut_(None)
        app.executor.shutdown(wait=True)
        AppHelper.stopEventLoop()
    AppHelper.callLater(float(os.environ.get('NOMNOM_SMOKE_HOLD', '2')), finish)

try:
    with patch.object(macos_app, 'state_directory', return_value=state), patch.object(macos_app.MacOSDetector, 'mounted_cards', return_value=[]):
        macos_app.main()
finally:
    runtime.cleanup()
if errors:
    raise errors[0]
