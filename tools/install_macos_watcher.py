"""Install/uninstall only NomNom's per-user insertion LaunchAgent."""
import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = 'com.nomnom.insertion-watcher'
ROOT = Path(__file__).resolve().parents[1]


def agent_spec(root, interpreter, state):
    return {'Label': LABEL,
            'ProgramArguments': [str(interpreter), '-m', 'nomnom.platforms.macos_watcher', '--app', str(root / 'dist/NomNom.app')],
            'EnvironmentVariables': {'PYTHONPATH': str(root / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'},
            'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10,
            'StandardOutPath': str(state / 'watcher.log'), 'StandardErrorPath': str(state / 'watcher.log')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('This per-user agent requires macOS')
    target = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    domain = 'gui/' + str(os.getuid())
    if args.uninstall:
        subprocess.run(['/bin/launchctl', 'bootout', domain + '/' + LABEL], check=True)
        target.unlink()
        print('Removed NomNom insertion watcher')
        return
    if target.exists():
        raise SystemExit('Watcher agent already exists; refusing to replace it')
    if not (ROOT / 'dist/NomNom.app').is_dir():
        raise SystemExit('Build dist/NomNom.app first')
    sys.path.insert(0, str(ROOT / 'src'))
    from nomnom.config import state_directory
    state = state_directory()
    state.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        plistlib.dump(agent_spec(ROOT, sys.executable, state), stream)
    try:
        subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(target)], check=True)
    except Exception:
        target.unlink()  # Roll back only the new file we just created.
        raise
    print('Enabled per-user insertion watcher: ' + str(target))


if __name__ == '__main__':
    main()
