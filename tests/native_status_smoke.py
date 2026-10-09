"""Real asynchronous synthetic transfer and native status/menu lifetime regression."""
import os
import tempfile
import time
from pathlib import Path
from threading import Event
from unittest.mock import patch
import AppKit
import rumps
from PyObjCTools import AppHelper
from nomnom.config import Config
from nomnom.detection.simulated import SimulatedDetector
from nomnom.engine import configured
from nomnom.engine.configured import RunResult
from nomnom.platforms import macos_app
from nomnom.reporting import summarize

runtime = tempfile.TemporaryDirectory(prefix='nomnom-native-status-')
root = Path(runtime.name).resolve()
source = root / 'synthetic-card'
source.mkdir()
(source / 'one.jpg').write_bytes(b'A' * (2 * 1024 * 1024))
(source / 'two.jpg').write_bytes(b'B' * (1024 * 1024))
card = SimulatedDetector(source, 'synthetic-status-card').inserted()
scan_gate, copy_gate, copying = Event(), Event(), Event()
errors = []
app = None
real_inventory = configured.inventory
real_run = macos_app.run


def inventory(*args):
    if not scan_gate.wait(10):
        raise RuntimeError('Synthetic scan gate timed out')
    return real_inventory(*args)


def observing_run(*args, **kwargs):
    callback = kwargs['progress']
    def observe(update):
        callback(update)
        if update.bytes_transferred > 0 and not copying.is_set():
            copying.set()
            if not copy_gate.wait(10):
                raise RuntimeError('Synthetic copy gate timed out')
    kwargs['progress'] = observe
    return real_run(*args, **kwargs)


def finish(error=None):
    if error:
        errors.append(error)
        print('Native status failure: ' + repr(error), flush=True)
    scan_gate.set()
    copy_gate.set()
    if app:
        app.timer.stop()
        app.ui_timer.stop()
        app.executor.shutdown(wait=True)
        if app.status:
            app.status.window.orderOut_(None)
    report = os.environ.get('NOMNOM_SMOKE_REPORT')
    if report:
        Path(report).write_text('FAILED: ' + repr(errors) if errors else 'PASSED')
    runtime.cleanup()
    if errors:
        os._exit(1)
    print('Native live progress, persistent status item, close/reopen, completion and partial failure passed', flush=True)
    AppHelper.stopEventLoop()


def check_scan():
    try:
        app.process_events()
        assert app.status.window.isVisible()
        assert str(app.status.phase.stringValue()) == 'Scanning source'
        assert 'not known yet' in str(app.status.details.string())
        app.status.window.performClose_(None)
        assert not app.status.window.isVisible()
        assert app.busy and not app.cancel_event.is_set()
        assert app._nsapp.applicationShouldTerminateAfterLastWindowClosed_(AppKit.NSApp) is False
        app.show_status(None)
        assert app.status.window.isVisible()
        scan_gate.set()
        AppHelper.callLater(0.1, check_copy)
    except Exception as error:
        finish(error)


def check_copy():
    try:
        app.process_events()
        if not copying.is_set():
            assert time.monotonic() < deadline
            AppHelper.callLater(0.1, check_copy)
            return
        details = str(app.status.details.string())
        assert app.busy
        assert app.latest_progress.files_total == 2
        assert app.latest_progress.bytes_transferred > 0
        assert 'Bytes transferred:' in details and ' / 2' in details and '%' not in details
        app.status.window.performClose_(None)
        app.show_status(None)
        assert app.status.window.isVisible() and app.busy
        item = app.menu['Show Transfer Status…']
        assert item.callback is not None
        app.status.window.performClose_(None)
        menu = app._status_item.menu()
        menu.performActionForItemAtIndex_(menu.indexOfItem_(item._menuitem))
        assert app.status.window.isVisible()
        copy_gate.set()
        AppHelper.callLater(0.1, check_complete)
    except Exception as error:
        finish(error)


def check_complete():
    try:
        app.process_events()
        if app.busy:
            assert time.monotonic() < deadline
            AppHelper.callLater(0.1, check_complete)
            return
        assert app.last_summary.title == 'Transfer complete'
        assert 'Copied: 2' in str(app.status.details.string())
        assert app.latest_progress.files_done == 2
        assert app.latest_progress.bytes_transferred == 3 * 1024 * 1024
        assert app._status_item.isVisible() and app._status_item.button().image() is not None
        assert app._status_item.button().title() == 'NomNom'
        app.status.window.performClose_(None)
        app.last_transfer(None)
        assert app.status.window.isVisible()
        # Actual partial failure on a second destination, preserving the conflicting file.
        dest = root / 'partial-output'
        dest.mkdir()
        (dest / 'one.jpg').write_bytes(b'synthetic-collision')
        app.config.destination = str(dest)
        with patch.object(rumps, 'alert', return_value=1):
            app.offer(card, detected=False)
        AppHelper.callLater(0.1, check_failure)
    except Exception as error:
        finish(error)


def check_failure():
    try:
        app.process_events()
        if app.busy:
            assert time.monotonic() < deadline
            AppHelper.callLater(0.1, check_failure)
            return
        assert app.last_summary.title == 'Transfer partially completed'
        assert 'Failed entries/issues: 1' in str(app.status.details.string())
        assert not app.status.cancel.isEnabled()
        app.present_summary(summarize(RunResult(cancelled=True, copied=1, verified=1, not_processed=1, destination=str(root / 'out'))))
        assert str(app.status.phase.stringValue()) == 'Transfer cancelled'
        app.status.window.performClose_(None)
        app.show_status(None)
        assert app.status.window.isVisible()
        finish()
    except Exception as error:
        finish(error)


@rumps.events.before_start
def start():
    global app, deadline
    app = getattr(rumps.App, '*app_instance')
    app.ensure_access()
    app.timer.stop()  # No hardware scans; UI event processing remains live.
    deadline = time.monotonic() + 12
    try:
        assert AppKit.NSApp.activationPolicy() == AppKit.NSApplicationActivationPolicyAccessory
        assert app._status_item.isVisible()
        app.config = Config(mode='preserve', destination=str(root / 'out'))
        with patch.object(rumps, 'alert', return_value=1):
            app.offer(card, detected=False)
        # These assertions happen synchronously before any queued progress is consumed.
        assert app.busy and app.status.window.isVisible()
        assert str(app.status.phase.stringValue()) == 'Preparing transfer'
        assert app.status.cancel.isEnabled()
        AppHelper.callLater(0.15, check_scan)
    except Exception as error:
        finish(error)


with patch.object(macos_app, 'state_directory', return_value=root / 'state'), patch.object(macos_app.MacOSDetector, 'mounted_cards', return_value=[]), patch.object(configured, 'inventory', side_effect=inventory), patch.object(macos_app, 'run', side_effect=observing_run), patch.object(rumps, 'notification'):
    macos_app.main()
