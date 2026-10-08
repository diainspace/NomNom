"""Build a project-local, ad-hoc-signed native launcher; no system installation."""
import json
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


def build_bundle(output=None):
    if sys.platform != 'darwin':
        raise RuntimeError('The local app launcher must be built on macOS')
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
    # Launch Services needs a native application executable. Do not resolve the
    # venv interpreter symlink: Python needs the venv path to find its packages.
    interpreter = json.dumps(sys.executable)
    source_path = json.dumps(str(root / 'src'))
    code = '''#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
int main(int argc, char **argv) {
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1);
    setenv("PYTHONPATH", SOURCE_PATH, 1);
    unsetenv("__PYVENV_LAUNCHER__");
    char **args = calloc((size_t)argc + 4, sizeof(char *));
    if (!args) { perror("NomNom allocation"); return 1; }
    args[0] = INTERPRETER;
    args[1] = "-m";
    args[2] = "nomnom.platforms.bundle_launcher";
    for (int i = 1; i < argc; i++) args[i + 2] = argv[i];
    execv(INTERPRETER, args);
    perror("NomNom could not start its project interpreter");
    return 1;
}
'''.replace('SOURCE_PATH', source_path).replace('INTERPRETER', interpreter)
    subprocess.run(['/usr/bin/xcrun', 'clang', '-x', 'c', '-', '-o', str(launcher)], input=code, text=True, check=True, capture_output=True)
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(bundle)], check=True, capture_output=True)
    return bundle


if __name__ == '__main__':
    print(build_bundle())
