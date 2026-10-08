# NomNom architecture

The macOS application is primary. Platform integrations sit behind adapters; importing the core never imports rumps or Cocoa. No runtime network services are used.

## Boundaries

- `config.py`: portable dataclasses, schema validation, atomic JSON persistence, Canon Rebel defaults. Settings schema version is 1; product release is 0.2.
- `planning.py`: extension selection, ordered-rule routing, date extraction, relative paths, read-only preview. It creates no directories.
- `engine/configured.py`: filesystem inventory, configured ingestion orchestration, session handling, results.
- `engine/transfer.py`: verified source-stable, non-overwriting copying. Reuses v0.1 fingerprint and signature primitives.
- `engine/ledger.py`: persistence and additive migration.
- `platforms/macos_detection.py`: injectable local diskutil adapter implementing `VolumeDetector`.
- `platforms/macos_app.py`: rumps status menu and AppKit controls. Main-thread UI, serialized background detection/ingestion, queued results. No browser or server.
- `engine/ingestion.py`, legacy `discover`, and `FlatOrganizer`: original v0.1 behavior and public entry point, preserved for compatibility.

## Selection and precedence

Rules are evaluated in JSON list/UI row order. The first enabled matching extension wins, case-insensitively. Disabled rows do not block later enabled matches; if no enabled match exists for an explicitly configured extension, that extension is excluded. Truly unmatched files use `skip`, `include`, or `error`. Preserve applies selection but ignores route folders. Backup bypasses selection and accounts for every entry.

Each rule has a `condition` discriminator, currently `extension`. Unknown condition types are rejected, allowing later explicit schema evolution rather than silently misinterpreting a new condition. Route folders are relative to the destination root. The hierarchy values are `date-extension`, `extension-date`, `date`, `extension`, and `none`. Route folder names supply the type component; they can group multiple extensions.

Date sources are an ordered list of `exif` and `mtime`, always ending with `mtime`. DateTimeOriginal is read from the EXIF sub-IFD where available. Missing optional packages, unsupported formats, absent metadata, or invalid dates fall back to mtime. Supported date directives are `%Y %y %m %d %H %M %S %j %%`; the rendered folder is validated as a safe relative path.

## Ledger migration and deduplication

Existing `contents` and `occurrences` tables remain intact. The additive migration creates `copies` and `backup_sessions` and seeds copy records from v0.1 destinations. Content identity is SHA-256, separate from source occurrence identity `(card_id, source_path, digest)`. Each recorded destination has its own copy row.

Organize deduplicates verified content within the planned route directory. It does not let another destination root satisfy a transfer. Preserve and Backup require the exact target path to exist and verify; identical files at different source paths are each retained. This ensures complete hierarchy preservation. Legacy v0.1 retains its original global content deduplication semantics.

Copy publication precedes ledger recording. Retrying verifies/adopts a matching file if a process stopped between publication and recording. A conflicting destination is a failure. Source changes observed during transfer are failures and are not recorded as successes. Older occurrence records describe earlier successful imports rather than current source state.

## Backup sessions

Every ordinary backup creates `<custom-name-or-timestamp>-<UUID>` beneath the explicitly selected root. A persisted manifest records relative file paths, digests, sizes, mtimes, directories, and unsupported entries. Session status starts incomplete. Explicit resume requires identical card identity, source root, configuration, and manifest. Completed existing files are reverified rather than overwritten. Modified or added source files reject resume; start a new session instead.

Backup enumerates symlinks without following them and reports them, along with special files and unreadable entries. It retains empty directories. An ending inventory scan detects changes during backup. Every entry/transfer/timestamp failure prevents complete status. Unreadable manifests may abort before transfer; callers must report the error rather than success. This is not an atomic filesystem snapshot or a disk image.

## Operational limits

Hard-link support is required at the destination for atomic publication. No source file mutation is performed; access times may change from reads. File bytes and atime/mtime are preserved for backup where supported; original directory permissions, xattrs, and creation times are outside scope. Symlinks and special entries are unsupported and make backup incomplete. Concurrent processes and hostile filesystem mutation are outside v0.2 guarantees. No Pi modules are dependencies of the macOS app. GUI packaging and code signing remain future work.
