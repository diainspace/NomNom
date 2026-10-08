# NomNom® v0.1

Standalone, local SD-card photo ingestion for macOS development and eventual Raspberry Pi deployment. No external services, Dropbox integration, or dependency on codex-vite-sandbox.

## Run without installation

Python 3.9 or newer; no runtime or test dependencies.

```sh
PYTHONPATH=src python3 -m nomnom.cli tests/fixtures/simulated_sd \
  --card-id simulated-card-1 \
  --destination "$HOME/Pictures/NomNom" \
  --state-dir "$HOME/.local/state/nomnom"

PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The CLI requires an explicit destination. Its default state directory is `$XDG_STATE_HOME/nomnom` or `~/.local/state/nomnom`. Runtime state must be outside this repository. Source directories must not overlap destination or state directories. These commands create local runtime directories only when executed. A nonzero CLI exit status indicates failure; individual file failures appear in JSON output.

The included fixture is a generated one-pixel PNG, not a personal photograph. Tests also generate arbitrary bytes with photo extensions to exercise byte-preserving transfers.

## Architecture

- `detection/simulated.py`: `Detector` protocol, simulated insertion, and explicit stable card identity. Future platform adapters return the same `Card` object.
- `engine/discovery.py`: recursive, extension-based discovery; skips symlinks.
- `engine/organization.py`: configurable `Organizer` protocol. Default names are SHA-256 plus normalized extension in a flat destination directory.
- `engine/ingestion.py`: orchestrates source fingerprinting, duplicate verification, copying, source stability checks, and final publication.
- `engine/ledger.py`: SQLite records content fingerprints separately from card/path/content occurrences.
- `cli.py`: local configuration and result reporting.

No source writes, moves, deletes, or metadata restoration are performed. Reading may update access time according to filesystem mount settings. SHA-256 identifies content across cards and filenames. Duplicates are recorded only after checking that the recorded destination still contains matching bytes. A missing destination is recopied; a corrupt existing destination is preserved and reported as a collision.

A transfer writes to a temporary destination file, flushes and fsyncs it, verifies its size and hash, and rehashes the source. Device/inode, size, modification time, and change time are checked around transfer and before recording. A detected changing source is never recorded as successful. Publication uses an atomic hard link on the destination filesystem, preventing silent overwrites. The ledger transaction follows publication. Retrying after publication but before ledger commit verifies and adopts the existing matching file.

Occurrences are keyed by card identity, relative source path, and digest. Repeated identical occurrences update the same row; new content at the same path preserves the earlier occurrence. Card IDs must be assigned consistently by the caller. The ledger currently keeps one verified destination per content fingerprint, across configured destinations.

## Prototype limitations

- Physical card detection, UI, EXIF organization, video ingestion, and image decoding are not implemented. Discovery recognizes extensions rather than validating camera formats.
- Tested locally on macOS with Python 3.9.6. Raspberry Pi and other Python versions have not been tested.
- Source stability checks detect observed changes; no read-only application can guarantee a source stays unchanged after the final check without filesystem snapshots or coordination with writers.
- Use one ingestion process per state directory. Concurrent hostile filesystem mutation and symlink replacement are outside this prototype's guarantees.
- Destination filesystems must support hard links. Unsupported filesystems fail safely without recording success.
- Abrupt process termination can leave `.nomnom-*` temporary files. Normal failures clean them up. Automatic stale-temp cleanup is deferred.
- Power-loss durability of directory entries is not guaranteed: file bytes are fsynced, but destination directories are not. SQLite uses its default journaling. Every repeat import revalidates the recorded destination.
- Copies preserve bytes, not original filesystem timestamps or permissions. No full historical event log, ledger migrations, parallel transfer queue, or cancellation API yet.
