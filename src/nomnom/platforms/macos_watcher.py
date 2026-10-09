"""Per-user local insertion watcher. Reads device metadata, never file contents."""
import argparse
import logging
import re
import subprocess
import time
from pathlib import Path
from ..config import Config, state_directory
from .macos_detection import MacOSDetector


class InsertionWatcher:
    def __init__(self, detector, settings, launch):
        self.detector, self.settings, self.launch = detector, Path(settings), launch
        self.seen = set()

    def poll(self):
        config = Config.load(self.settings) if self.settings.exists() else Config()
        cards = self.detector.mounted_cards()
        current = {(card.identity, str(card.root)) for card in cards}
        inserted = current - self.seen
        if config.prompt_on_insert and inserted:
            self.launch()
        self.seen = current


def launch_if_needed(app):
    # Read process metadata only. Do not reopen or duplicate an existing UI.
    executable = Path(app).resolve() / 'Contents/MacOS/NomNom'
    running = subprocess.run(['/usr/bin/pgrep', '-f', '^' + re.escape(str(executable)) + r'( |$)'], capture_output=True)
    if running.returncode == 0:
        return
    if running.returncode != 1:
        raise RuntimeError('Unable to check whether NomNom is already running')
    subprocess.run(['/usr/bin/open', '-g', str(app)], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    args = parser.parse_args()
    if not args.app.is_dir():
        raise SystemExit('Build NomNom.app before starting the insertion watcher')
    watcher = InsertionWatcher(MacOSDetector(), state_directory() / 'settings.json',
                               lambda: launch_if_needed(args.app))
    while True:
        try:
            watcher.poll()
        except Exception:
            logging.exception('Insertion detection unavailable; retrying')
        time.sleep(3)


if __name__ == '__main__':
    main()
