"""Native macOS configuration UI. Optional Cocoa imports stay in this module."""
import copy
import queue
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import Config, Rule, state_directory
from ..planning import preview
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
        from Foundation import NSObject
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
            self.button('Save menu', 540, 20, 120, 'save:')
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
        def picker(self, directories):
            panel = A.NSOpenPanel.openPanel()
            panel.setCanChooseDirectories_(directories)
            panel.setCanChooseFiles_(not directories)
            panel.setAllowsMultipleSelection_(False)
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
            selected = self.picker(True)
            if selected:
                self.destination.setStringValue_(str(selected))
                self.refreshPreview_(sender)

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
                config.save(self.app.settings_path)
                self.app.config = config
                self.preview_label.setStringValue_('Menu saved. NomNom is ready for the next card.')
            except (ValueError, OSError) as error:
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
            self.window.makeKeyAndOrderFront_(None)

    class MenuBarMuncher(rumps.App):
        def __init__(self):
            # rumps otherwise creates ~/Library/Application Support/NomNom.
            # Redirect its unused support path to our designated local state root.
            import rumps.rumps as runtime
            support = runtime.application_support
            runtime.application_support = lambda name: str(state_directory())
            try:
                super().__init__('NomNom', title='NomNom', quit_button='Quit NomNom')
            finally:
                runtime.application_support = support
            self.settings_path = state_directory() / 'settings.json'
            self.load_error = None
            try:
                self.config = Config.load(self.settings_path) if self.settings_path.exists() else Config()
            except (ValueError, OSError) as error:
                self.config = Config()
                self.load_error = str(error)
            self.menu = ['Configure NomNom…', 'Ingest folder…', 'Check cards now', None, 'Ready for a nibble']
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

        @rumps.clicked('Ingest folder…')
        def folder(self, sender):
            if self.settings is None:
                self.settings = SettingsWindow.alloc().initWithApp_(self)
            source = self.settings.picker(True)
            if source:
                self.offer(SimulatedDetector(source, 'folder:' + str(source.resolve())).inserted())

        @rumps.clicked('Check cards now')
        def check(self, sender):
            self.seen.clear()
            self.tick(None)

        def offer(self, card):
            if self.busy:
                return
            if not self.config.destination or self.load_error:
                self.configure(None)
                return
            if rumps.alert('NomNom found a snack', '{}\n\n{} → {}\n\nStart a verified local transfer?'.format(card.root, self.config.mode.title(), self.config.destination), ok='Start', cancel='Not now') != 1:
                return
            self.busy = True
            self.menu['Ready for a nibble'].title = 'Munching…'
            config = copy.deepcopy(self.config)
            def work():
                try:
                    self.events.put(('result', run(card, config, state_directory())))
                except Exception as error:
                    self.events.put(('error', str(error)))
            self.executor.submit(work)

        def tick(self, sender):
            while not self.events.empty():
                kind, value = self.events.get_nowait()
                if kind == 'cards':
                    self.scanning = False
                    current = {(c.identity, str(c.root)) for c in value}
                    new = [c for c in value if (c.identity, str(c.root)) not in self.seen]
                    if not self.busy:
                        # Offer one card per tick so simultaneous insertions remain pending.
                        self.seen.intersection_update(current)
                        if new:
                            card = new[0]
                            self.seen.add((card.identity, str(card.root)))
                            self.offer(card)
                elif kind == 'scan-error':
                    self.scanning = False
                    self.menu['Ready for a nibble'].title = 'Card detection unavailable — use Ingest folder'
                else:
                    self.busy = False
                    self.menu['Ready for a nibble'].title = 'Ready for a nibble'
                    if kind == 'error':
                        rumps.alert('NomNom stopped safely', value)
                    else:
                        message = '{} copied, {} already verified, {} skipped.\n{}'.format(value.copied, value.duplicates, value.skipped, value.destination)
                        if value.failures:
                            message += '\nIncomplete: ' + '\n'.join(path + ': ' + error for path, error in value.failures[:8])
                        rumps.alert('Meal complete' if value.complete else 'Meal incomplete', message)
            if not self.scanning and not self.busy:
                self.scanning = True
                def scan():
                    try:
                        self.events.put(('cards', self.detector.mounted_cards()))
                    except Exception as error:
                        self.events.put(('scan-error', str(error)))
                self.executor.submit(scan)

    MenuBarMuncher().run()


if __name__ == '__main__':
    main()
