"""Verify open/Launch Services startup with no hardware detection or ingestion."""
import subprocess
import tempfile
from pathlib import Path


def main():
    app = Path(__file__).resolve().parents[1] / 'dist' / 'NomNom.app'
    for flag in ('--smoke-report', '--status-smoke-report', '--device-smoke-report'):
        check_launch(app, flag)


def check_launch(app, flag):
    with tempfile.TemporaryDirectory(prefix='nomnom-launchservices-test-') as folder:
        root = Path(folder)
        report, log = root / 'report.txt', root / 'launch.log'
        result = subprocess.run(['/usr/bin/open', '-n', '-W', '--stdout', str(log), '--stderr', str(log), str(app), '--args', flag, str(report)], capture_output=True, text=True, timeout=45)
        if log.exists():
            print(log.read_text())
        if result.returncode != 0:
            raise RuntimeError('Launch Services rejected NomNom: ' + result.stderr)
        if not report.exists() or report.read_text() != 'PASSED':
            raise RuntimeError('Native app launch did not complete its isolated smoke check')
        print('Launch Services and isolated native startup check passed')


if __name__ == '__main__':
    main()
