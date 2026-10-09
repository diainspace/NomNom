"""Native menu/confirmation/device-status checks; all disk operations are mocked."""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock
import AppKit
import rumps
from PyObjCTools import AppHelper
from nomnom.platforms import macos_app
from nomnom.platforms.macos_devices import MacOSDeviceAdapter
from nomnom.reporting import Summary
sys.path.insert(0, str(Path(__file__).parent))
from test_devices import FakeDiskutil

runtime = tempfile.TemporaryDirectory(prefix='nomnom-native-devices-')
root = Path(runtime.name)
source = root / 'synthetic-card'
source.mkdir()
fake = FakeDiskutil()
fake.info['disk4s1']['MountPoint'] = str(source)
adapter = MacOSDeviceAdapter(fake)
errors = []


@rumps.events.before_start
def exercise():
    app = getattr(rumps.App, '*app_instance')
    app.timer.stop()
    app.ui_timer.stop()
    app.ensure_access()
    try:
        selected = adapter.devices()[0]
        # Native popup selection has a placeholder; cancel and missing selection
        # never default to the first physical disk.
        class PickerAlert:
            def init(self): return self
            def setMessageText_(self, text): pass
            def setInformativeText_(self, text): pass
            def setAccessoryView_(self, view): self.picker = view
            def addButtonWithTitle_(self, text): pass
            def runModal(self):
                assert self.picker.numberOfItems() == 2
                assert selected.label == str(self.picker.itemTitleAtIndex_(1))
                return AppKit.NSAlertFirstButtonReturn
        picker = PickerAlert()
        with patch.object(AppKit, 'NSAlert', SimpleNamespace(alloc=lambda: picker)):
            assert app.pick_device([selected]) is None
            picker.runModal = lambda: (picker.picker.selectItemAtIndex_(1), AppKit.NSAlertFirstButtonReturn)[1]
            assert app.pick_device([selected]) == selected
            picker.runModal = lambda: AppKit.NSAlertSecondButtonReturn
            assert app.pick_device([selected]) is None
        app.source_root = source
        summary = Summary('Transfer complete', 'Synthetic completed transfer', '')
        with patch.object(rumps, 'notification'):
            app.present_summary(summary)
        assert app.status.eject_button.isEnabled() and app.status.format_button.isEnabled()
        assert app.device_window is None
        # Cancellation through the native completion button makes no disk changes.
        with patch.object(app, 'pick_device', return_value=selected), patch.object(app.executor, 'submit', side_effect=lambda task: task()), patch.object(rumps, 'alert', return_value=0) as confirm:
            app.status.format_button.performClick_(None)
            app.process_events()
            assert confirm.call_count == 1
            assert 'ALL data' in confirm.call_args.args[1] and '/dev/disk4' in confirm.call_args.args[1]
        assert not app.device_busy and not fake.mutations
        # Actual Cocoa menu action dispatches the mocked format and safe eject.
        with patch.object(app, 'pick_device', return_value=selected), patch.object(app.executor, 'submit', side_effect=lambda task: task()), patch.object(rumps, 'alert', return_value=1):
            item = app.menu['Reformat & Eject…']
            menu = app._status_item.menu()
            menu.performActionForItemAtIndex_(menu.indexOfItem_(item._menuitem))
            app.process_events()
        assert fake.mutations == [['eraseDisk', 'FAT32', 'NOMNOM', 'MBRFormat', '/dev/disk4'], ['eject', '/dev/disk4']]
        assert not app.device_busy and app.device_window.window.isVisible()
        assert 'Reformatted & ejected' in str(app.device_window.text.string())
        assert app.device_window.button.title() == 'Dismiss'
        assert app.last_summary is summary and app.source_root is None
        assert not app.status.format_button.isEnabled()
        app.device_window.button.performClick_(None)
        app.show_device_status()
        assert app.device_window.window.isVisible()
        # Neither action can operate during an active transfer.
        app.busy = True
        with patch.object(rumps, 'alert') as alert, patch.object(app.executor, 'submit') as submit:
            app.eject_device()
            submit.assert_not_called()
            assert alert.call_args.args[0] == 'Device is busy'
        app.busy = False
        print('Native device selection, confirmation, menu dispatch, status and ledger-independent actions passed', flush=True)
    except Exception as error:
        errors.append(error)
        print('Native device failure: ' + repr(error), flush=True)
    def finish():
        app.executor.shutdown(wait=True)
        if app.status: app.status.window.orderOut_(None)
        if app.device_window: app.device_window.window.orderOut_(None)
        report = os.environ.get('NOMNOM_SMOKE_REPORT')
        if report: Path(report).write_text('FAILED: ' + repr(errors) if errors else 'PASSED')
        runtime.cleanup()
        if errors: os._exit(1)
        AppHelper.stopEventLoop()
    AppHelper.callLater(float(os.environ.get('NOMNOM_SMOKE_HOLD', '0.2')), finish)


with patch.object(macos_app, 'state_directory', return_value=root / 'state'), patch.object(macos_app.MacOSDetector, 'mounted_cards', return_value=[]), patch.object(macos_app, 'MacOSDeviceAdapter', return_value=adapter):
    macos_app.main()
