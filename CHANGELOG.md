# Changelog

## Startup and pending-card UX fix

- Always confirm destination setup before presenting Start, even when settings were previously saved.
- Keep detected cards pending through destination selection and Not now; selecting a destination saves settings and resumes transfer review.
- Separate Import detected card from Choose source folder, label source/destination dialogs, reset source-picker history, and prevent accidental destination selection from replacing the source.
- Clear pending detected cards when removed and add native regressions for the complete startup flow.

## v0.2 UX follow-up

- Reset the native destination picker directory on every use, enable New Folder, and reject resolved destinations on the source card while allowing other drives.
- Add completion notifications and reopenable summaries with verified outcome counts and distinct success, partial failure, failure, and cancellation states.
- Add safe between-file cancellation and preserve incomplete backup status.

## NomNom® v0.2: The Menu Bar Muncher

- Reframe NomNom as general-purpose SD-card ingestion and file distribution, with macOS as the primary deployment target.
- Add Organize, Preserve, and verified file-level Backup modes.
- Add portable validated JSON settings, ordered extension rules, routing, date hierarchy, optional EXIF dates, and a Canon Rebel preset.
- Add native macOS menu bar settings, folder pickers, rule editing, previews, and automatic local removable-volume detection with explicit transfer authorization.
- Add multiple destination-copy records and isolated/resumable backup sessions through additive SQLite migration.
- Account for empty directories and explicitly report unsupported symlinks and special files; incomplete backups never report complete status.
- Preserve the v0.1 engine API and its original tests.

## v0.1

- Local simulated SD-card photo discovery, verified non-overwriting copies, content fingerprints, source occurrences, and external SQLite runtime state.
