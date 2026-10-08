# Changelog

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
