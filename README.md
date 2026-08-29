# StreamForge Update Builder

A standalone Windows desktop tool that creates verified full-release ZIPs and delta patches for a Laravel project.

It only reads the project and Git history; it never modifies files, commits, or Git history.

## StreamForge Pro package format

Delta packages conform to `sfdelta-v1` and contain a manifest plus payloads
below `files/<project-relative-path>`. Full releases are ordinary, ready-to-
extract installation ZIPs: files are at the ZIP root, there is no manifest,
and a fresh empty Laravel `storage/` directory tree is included. The builder
sets the ZIP's `composer.json` version to the release version without changing
the source project's composer.json.

- Delta `manifest.json` contains `format`, `from_version`, `to_version`, an ISO-8601 `generated_at`, and an `entries` map.
- Delta payload files are stored as `files/<project-relative-path>`.
- Each entry is `add`, `modify`, or `delete` and carries the required SHA-256 values.
- A rename is emitted safely as a delete of its old path plus an add of its new path.

For modified and deleted entries, `before_sha256` is read from the selected old-release Git baseline. For added and modified entries, `after_sha256` is calculated from the current working tree.

## Safety

- Only an allow-list of read-only Git commands can run (`status`, `diff`, `ls-files`, `rev-parse`, `cat-file`, `rev-list`, and read-only `config`).
- All package paths are validated to prevent traversal and symlinks escaping the project root.
- `.env`, private keys, and credential-looking files are excluded by default unless explicitly overridden.
- Customer/runtime data is excluded by default, including `storage`, `vendor`, `node_modules`, and `public/uploads`.
- `composer.json` and `composer.lock` are never silently hidden.

## Usage

On Windows, double-click `run.bat`. It creates the local virtual environment and installs dependencies when needed.

For manual use:

```bash
pip install -r requirements.txt
python main.py
```

1. Open the Laravel project root.
2. Review the detected current version and select the changes to ship.
3. Enter the new version.
4. Choose **Delta patch** for selected Git changes, or **Full release** to build the complete safe deployable tree. Use a full release for every version; a delta is optional and is only valid from its exact base version.
5. For a delta, enter **Old Git Baseline**: `HEAD`, an old-release tag such as `v2.4.1`, or a commit SHA that contains the old release. The builder uses it only to calculate `before_sha256`.
6. Upload the `-full.zip` file as **Release ZIP** and the optional `-delta.zip` file as **Delta Patch File**. The target/base versions must match the form exactly.

## Project layout

```text
main.py
app/
    gui.py                PySide6 UI
    git_manager.py        Read-only Git integration
    version_manager.py    Composer version detection
    update_builder.py     Exclusions, path safety, ZIP construction
    manifest.py           sfdelta-v1 manifest and SHA-256 helpers
    config.py             Application constants and exclusion rules
```
