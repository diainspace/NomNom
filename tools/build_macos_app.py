"""Build a local, unsigned launcher with NomNom's app icon; no system install."""
import plistlib
import shlex
import shutil
import sys
from pathlib import Path


def build_bundle(output=None):
    root = Path(__file__).resolve().parents[1]
    bundle = Path(output) if output is not None else root / 'dist' / 'NomNom.app'
    macos = bundle / 'Contents' / 'MacOS'
    resources = bundle / 'Contents' / 'Resources'
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / 'src/nomnom/assets/NomNom.icns', resources / 'NomNom.icns')
    info = {'CFBundleName': 'NomNom', 'CFBundleDisplayName': 'NomNom',
            'CFBundleIdentifier': 'com.nomnom.ingest', 'CFBundleVersion': '0.2.0',
            'CFBundleShortVersionString': '0.2.0', 'CFBundlePackageType': 'APPL',
            'CFBundleExecutable': 'NomNom', 'CFBundleIconFile': 'NomNom.icns', 'LSUIElement': True}
    with (bundle / 'Contents' / 'Info.plist').open('wb') as stream:
        plistlib.dump(info, stream)
    launcher = macos / 'NomNom'
    launcher.write_text('#!/bin/sh\nexport PYTHONDONTWRITEBYTECODE=1\nexport PYTHONPATH=' + shlex.quote(str(root / 'src')) + '\nexec ' + shlex.quote(sys.executable) + ' -m nomnom.platforms.macos_app\n')
    launcher.chmod(0o755)
    return bundle


if __name__ == '__main__':
    print(build_bundle())
