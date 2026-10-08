# NomNom development workflow

- NomNom is standalone; macOS is the primary deployment target. Keep configuration, planning, ingestion, detection, and UI separate. Optional platforms must not introduce dependencies into the macOS application.
- Use computer access as needed for development and testing. Use synthetic fixtures; request approval before accessing personal photographs.
- Run automated tests and review the complete change before committing. Preserve the v0.1 tests and behavior.
- Automatically commit successfully validated changes with descriptive messages and push to the existing GitHub repository's `main` branch. Check remote state first; never force-push or rewrite published history. Report test results, commit hash, and push status after each completed development task.
- Never commit credentials, runtime databases, temporary files, or personal data. Runtime settings and ledger belong outside the repository. Review staged files before committing.
- Request approval before destructive operations or system-wide changes. Explain unusual permission requests before proceeding.
- Never modify or delete ingestion source files. Verify every completed copy; never silently overwrite a destination. Incomplete backups must never report success.
- Keep application operations local. No Dropbox, external server, or cloud-service integration unless explicitly authorized in a later task. Git push authorization applies to source-code version control only.
