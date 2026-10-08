"""Native macOS configuration UI. Optional Cocoa imports stay in this module."""
import copy
import queue
import sys
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import Config, Rule, state_directory
from ..planning import preview
from ..settings import select_destination
from ..destinations import configure_destination_panel, configure_source_panel, validate_destination
from ..reporting import summarize, interrupted_summary
from ..detection.simulated import SimulatedDetector
from ..engine.configured import run, RunResult
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
            self.preview_label = self.label('Pick a sample file to preview its destination.', 20, 67, 640, 46)
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
            self.draw_rules(config.rules)
            self.unmatched_folder = config.unmatched_folder

        @objc.python_method
        def read(self):
            return Config(mode=['organize', 'preserve', 'backup'][self.mode.indexOfSelectedItem()],
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
                    if self.app.pending_card is not None:
                        # Explicit folder selection confirms destination; Start still authorizes copying.
                        self.save_(sender)
                    else:
                        self.preview_label.setStringValue_('Destination saved. Choose a source or insert a card to import.')
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

    class MenuBarMuncher(rumps.App):
        def __init__(self):
            # rumps otherwise creates ~/Library/Application Support/NomNom.
            # Redirect its unused support path to our designated local state root.
            import rumps.rumps as runtime
            support = runtime.application_support
            runtime.application_support = lambda name: str(state_directory())
            try:
                assets = Path(__file__).resolve().parents[1] / 'assets'
                super().__init__('NomNom', icon=str(assets / 'menu-template.png'), template=True, quit_button='Quit NomNom')
            finally:
                runtime.application_support = support
            self.settings_path = state_directory() / 'settings.json'
            self.load_error = None
            try:
                self.config = Config.load(self.settings_path) if self.settings_path.exists() else Config()
            except (ValueError, OSError) as error:
                self.config = Config()
                self.load_error = str(error)
            self.menu = ['Configure NomNom…', 'Import detected card…', 'Choose source folder…', 'Check cards now', 'Cancel transfer', 'Last transfer summary…', None, 'Ready for a nibble']
            self.menu['Cancel transfer'].set_callback(None)
            self.last_summary = None
            self.source_root = None
            self.pending_card = None
            self.pending_detected = False
            self.cancel_event = Event()
            self.executor = ThreadPoolExecutor(max_workers=1)
            self.events = queue.Queue()
            self.detector = MacOSDetector()
            self.seen = set()
            self.scanning = False
            self.busy = False
            self.settings = None
            self.timer = rumps.Timer(self.tick, 3)
            self.timer.start()

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

        @rumps.clicked('Last transfer summary…')
        def last_transfer(self, sender):
            if self.last_summary:
                rumps.alert(self.last_summary.title, self.last_summary.text)
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
            rumps.alert(summary.title, summary.text)

        @rumps.clicked('Import detected card…')
        def import_detected(self, sender):
            if self.busy:
                return
            if self.pending_card is not None:
                self.review_pending()
            else:
                self.seen.clear()
                self.tick(None)
                self.menu['Ready for a nibble'].title = 'Checking for a source card…'

        def offer(self, card, detected=False):
            if self.busy:
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
                self.present_summary(summarize(RunResult(destination=self.config.destination, cancelled=True)))
                # Keep this source pending so configuring a new destination can resume the review.
                return
            self.pending_card = None
            self.pending_detected = False
            if self.settings:
                self.settings.window.orderOut_(None)
            self.busy = True
            self.cancel_event.clear()
            self.menu['Cancel transfer'].set_callback(self.cancel_transfer)
            self.menu['Ready for a nibble'].title = 'Munching…'
            config = copy.deepcopy(self.config)
            def work():
                try:
                    self.events.put(('result', run(card, config, state_directory(), cancel=self.cancel_event)))
                except Exception as error:
                    self.events.put(('error', interrupted_summary(config.destination, error)))
            self.executor.submit(work)

        def tick(self, sender):
            while not self.events.empty():
                kind, value = self.events.get_nowait()
                if kind == 'cards':
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
                            self.offer(card, detected=True)
                elif kind == 'scan-error':
                    self.scanning = False
                    self.menu['Ready for a nibble'].title = 'Card detection unavailable — choose a source folder'
                else:
                    self.busy = False
                    self.menu['Cancel transfer'].set_callback(None)
                    self.present_summary(value if kind == 'error' else summarize(value))
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
    MenuBarMuncher().run()


if __name__ == '__main__':
    main()
