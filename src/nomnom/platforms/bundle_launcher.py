"""Entry point for the project-local macOS app and isolated launch testing."""
import argparse
import os
import runpy
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='NomNom local application launcher')
    parser.add_argument('--smoke-report', type=Path, help='Developer check: disable hardware/ingestion and write a test result')
    parser.add_argument('--status-smoke-report', type=Path, help='Developer live status test with synthetic transfers only')
    arguments = parser.parse_args()
    if arguments.smoke_report or arguments.status_smoke_report:
        test = Path(__file__).resolve().parents[3] / 'tests' / ('native_status_smoke.py' if arguments.status_smoke_report else 'native_smoke.py')
        os.environ['NOMNOM_SMOKE_REPORT'] = str((arguments.status_smoke_report or arguments.smoke_report).resolve())
        runpy.run_path(str(test), run_name='__main__')
    else:
        from .macos_app import main as app_main
        app_main()


if __name__ == '__main__':
    main()
