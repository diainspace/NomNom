# Changelog

## Automatic insertion snacks

- Add a local per-user insertion watcher and LaunchAgent installer for mounted SD cards and other external physical volumes.
- Offer Eat this snack, Not now, and Don’t ask again before configuration; never auto-authorize copying.
- Persist a default-on insertion-prompt preference with immediate settings re-enable, while preserving manual use.
- Keep device checks metadata-only and avoid duplicate UI launches.

## Green progress and background controls

- Replace the spinner with a green progress bar driven by actual processed-file totals, with an indeterminate bar before totals are known.
- Keep the status window floating above ordinary windows and simplify repetitive transfer-phase headings.
- Replace the dialog’s Cancel transfer button with Run in the background while working and Dismiss afterward; preserve menu-based reopening and cancellation.

## Review settings before starting

- Destination selection saves the destination without prematurely opening transfer review or saving unrelated edits.
- Only the explicit bottom Save & review transfer action cues Start/Not now from the settings form.
- Not now returns to settings with the card pending and does not report an unstarted transfer as cancelled.

## Finished transfers and selection notes

- Say “Transfer finished — with notes” when an attempt has ended with verified files and reported issues, rather than implying it is still partly in progress.
- Explain skipped files as exclusions from the user’s file-selection settings; retain actual issue counts and details.
- Keep incomplete backups explicitly labeled incomplete and preserve engine success/failure semantics.

## Native application identity and menu registration

- Embed framework Python in the native launcher instead of replacing NomNom with Python.app, preserving the macOS application identity.
- Refresh menu registration after Cocoa launch and explicitly reattach the template artwork.
- Validate bundle identity and native status-item window visibility with synthetic transfers.

## Persistent compact menu icon

- Keep the menu-bar icon compact at 24 points, removing the text label that consumes scarce menu-bar space.
- Reassert item visibility on timer ticks, retain the status item, and test restoration after visibility is cleared.

## Window-close lifecycle hardening

- Explicitly hide configuration and transfer windows when their close button is used, keeping the accessory app and worker running.
- Leave all windows hidden across real event-loop turns in native regression tests before reopening through the Cocoa menu.

## Transfer visibility and window access

- Open a retained native status window before background preparation starts, with measured phase, file, and byte updates.
- Keep the menu-bar-only app accessible through a visible icon, NomNom label, and Show Transfer Status action. Closing the window leaves transfers running.
- Retain actual completion, cancellation, and failure summaries; validate live progress and reopening through native synthetic transfers.
- Use the approved dumpling-box app artwork and monochrome menu-bar concept.

## Local app launch repair

- Replace the shell-script bundle executable with a native Mach-O launcher and local ad-hoc signature to fix Launch Services error -10669.
- Keep the virtual-environment interpreter path intact and clear inherited Python launcher hints.
- Add an isolated `open`/Launch Services regression that disables hardware and ingestion, alongside executable-format and signature validation.

## Destination persistence and icons

- Persist explicit destination selection immediately, including without a pending card; cancelling preserves saved settings.
- Reuse the saved destination in automatic review and manual ingest, without reopening setup unnecessarily.
- Add matching menu bar/app icon assets and a project-local unsigned Finder launcher builder.
- Extend synthetic and native regressions for immediate persistence, cancelled selection, and automatic/manual destination reuse.

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
