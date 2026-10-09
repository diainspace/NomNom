"""Checks generated public icon assets and local launcher metadata."""
import plistlib
import struct
import tempfile
import sys
import subprocess
import unittest
from pathlib import Path
from tools.build_macos_app import build_bundle


class IconTests(unittest.TestCase):
    def test_png_and_icns_assets(self):
        assets = Path(__file__).resolve().parents[1] / 'src/nomnom/assets'
        for name in ('NomNom.png', 'menu-template.png'):
            data = (assets / name).read_bytes()
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('!II', data[16:24]), (1254, 1254))
        data = (assets / 'NomNom.icns').read_bytes()
        self.assertEqual(data[:4], b'icns')
        self.assertEqual(struct.unpack('!I', data[4:8])[0], len(data))

    @unittest.skipUnless(sys.platform == 'darwin', 'Native bundle building requires macOS')
    def test_local_bundle_has_app_icon_and_executable(self):
        with tempfile.TemporaryDirectory(prefix='nomnom-bundle-test-') as folder:
            bundle = build_bundle(Path(folder) / 'NomNom.app')
            with (bundle / 'Contents/Info.plist').open('rb') as stream:
                info = plistlib.load(stream)
            self.assertEqual(info['CFBundleIconFile'], 'NomNom.icns')
            self.assertTrue(info['LSUIElement'])
            self.assertTrue((bundle / 'Contents/Resources/NomNom.icns').is_file())
            launcher = bundle / 'Contents/MacOS/NomNom'
            self.assertTrue(launcher.stat().st_mode & 0o111)
            self.assertIn(launcher.read_bytes()[:4], (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe'))
            subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(bundle)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
