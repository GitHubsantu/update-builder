# StreamForge Update Builder

A standalone Windows desktop tool that creates **delta update ZIP packages**
for a Laravel project by automatically detecting changed files with Git.

It is a **local development utility**. It never modifies your Laravel
project, never touches `composer.json`, and never changes Git history —
it only *reads* Git status and packages the files you select.

## What it does

1. You select your Laravel project's root folder (the one containing `.git`
   and `composer.json`).
2. It reads `composer.json` and detects the current application version
   (checking `extra.version` / `extra.app-version` / `extra.application-version`
   before falling back to the top-level `version` field, since that field is
   often just the Composer package version, not your product version).
3. It runs read-only Git commands (`git status --porcelain`, `git diff
   --name-only`, `git ls-files --others --exclude-standard`, etc.) to detect
   modified, added, deleted, renamed, and untracked files in your working tree.
4. You review and select which changes to include, enter the new version
   number, and click **Build Update ZIP**.
5. It produces `updates/update-<version>.zip` containing:
   - `update-manifest.json` — machine-readable manifest with the product
     name, from/to version, file list (with SHA-256 hashes), deleted files,
     and renamed files, ready to be consumed by a Laravel-side updater.
   - The changed files themselves, preserving their exact project-relative
     folder structure (e.g. `app/Http/Controllers/VersionController.php`).

## Safety

- Only a fixed allow-list of read-only Git subcommands can ever run
  (`status`, `diff`, `ls-files`, `rev-parse`, `cat-file`, `rev-list`,
  read-only `config`). Anything else — `commit`, `push`, `pull`, `reset`,
  `checkout`, `clean`, `stash`, `merge`, `rebase`, etc. — is hard-refused
  by the code itself, even if something upstream tried to call it.
- Every file path is validated to stay inside the selected project root
  before being added to the ZIP, blocking path traversal and symlinks that
  point outside the project.
- `.env`, `.env.*`, private keys, `*.pem`, `*.key`, and other
  credential-looking files are excluded by default and only included if you
  explicitly enable the override in **Manage Exclusions**.
- `composer.json` / `composer.lock` are never silently excluded — if they
  changed, they're shown normally with a warning that the server may need
  `composer install` after the update.

## Requirements

- Windows (also runs on macOS/Linux for development/testing)
- Python 3.11+
- Git, available on your `PATH`

## Setup & Usage (Windows)

Just double-click **`run.bat`**. On first run it creates a local `.venv`
folder and installs dependencies automatically; on later runs it starts
straight away. No need to open a terminal.

## Setup & Usage (manual / macOS / Linux)

```bash
pip install -r requirements.txt
python main.py
```

1. **Browse...** and select your Laravel project's root folder, then
   **Open Project**.
2. Review the **detected current version**. If it's wrong or missing, type
   the correct one into **Override Detected Version**.
3. In **Git Changes**, review the detected files. Everything is selected by
   default except files matched by the exclusion rules. Untick anything you
   don't want in this update, or use **Select All** / **Unselect All**.
   Use **Manage Exclusions...** to edit the excluded directories/patterns or
   to (not recommended) allow sensitive files through.
4. Enter the **New Version** (must differ from the current version).
5. Click **Build Update ZIP**. Confirm the pre-build summary. If a package
   for that version already exists, you'll be asked whether to replace it.
6. The **Output** section shows the resulting ZIP name, size, and file
   count. Click **Open Output Folder** to find it, then upload the ZIP to
   the StreamForge admin panel.

## Project layout

```
streamforge-update-builder/
    main.py                  Entry point
    run.bat                  Windows launcher (sets up venv, installs deps, runs)
    requirements.txt
    README.md

    app/
        __init__.py
        gui.py                PySide6 UI (dark theme)
        git_manager.py        Read-only Git integration + safety allow-list
        version_manager.py    composer.json version detection
        update_builder.py     Exclusion rules, path safety, ZIP building
        manifest.py           update-manifest.json construction + SHA-256
        config.py             Constants: exclusions, sensitive patterns,
                               allowed/disallowed Git subcommands
```
