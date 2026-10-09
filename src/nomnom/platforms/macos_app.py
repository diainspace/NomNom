"""Native macOS configuration UI. Optional Cocoa imports stay in this module."""
import copy
import queue
import sys
from time import monotonic
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import Config, Rule, state_directory
from ..planning import preview
from ..progress import Progress
from ..settings import select_destination
from ..destinations import configure_destination_panel, configure_source_panel, validate_destination
from ..reporting import summarize, interrupted_summary
from ..detection.simulated import SimulatedDetector
from ..engine.configured import run
from .macos_detection import MacOSDetector


def main():
    if sys.platform != 'darwin':
        raise SystemExit('The Menu Bar Muncher requires macOS. The CLI works independently.')
    try:
        import rumps
        import objc
        import AppKit as A
        from Foundation import NSObject, NSURL
        from PyObjCTools import AppHelper
    except ImportError as error:
        raise SystemExit('Install the macOS extras: python -m pip install -e ".[macos,exif]"') from error

    class SettingsWindow(NSObject):
        def windowShouldClose_(self, sender):
            sender.orderOut_(None)
            return False

        def initWithApp_(self, app):
            self = objc.super(SettingsWindow, self).init()
            if self is None:
                return None
            self.app = app
            self.sample = None
            self.fields = []
            self.controls = []
            self.window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                A.NSMakeRect(0, 0, 680, 640), A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable,
                A.NSBackingStoreBuffered, False)
            self.window.setTitle_('NomNom® — Choose the menu')
            self.window.setReleasedWhenClosed_(False)
            self.window.setDelegate_(self)
            self.window.center()
            self.view = self.window.contentView()
            self.label('You decide what it eats and where it puts it.', 20, 602, 640)
            self.label('Mode', 20, 562, 100)
            self.mode = self.popup(['Organize', 'Preserve', 'Backup'], 120, 557, 220)
            self.mode.setTarget_(self)
            self.mode.setAction_('modeChanged:')
            self.source_label = self.label('No source selected', 355, 562, 305)
            self.label('Destination', 20, 522, 100)
            self.destination = self.text('', 120, 517, 440)
            self.button('Choose…', 570, 517, 90, 'chooseDestination:')
            self.label('Folders', 20, 482, 100)
            self.hierarchy = self.popup(['Date / Type', 'Type / Date', 'Date only', 'Type only', 'No automatic folders'], 120, 477, 220)
            self.label('Date folders', 355, 482, 100)
            self.date_formats = {'Year / Month / Day': '%Y/%m/%d', 'Year-Month-Day': '%Y-%m-%d', 'Year / Month': '%Y/%m', 'Year': '%Y'}
            self.date_format = A.NSComboBox.alloc().initWithFrame_(A.NSMakeRect(465, 477, 195, 26))
            self.date_format.addItemsWithObjectValues_(list(self.date_formats))
            self.date_format.setEditable_(True)
            self.view.addSubview_(self.date_format)
            self.label('Date from', 20, 442, 100)
            self.date_source = self.popup(['Capture date, then modified date', 'Modified date'], 120, 437, 310)
            self.label('Other files', 20, 402, 100)
            self.unmatched = self.popup(['Skip', 'Include in Other', 'Report as error'], 120, 397, 220)
            self.label('Backup name', 355, 402, 100)
            self.backup = self.text('', 465, 397, 195)
            self.backup.setPlaceholderString_('Automatic timestamp')
            self.label('File types — top rows have priority', 20, 362, 640)
            scroll = A.NSScrollView.alloc().initWithFrame_(A.NSMakeRect(20, 155, 640, 200))
            scroll.setHasVerticalScroller_(True)
            self.rule_view = A.NSView.alloc().initWithFrame_(A.NSMakeRect(0, 0, 620, 200))
            scroll.setDocumentView_(self.rule_view)
            self.view.addSubview_(scroll)
            self.button('+ File type', 20, 120, 110, 'addRule:')
            self.button('Canon Rebel preset', 140, 120, 180, 'preset:')
            self.button('Sample file…', 330, 120, 130, 'chooseSample:')
            self.insertion_prompt = self.button('Offer snacks when external devices are connected', 20, 87, 640, 'insertionPrompt:')
            self.insertion_prompt.setButtonType_(A.NSButtonTypeSwitch)
            self.preview_label = self.label('Pick a sample file to preview its destination.', 20, 48, 640, 35)
            self.button('Reload', 20, 20, 100, 'reload:')
            self.button('Preview', 130, 20, 100, 'refreshPreview:')
            self.save_button = self.button('Save menu', 465, 20, 195, 'save:')
            self.populate(app.config)
            self.modeChanged_(None)
            return self

        @objc.python_method
        def label(self, title, x, y, width, height=22):
            label = A.NSTextField.alloc().initWithFrame_(A.NSMakeRect(x, y, width, height))
            label.setStringValue_(title)
            label.setEditable_(False)
            label.setBezeled_(False)
            label.setDrawsBackground_(False)
            self.view.addSubview_(label)
            return label

        @objc.python_method
        def text(self, value, x, y, width, parent=None):
            control = A.NSTextField.alloc().initWithFrame_(A.NSMakeRect(x, y, width, 26))
            control.setStringValue_(value)
            (parent or self.view).addSubview_(control)
            return control

        @objc.python_method
        def popup(self, values, x, y, width):
            control = A.NSPopUpButton.alloc().initWithFrame_pullsDown_(A.NSMakeRect(x, y, width, 28), False)
            control.addItemsWithTitles_(values)
            self.view.addSubview_(control)
            return control

        @objc.python_method
        def button(self, title, x, y, width, action, parent=None, tag=0):
            button = A.NSButton.alloc().initWithFrame_(A.NSMakeRect(x, y, width, 28))
            button.setTitle_(title)
            button.setBezelStyle_(A.NSBezelStyleRounded)
            button.setTarget_(self)
            button.setAction_(action)
            button.setTag_(tag)
            (parent or self.view).addSubview_(button)
            return button

        @objc.python_method
        def draw_rules(self, rules):
            for child in list(self.rule_view.subviews()):
                child.removeFromSuperview()
            self.fields = []
            height = max(200, len(rules) * 36 + 12)
            self.rule_view.setFrameSize_(A.NSMakeSize(620, height))
            for index, rule in enumerate(rules):
                y = height - 38 - index * 36
                enabled = self.button('Eat', 0, y, 60, 'refreshPreview:', self.rule_view)
                enabled.setButtonType_(A.NSButtonTypeSwitch)
                enabled.setState_(int(rule.enabled))
                extension = self.text(rule.extension, 65, y, 95, self.rule_view)
                folder = self.text(rule.folder, 170, y, 255, self.rule_view)
                folder.setPlaceholderString_('Destination subfolder (Organize only)')
                self.button('↑', 430, y, 45, 'moveUp:', self.rule_view, index)
                self.button('↓', 478, y, 45, 'moveDown:', self.rule_view, index)
                self.button('Remove', 525, y, 85, 'removeRule:', self.rule_view, index)
                self.fields.append((enabled, extension, folder))

        @objc.python_method
        def rules(self):
            return [Rule(str(ext.stringValue()), str(folder.stringValue()), bool(enabled.state())) for enabled, ext, folder in self.fields]

        @objc.python_method
        def populate(self, config):
            self.mode.selectItemAtIndex_(['organize', 'preserve', 'backup'].index(config.mode))
            self.destination.setStringValue_(config.destination)
            self.hierarchy.selectItemAtIndex_(['date-extension', 'extension-date', 'date', 'extension', 'none'].index(config.hierarchy))
            self.date_format.setStringValue_(next((label for label, value in self.date_formats.items() if value == config.date_format), config.date_format))
            self.date_source.selectItemAtIndex_(0 if 'exif' in config.date_sources else 1)
            self.unmatched.selectItemAtIndex_(['skip', 'include', 'error'].index(config.unmatched))
            self.backup.setStringValue_(config.backup_name)
            self.insertion_prompt.setState_(A.NSControlStateValueOn if config.prompt_on_insert else A.NSControlStateValueOff)
            self.draw_rules(config.rules)
            self.unmatched_folder = config.unmatched_folder

        @objc.python_method
        def read(self):
            return Config(prompt_on_insert=self.insertion_prompt.state() == A.NSControlStateValueOn, mode=['organize', 'preserve', 'backup'][self.mode.indexOfSelectedItem()],
                          destination=str(self.destination.stringValue()), rules=self.rules(),
                          hierarchy=['date-extension', 'extension-date', 'date', 'extension', 'none'][self.hierarchy.indexOfSelectedItem()],
                          date_format=self.date_formats.get(str(self.date_format.stringValue()), str(self.date_format.stringValue())),
                          date_sources=['exif', 'mtime'] if self.date_source.indexOfSelectedItem() == 0 else ['mtime'],
                          unmatched=['skip', 'include', 'error'][self.unmatched.indexOfSelectedItem()],
                          unmatched_folder=self.unmatched_folder,
                          backup_name=str(self.backup.stringValue())).validate(True)

        @objc.python_method
        def picker(self, directories, destination=False, source=False):
            panel = A.NSOpenPanel.openPanel()
            panel.setCanChooseDirectories_(directories)
            panel.setCanChooseFiles_(not directories)
            panel.setAllowsMultipleSelection_(False)
            if destination:
                configure_destination_panel(panel, NSURL.fileURLWithPath_,
                                            str(self.destination.stringValue()), self.app.sources())
                panel.setTitle_('Choose destination folder')
                panel.setMessage_('Choose where NomNom will put the imported files.')
                panel.setPrompt_('Use destination')
            elif source:
                configure_source_panel(panel, NSURL.fileURLWithPath_, self.app.source_root)
            if panel.runModal() == A.NSModalResponseOK:
                return Path(str(panel.URL().path()))
            return None

        def insertionPrompt_(self, sender):
            try:
                updated = copy.deepcopy(self.app.config)
                updated.prompt_on_insert = self.insertion_prompt.state() == A.NSControlStateValueOn
                updated.save(self.app.settings_path)
                self.app.config = updated
            except (ValueError, OSError) as error:
                self.insertion_prompt.setState_(A.NSControlStateValueOn if self.app.config.prompt_on_insert else A.NSControlStateValueOff)
                rumps.alert('Could not save insertion preference', str(error))

        def modeChanged_(self, sender):
            mode = self.mode.indexOfSelectedItem()
            self.hierarchy.setEnabled_(mode == 0)
            self.date_format.setEnabled_(mode == 0)
            self.date_source.setEnabled_(mode == 0)
            self.unmatched.setEnabled_(mode != 2)
            self.backup.setEnabled_(mode == 2)
            self.preview_label.setStringValue_([
                'Organize: route selected files into type and date folders.',
                'Preserve: select file types and keep their original paths.',
                'Backup: all files and folders; file-type rules are ignored.'
            ][mode])

        def chooseDestination_(self, sender):
            selected = self.picker(True, destination=True)
            if selected:
                try:
                    # Persist destination independently of any unrelated unsaved rule edits.
                    self.app.config = select_destination(self.app.config, selected,
                                                         self.app.settings_path, self.app.sources())
                    self.destination.setStringValue_(self.app.config.destination)
                    self.refreshPreview_(sender)
                    self.preview_label.setStringValue_('Destination saved. Review the remaining settings, then choose Save & review transfer.' if self.app.pending_card else 'Destination saved. Choose a source or insert a card to import.')
                except (ValueError, OSError, RuntimeError) as error:
                    rumps.alert('Destination unavailable', str(error))

        def chooseSample_(self, sender):
            self.sample = self.picker(False)
            if self.sample:
                self.refreshPreview_(sender)

        def refreshPreview_(self, sender):
            try:
                config = self.read()
                if self.sample:
                    # For a mounted volume, preserve the path relative to that volume.
                    root = self.sample.parent
                    if len(self.sample.parts) > 3 and self.sample.parts[1] == 'Volumes':
                        root = Path(*self.sample.parts[:3])
                    path, source = preview(config, self.sample, root)
                    self.preview_label.setStringValue_(str(path) + (' (date: ' + source + ')' if source else '') if path else 'This file is off the menu.')
                else:
                    self.preview_label.setStringValue_('Pick a sample file. Preserve and Backup retain paths beneath the card root.')
            except (ValueError, OSError) as error:
                self.preview_label.setStringValue_(str(error))

        def addRule_(self, sender):
            self.draw_rules(self.rules() + [Rule('.txt', 'Documents')])

        def removeRule_(self, sender):
            rules = self.rules()
            del rules[sender.tag()]
            self.draw_rules(rules)

        def moveUp_(self, sender):
            rules, index = self.rules(), sender.tag()
            if index > 0:
                rules[index - 1], rules[index] = rules[index], rules[index - 1]
                self.draw_rules(rules)

        def moveDown_(self, sender):
            rules, index = self.rules(), sender.tag()
            if index < len(rules) - 1:
                rules[index + 1], rules[index] = rules[index], rules[index + 1]
                self.draw_rules(rules)

        def preset_(self, sender):
            self.draw_rules(Config().rules)

        def save_(self, sender):
            try:
                config = self.read()
                validate_destination(config.destination, self.app.sources())
                config.save(self.app.settings_path)
                self.app.config = config
                self.app.load_error = None
                self.preview_label.setStringValue_('Settings saved. Ready to review the pending card.' if self.app.pending_card else 'Menu saved. NomNom is ready for the next card.')
                if self.app.pending_card:
                    AppHelper.callAfter(self.app.review_pending)
            except (ValueError, OSError, RuntimeError) as error:
                rumps.alert('Could not save menu', str(error))

        def reload_(self, sender):
            try:
                self.app.config = Config.load(self.app.settings_path) if self.app.settings_path.exists() else Config()
                self.populate(self.app.config)
                self.refreshPreview_(sender)
            except (ValueError, OSError) as error:
                rumps.alert('Could not reload menu', str(error))

        @objc.python_method
        def show(self):
            A.NSApp.activateIgnoringOtherApps_(True)
            self.source_label.setStringValue_('Source: ' + str(self.app.pending_card.root) if self.app.pending_card else 'No source selected')
            self.save_button.setTitle_('Save & review transfer' if self.app.pending_card else 'Save menu')
            self.window.makeKeyAndOrderFront_(None)

    class TransferBar(A.NSView):
        def initWithFrame_(self, frame):
            self = objc.super(TransferBar, self).initWithFrame_(frame)
            if self is not None:
                self.fraction = None
                self.active = False
                self.setAccessibilityElement_(True)
                self.setAccessibilityRole_(A.NSAccessibilityProgressIndicatorRole)
                self.setAccessibilityLabel_('Transfer progress')
            return self

        @objc.python_method
        def update(self, progress, active):
            self.active = active
            self.fraction = (min(progress.files_done, progress.files_total) / progress.files_total
                             if progress.files_total else None)
            self.setAccessibilityValue_(str(progress.files_done) + ' of ' + str(progress.files_total) + ' files processed' if progress.files_total is not None else 'Preparing — total not known yet')
            self.setNeedsDisplay_(True)

        def drawRect_(self, dirty):
            bounds = self.bounds()
            A.NSColor.controlBackgroundColor().setFill()
            A.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, 5, 5).fill()
            width = bounds.size.width
            if self.fraction is not None:
                fill = A.NSMakeRect(0, 0, width * self.fraction, bounds.size.height)
            elif self.active:
                # An indeterminate moving bar, never a guessed completion percentage.
                segment = width * 0.2
                fill = A.NSMakeRect((width - segment) * ((monotonic() % 1.5) / 1.5), 0, segment, bounds.size.height)
            else:
                return
            A.NSColor.systemGreenColor().setFill()
            A.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(fill, 5, 5).fill()

    class TransferWindow(NSObject):
        def initWithApp_(self, app):
            self = objc.super(TransferWindow, self).init()
            if self is None:
                return None
            self.app = app
            self.window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                A.NSMakeRect(0, 0, 650, 420), A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable | A.NSWindowStyleMaskMiniaturizable | A.NSWindowStyleMaskResizable,
                A.NSBackingStoreBuffered, False)
            self.window.setTitle_('NomNom — Transfer Status')
            self.window.setLevel_(A.NSFloatingWindowLevel)
            self.window.setHidesOnDeactivate_(False)
            self.window.setReleasedWhenClosed_(False)
            self.window.setDelegate_(self)
            self.window.center()
            view = self.window.contentView()
            self.phase = A.NSTextField.alloc().initWithFrame_(A.NSMakeRect(20, 365, 610, 30))
            self.phase.setEditable_(False)
            self.phase.setBezeled_(False)
            self.phase.setDrawsBackground_(False)
            self.phase.setFont_(A.NSFont.boldSystemFontOfSize_(18))
            self.phase.setStringValue_('Ready for a transfer')
            view.addSubview_(self.phase)
            self.bar = TransferBar.alloc().initWithFrame_(A.NSMakeRect(20, 340, 610, 14))
            self.bar.setAutoresizingMask_(A.NSViewWidthSizable)
            view.addSubview_(self.bar)
            scroll = A.NSScrollView.alloc().initWithFrame_(A.NSMakeRect(20, 65, 610, 260))
            scroll.setHasVerticalScroller_(True)
            scroll.setAutoresizingMask_(A.NSViewWidthSizable | A.NSViewHeightSizable)
            self.details = A.NSTextView.alloc().initWithFrame_(A.NSMakeRect(0, 0, 610, 260))
            self.details.setEditable_(False)
            self.details.setSelectable_(True)
            self.details.setFont_(A.NSFont.userFixedPitchFontOfSize_(13))
            self.details.setString_('Start a transfer from the NomNom menu. Closing this window keeps NomNom running.')
            scroll.setDocumentView_(self.details)
            view.addSubview_(scroll)
            self.action = A.NSButton.alloc().initWithFrame_(A.NSMakeRect(455, 18, 175, 30))
            self.action.setTitle_('Dismiss')
            self.action.setBezelStyle_(A.NSBezelStyleRounded)
            self.action.setTarget_(self)
            self.action.setAction_('hideStatus:')
            self.action.setEnabled_(True)
            view.addSubview_(self.action)
            return self

        def windowShouldClose_(self, sender):
            # Hide explicitly instead of entering Cocoa's last-window close lifecycle.
            # Only the explicit Quit menu action terminates this accessory app.
            sender.orderOut_(None)
            return False

        def hideStatus_(self, sender):
            self.window.orderOut_(None)

        @objc.python_method
        def update(self, progress):
            phase = progress.phase
            if phase.startswith(('Fingerprinting', 'Copying', 'Verifying', 'Recording')):
                phase = 'Transferring files'
            self.phase.setStringValue_(phase)
            counts = progress.text().split('\n', 1)[1]
            self.details.setString_(counts + '\n\nSource (read only): ' + str(self.app.source_root or '—') + '\nDestination: ' + self.app.transfer_destination)
            self.action.setTitle_('Run in the background' if self.app.busy else 'Dismiss')
            self.bar.update(progress, self.app.busy)

        @objc.python_method
        def finish(self, summary):
            self.phase.setStringValue_(summary.title)
            self.details.setString_(summary.text)
            self.action.setTitle_('Dismiss')
            self.bar.active = False
            if summary.title in ('Transfer complete', 'Transfer finished — with notes'):
                self.bar.fraction = 1
            self.bar.setNeedsDisplay_(True)

        @objc.python_method
        def show(self):
            A.NSApp.activateIgnoringOtherApps_(True)
            self.window.makeKeyAndOrderFront_(None)

    class MenuBarMuncher(rumps.App):
        def __init__(self):
            # rumps otherwise creates ~/Library/Application Support/NomNom.
            # Redirect its unused support path to our designated local state root.
            import rumps.rumps as runtime
            support = runtime.application_support
            runtime.application_support = lambda name: str(state_directory())
            try:
                assets = Path(__file__).resolve().parents[1] / 'assets'
                super().__init__('NomNom', title='', icon=str(assets / 'menu-template.png'), template=True, quit_button='Quit NomNom')
            finally:
                runtime.application_support = support
            self.settings_path = state_directory() / 'settings.json'
            self.load_error = None
            try:
                self.config = Config.load(self.settings_path) if self.settings_path.exists() else Config()
            except (ValueError, OSError) as error:
                self.config = Config()
                self.load_error = str(error)
            self.menu = ['Show Transfer Status…', 'Configure NomNom…', 'Import detected card…', 'Choose source folder…', 'Check cards now', 'Cancel transfer', 'Last transfer summary…', None, 'Ready for a nibble']
            self.menu['Cancel transfer'].set_callback(None)
            self.last_summary = None
            self.status = None
            self.latest_progress = Progress()
            self.transfer_destination = ''
            self._controller = self
            self.source_root = None
            self.pending_card = None
            self.pending_detected = False
            self.cancel_event = Event()
            self.executor = ThreadPoolExecutor(max_workers=1)
            self.events = queue.Queue()
            self.detector = MacOSDetector()
            self.seen = set()
            self.manual_detection = False
            self.scanning = False
            self.busy = False
            self.settings = None
            self.timer = rumps.Timer(self.tick, 3)
            self.timer.start()
            self.ui_timer = rumps.Timer(self.process_events, 0.1)
            self.ui_timer.start()

        def ensure_access(self):
            # Retain and reattach the native template after launch and on timer ticks.
            self._status_item = self._nsapp.nsstatusitem
            self._status_item.setVisible_(True)
            self._status_item.setBehavior_(0)
            button = self._status_item.button()
            button.setImage_(self._icon_nsimage)
            self._status_item.setLength_(24)
            button.setTitle_('' if button.image() is not None else 'N')
            button.setImagePosition_(A.NSImageOnly if button.image() is not None else A.NSNoImage)
            button.setToolTip_('NomNom — open the menu for Transfer Status')
            button.setAccessibilityLabel_('NomNom menu')
            A.NSApp.setActivationPolicy_(A.NSApplicationActivationPolicyAccessory)

        @rumps.clicked('Show Transfer Status…')
        def show_status(self, sender=None):
            if self.status is None:
                self.status = TransferWindow.alloc().initWithApp_(self)
            self.status.show()

        @rumps.clicked('Configure NomNom…')
        def configure(self, sender):
            if self.settings is None:
                self.settings = SettingsWindow.alloc().initWithApp_(self)
            self.settings.show()
            if self.load_error:
                rumps.alert('Settings need attention', self.load_error)
                self.load_error = None

        @rumps.clicked('Choose source folder…')
        def folder(self, sender):
            if self.settings is None:
                self.settings = SettingsWindow.alloc().initWithApp_(self)
            if self.busy:
                return
            source = self.settings.picker(True, source=True)
            if source:
                card = SimulatedDetector(source, 'folder:' + str(source.resolve())).inserted()
                if self.config.destination:
                    try:
                        validate_destination(self.config.destination, [card.root])
                    except (ValueError, OSError, RuntimeError):
                        rumps.alert('Choose the source, not the destination',
                                    'The selected folder overlaps your destination. Select the SD card or folder containing files to import. Your destination has not changed.')
                        return
                self.offer(card)

        @rumps.clicked('Check cards now')
        def check(self, sender):
            self.seen.clear()
            self.tick(None)

        def sources(self):
            return [self.source_root] if self.source_root is not None else []

        @rumps.clicked('Cancel transfer')
        def cancel_transfer(self, sender):
            if self.busy:
                self.cancel_event.set()
                self.menu['Ready for a nibble'].title = 'Stopping after current file…'
                self.latest_progress = Progress('Cancellation requested — finishing current file', self.latest_progress.files_done, self.latest_progress.files_total, self.latest_progress.bytes_transferred, self.latest_progress.current_file, self.latest_progress.verified, self.latest_progress.failures)
                self.show_status(None)
                self.status.update(self.latest_progress)

        @rumps.clicked('Last transfer summary…')
        def last_transfer(self, sender):
            if self.busy:
                self.show_status(None)
                self.status.update(self.latest_progress)
            elif self.last_summary:
                self.show_status(None)
                self.status.finish(self.last_summary)
            else:
                rumps.alert('No transfers yet', 'A summary will appear after your first transfer.')

        def present_summary(self, summary):
            self.last_summary = summary
            self.menu['Ready for a nibble'].title = summary.title
            try:
                rumps.notification('NomNom — ' + summary.title, '', summary.notification)
            except Exception:
                # Notification Center may be disabled or unavailable for a CLI-launched app.
                pass
            # Respect Run in the background: completion updates the retained
            # summary without stealing focus or reopening a deliberately hidden window.
            if self.status is None:
                self.show_status(None)
            self.status.finish(summary)

        @rumps.clicked('Import detected card…')
        def import_detected(self, sender):
            if self.busy:
                return
            if self.pending_card is not None:
                self.review_pending()
            else:
                self.seen.clear()
                self.manual_detection = True
                self.tick(None)
                self.menu['Ready for a nibble'].title = 'Checking for a source card…'

        def offer(self, card, detected=False):
            if self.busy:
                return
            if detected:
                if not self.config.prompt_on_insert:
                    return
                choice = rumps.alert('NomNom has identified a snack',
                                     'External device: {}\n\nWould you like NomNom to eat this snack? You will review all settings before starting a transfer.'.format(card.root),
                                     ok='Eat this snack', cancel='Not now', other="Don’t ask again")
                if choice == -1:
                    updated = copy.deepcopy(self.config)
                    updated.prompt_on_insert = False
                    try:
                        updated.save(self.settings_path)
                        self.config = updated
                        if self.settings:
                            self.settings.insertion_prompt.setState_(A.NSControlStateValueOff)
                    except (ValueError, OSError) as error:
                        rumps.alert('Could not save insertion preference', str(error))
                    return
                if choice != 1:
                    return
            self.source_root = card.root
            self.pending_card = card
            self.pending_detected = detected
            self.menu['Ready for a nibble'].title = 'Confirm destination for pending card'
            if detected or not self.config.destination or self.load_error:
                self.configure(None)
            else:
                self.review_pending()

        def review_pending(self):
            card = self.pending_card
            if self.busy or card is None:
                return
            if not card.root.is_dir():
                rumps.alert('Source unavailable', 'The source was removed. Reinsert the card or choose a source folder.')
                return
            try:
                self.config.validate(True)
                validate_destination(self.config.destination, [card.root])
            except (ValueError, OSError, RuntimeError) as error:
                rumps.alert('Destination unavailable', str(error))
                self.configure(None)
                return
            message = 'Source (read only): {}\n\nDestination: {}\n\nMode: {}\n\nStart a verified local transfer?'.format(card.root, self.config.destination, self.config.mode.title())
            if rumps.alert('Review transfer', message, ok='Start', cancel='Not now') != 1:
                # No transfer began: deferring is not a cancellation or an outcome.
                self.menu['Ready for a nibble'].title = 'Ready when you are — review settings'
                self.configure(None)
                self.settings.preview_label.setStringValue_('No transfer started. Review your settings whenever you are ready.')
                return
            self.pending_card = None
            self.pending_detected = False
            if self.settings:
                self.settings.window.orderOut_(None)
            self.busy = True
            self.cancel_event.clear()
            self.menu['Cancel transfer'].set_callback(self.cancel_transfer)
            self.menu['Ready for a nibble'].title = 'Preparing transfer…'
            self.transfer_destination = self.config.destination
            self.latest_progress = Progress('Preparing transfer')
            self.show_status(None)
            self.status.update(self.latest_progress)
            config = copy.deepcopy(self.config)
            def work():
                try:
                    self.events.put(('result', run(card, config, state_directory(), cancel=self.cancel_event, progress=lambda update: self.events.put(('progress', update)))))
                except Exception as error:
                    self.events.put(('error', interrupted_summary(config.destination, error)))
            self.executor.submit(work)

        def process_events(self, sender=None):
            if self.status and self.status.bar.active and self.status.bar.fraction is None:
                self.status.bar.setNeedsDisplay_(True)
            while not self.events.empty():
                kind, value = self.events.get_nowait()
                if kind == 'progress':
                    self.latest_progress = value
                    if self.status:
                        self.status.update(value)
                elif kind == 'cards':
                    self.scanning = False
                    current = {(c.identity, str(c.root)) for c in value}
                    new = [c for c in value if (c.identity, str(c.root)) not in self.seen]
                    if not self.busy:
                        if self.pending_card is not None:
                            if self.pending_detected and (self.pending_card.identity, str(self.pending_card.root)) not in current:
                                self.pending_card = None
                                self.pending_detected = False
                                self.source_root = None
                                self.menu['Ready for a nibble'].title = 'Source card removed — waiting for a card'
                                if self.settings:
                                    self.settings.source_label.setStringValue_('Source card removed')
                            else:
                                continue
                        # Offer one card per tick so simultaneous insertions remain pending.
                        self.seen.intersection_update(current)
                        if new:
                            card = new[0]
                            self.seen.add((card.identity, str(card.root)))
                            manual = self.manual_detection
                            self.manual_detection = False
                            self.offer(card, detected=not manual)
                elif kind == 'scan-error':
                    self.scanning = False
                    self.menu['Ready for a nibble'].title = 'Card detection unavailable — choose a source folder'
                else:
                    self.busy = False
                    self.menu['Cancel transfer'].set_callback(None)
                    self.present_summary(value if kind == 'error' else summarize(value))
        def tick(self, sender):
            self.ensure_access()
            self.process_events()
            if not self.scanning and not self.busy:
                self.scanning = True
                def scan():
                    try:
                        self.events.put(('cards', self.detector.mounted_cards()))
                    except Exception as error:
                        self.events.put(('scan-error', str(error)))
                self.executor.submit(scan)

    image = A.NSImage.alloc().initWithContentsOfFile_(str(Path(__file__).resolve().parents[1] / 'assets' / 'NomNom.png'))
    A.NSApplication.sharedApplication().setApplicationIconImage_(image)
    import rumps.rumps as runtime
    original_delegate = runtime.NSApp

    class NomNomApplicationDelegate(original_delegate):
        def applicationDidFinishLaunching_(self, notification):
            objc.super(NomNomApplicationDelegate, self).applicationDidFinishLaunching_(notification)
            self._app['_controller'].ensure_access()

        def applicationShouldTerminateAfterLastWindowClosed_(self, application):
            return False

        def applicationShouldHandleReopen_hasVisibleWindows_(self, application, visible):
            self._app['_controller'].show_status(None)
            return True

    runtime.NSApp = NomNomApplicationDelegate
    app = MenuBarMuncher()
    rumps.events.before_start.register(app.ensure_access)
    try:
        app.run()
    finally:
        runtime.NSApp = original_delegate


if __name__ == '__main__':
    main()
