# NomNom® v0.2: The Menu Bar Muncher

**NomNom® is a standalone, general-purpose SD-card ingestion and file distribution application.** macOS is its primary target: a native menu bar utility detects mounted removable cards and asks before starting a verified local transfer. The configuration and ingestion engines work independently of the UI. No Raspberry Pi hardware, external server, or cloud service is required.

> NomNom® doesn't decide what's worth keeping. You decide what it eats and where it puts it.

## Three ways to munch

| Mode | What's on the menu? | Where does it go? |
| --- | --- | --- |
| **Organize** | Enabled extension rules; configurable treatment of other files | Route subfolders and optional date folders, in your chosen order |
| **Preserve** | The same extension selection | Original relative file paths beneath your destination; automatic routing and date folders are ignored |
| **Backup** | Every regular file, including hidden and extensionless files | A new, uniquely named backup folder with the complete directory hierarchy, including empty directories |

Backup is a **verified file-level backup**, not a disk image. Symlinks, special files, unreadable entries, transfer failures, and source changes are reported. A backup with any such failure is incomplete. Existing backups are never silently overwritten or combined. Filenames and file/directory access and modification timestamps are preserved where supported; permissions, extended attributes, filesystem creation dates, and disk structures are not cloned.

## Launch the macOS utility

From this project directory, using Python 3.9 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools
.venv/bin/python -m pip install -e '.[macos,exif]'
PYTHONDONTWRITEBYTECODE=1 .venv/bin/nomnom-menubar
```

A monochrome NomNom SD-card icon appears in the menu bar; macOS adapts it for light and dark appearances. Choose **Configure NomNom…**, pick a mode and destination, then edit the file-type rows. If a source is pending, the window shows its path and a **Save & review transfer** button; otherwise use **Save menu** to save settings without starting a transfer. Use **Eat** to enable a type, folder fields to route it in Organize, and arrows to change priority. The Canon Rebel preset starts with JPEG (`.jpg`, `.jpeg`) and RAW (`.cr2`) routes. Backup ignores extension rules.

Choose a folder hierarchy and a plain-language date layout such as **Year / Month / Day**. The date field also accepts a custom format such as `%Y-%m-%d`. **Capture date, then modified date** uses supported EXIF when available, with a filesystem modification-date fallback. Pick **Sample file…**, then **Preview** to see the planned path and date source. Samples on `/Volumes/<card>` use that volume as their source root; other samples use their parent directory. **Save menu** saves settings; **Reload** retrieves them. No JSON editing is needed.

When a card is detected, NomNom first opens configuration and keeps that card pending. Confirm a destination with **Choose…**, or keep the displayed destination with **Save & review transfer**. Choosing a destination always saves that destination immediately, even without a pending card. With a pending card, it also saves the current valid settings and opens a **Review transfer** dialog with explicitly labeled Source and Destination paths. Only **Start** authorizes ingestion. Cards already mounted at launch follow the same setup-first sequence. **Not now** leaves the source pending; **Import detected card…** resumes review using the saved destination without another source picker. A manual **Choose source folder…** selection also proceeds directly to review when a valid destination has already been saved. **Choose source folder…** is a separate, explicitly labeled source-selection command for local simulation. **Check cards now** checks for mounted cards again. The UI remains responsive during hashing/copying. Do not quit during an active transfer; interrupted backup sessions can be resumed through the CLI.

Detection polls local `diskutil` every three seconds on a background worker. It recognizes mounted, external removable/ejectable physical partitions with a volume UUID. This can include USB removable media as well as SD cards. Every transfer requires confirmation; no data is imported merely because a volume is detected. Some readers do not expose removable flags or a UUID; use **Choose source folder…** if detection cannot identify the card.

Runtime settings and the SQLite ledger default to `~/.local/state/nomnom`, or `$XDG_STATE_HOME/nomnom`. Installation files and the virtual environment remain in the project. Optional packages are downloaded during installation; the application itself makes no network requests.

## CLI and portable configuration

The original v0.1 invocation remains supported:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m nomnom.cli tests/fixtures/simulated_sd \
  --card-id simulated-card-1 --destination "$HOME/Pictures/NomNom"
```

For v0.2, use settings saved by the UI (or a portable copy of `presets/canon-rebel.json` with an absolute destination):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m nomnom.cli /Volumes/MY_CARD \
  --card-id MY_CARD_UUID --config "$HOME/.local/state/nomnom/settings.json" --preview
```

Remove `--preview` to authorize an actual transfer. Use `--destination` to override the configured root, and `--state-dir` to choose local runtime state outside the repository. Backup results include `session_id`; `--resume SESSION_ID` explicitly resumes that backup with unchanged card identity, source inventory, and configuration. An ordinary run always creates a new session, even with a custom backup name. JSON output includes `complete`; failures produce a nonzero exit status. Preview creates no destination or runtime directories.

## Tests

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

All fixtures are synthetic. The unchanged v0.1 suite remains in `tests/test_ingestion.py`; v0.2 cases are in `tests/test_v02.py`. The optional `tests/native_smoke.py` test runs the real menu bar event loop, settings window, preview, and save/reload against isolated temporary state with physical detection disabled. Physical reader behavior still requires hardware testing; automated detection tests use synthetic diskutil responses.

## Safety and limits

Sources are opened for reading only. Files are never moved, deleted, rewritten, or timestamp-restored on the source. Reading may update access times according to filesystem policy. Every completed copy is size/hash verified, with source metadata and content stability checks. Identical existing destination files are verified before reuse. Conflicting content is preserved and reported; there is no silent rename or overwrite.

Paths are validated against traversal, source/destination overlap, and symlinked target components. Runtime state cannot be inside the repository, source, or v0.2 destination. Settings and previews do not create destination folders. Backup accounts for unsupported entries rather than ignoring them.

Use one ingestion process per state directory. Filesystem snapshots and coordination with other writers are not provided; changes after the final source check and hostile concurrent path replacement cannot be prevented. The destination filesystem currently must support hard links for atomic non-overwriting publication. Unsupported filesystems fail safely. Power-loss durability of directory entries is not guaranteed. Abrupt termination can leave `.nomnom-*` temporary files. Automatic stale-file cleanup, signed `.app` packaging, login-item installation, and physical hardware validation are deferred.

EXIF uses optional Pillow. JPEG/TIFF metadata support is practical; Canon CR2 and other RAW/HEIC formats may fall back to modified time. EXIF times without timezone data are treated as camera-local calendar times; filesystem dates use local time. Raspberry Pi support is optional and untested, with no Pi-specific dependencies or influence on macOS design.

See [technical architecture](docs/architecture.md) and [release notes](CHANGELOG.md).

## Destination picker and transfer summaries

Every destination picker invocation starts at the configured destination if it is an existing valid directory outside the current source card; otherwise it starts at your home folder. It does not reuse the shared panel's navigation history. **New Folder** is enabled, including the native **Shift–Command–N** shortcut where macOS supports it. Creating a folder from the picker is an explicit user action; saving settings and previews still create no transfer destinations.

Source-card destinations are rejected when selecting/saving settings and again before transferring. Symbolic links are resolved for this check, including links to nonexistent subfolders beneath the card. A source under `/Volumes/<card>` protects the entire card, not just its DCIM directory. Other external destination drives remain allowed.

A completed attempt shows a Notification Center notification (subject to macOS notification settings), a native accessible summary, and a menu-bar status. **Last transfer summary…** reopens the latest summary during the current application session, even if Notification Center is unavailable. The summary reports copied, verified, already present, skipped, failed entries/issues, not processed, and destination. Verified includes both successfully copied files and matching existing files rehashed during the attempt; it is not an extra file count to add to copied. Failures can include filesystem entries and backup-wide errors, not just photographs.

**Cancel transfer** stops before the next file, after the current file finishes verification. Successfully completed files remain intact and recorded; an interrupted backup stays incomplete. Declining **Start** is also reported as cancellation. If an unexpected exception prevents final counts from being recovered, the summary says counts are unavailable rather than inventing zero counts. Success, partial completion, failure, and cancellation have distinct titles. No system notification settings are changed by NomNom.

The source-folder picker is titled **Choose source folder**, uses **Select source** as its action, and explicitly says to choose files to import rather than the destination. Its starting directory is independently reset to the known source or Home, and New Folder is disabled there. Accidentally selecting your destination as the source is rejected without replacing the pending card or changing your destination. Removing a pending detected card clears it; reinsert it to set up a new transfer.

## Menu bar and app icons

NomNom now includes a matching SD-card-with-a-bite mark: a monochrome template for the menu bar and an orange app icon. The running Cocoa application uses the app artwork. Public assets (`mark.svg`, PNGs, and `NomNom.icns`) are packaged with the Python application.

A local, unsigned Finder launcher is already generated at `dist/NomNom.app`. Quit any running instance before launching it:

```sh
open /Users/dianardozzi/Developer/NomNom/dist/NomNom.app
```

To regenerate the launcher after moving the checkout or virtual environment:

```sh
.venv/bin/python tools/build_macos_app.py
```

This launcher references the current checkout and interpreter; it is not a self-contained distributable and is not installed system-wide. Signing/notarization remain future work. To regenerate icon assets, run `.venv/bin/python tools/build_icons.py` with Pillow installed.
