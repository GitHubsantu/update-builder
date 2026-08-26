"""
config.py

Central configuration for StreamForge Update Builder:
- App/product identity
- Default exclusion rules (directories, files, glob patterns)
- Sensitive-file protection patterns
- Git safety allow/deny lists

Nothing in this module touches disk or Git. It only defines constants and
small pure helper functions so the rest of the app has a single source of
truth for "what gets excluded and why".
"""

from __future__ import annotations

APP_NAME = "StreamForge Update Builder"
APP_VERSION = "1.0.0"
PRODUCT_NAME = "StreamForge"

# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------
# Directories excluded by default (matched as path prefixes, using
# forward-slash-normalized, project-relative paths).
DEFAULT_EXCLUDED_DIRS = [
    ".git",
    "vendor",
    "node_modules",
    "storage/logs",
    "storage/framework/cache",
    "storage/framework/sessions",
    "storage/framework/views",
    "bootstrap/cache",
    "public/storage",
]

# Exact file names excluded by default (matched by file name, not full path,
# unless the pattern contains a "/").
DEFAULT_EXCLUDED_FILES = [
    ".gitignore",
]

# Glob-style patterns (fnmatch) checked against the file name.
DEFAULT_EXCLUDED_PATTERNS = [
    "*.log",
    "*.tmp",
    ".DS_Store",
    "Thumbs.db",
]

# ---------------------------------------------------------------------------
# Sensitive files - excluded even more aggressively. These are never
# included unless the user explicitly overrides them in the GUI.
# ---------------------------------------------------------------------------
SENSITIVE_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*id_rsa*",
    "*id_dsa*",
    "*id_ecdsa*",
    "*id_ed25519*",
    "*.ppk",
    "*credentials*",
    "*secret*",
]

# Files that must NEVER be silently excluded just because they look like
# config -- dependency manifests may legitimately change and must be shown
# (with a warning), never hidden.
NEVER_AUTO_EXCLUDE = {
    "composer.json",
    "composer.lock",
}

# ---------------------------------------------------------------------------
# Git safety
# ---------------------------------------------------------------------------
# Only these read-only subcommands may ever be executed by the app.
ALLOWED_GIT_SUBCOMMANDS = {
    "rev-parse",
    "status",
    "diff",
    "ls-files",
    "cat-file",
    "config",  # used read-only, e.g. `git config --get ...`
    "rev-list",
}

# Explicit deny list -- defense in depth. Even if a caller made a mistake,
# these subcommands are refused outright by git_manager.run_git().
DISALLOWED_GIT_SUBCOMMANDS = {
    "commit",
    "push",
    "pull",
    "reset",
    "checkout",
    "clean",
    "stash",
    "merge",
    "rebase",
    "branch",
    "tag",
    "remote",
    "fetch",
    "clone",
    "init",
    "rm",
    "mv",
    "apply",
    "cherry-pick",
    "revert",
    "gc",
    "filter-branch",
    "worktree",
    "am",
    "submodule",
    "restore",
    "switch",
    "reflog",
    "update-ref",
    "symbolic-ref",
}

# Composer keys checked (in order) to find the application/product version.
# Deliberately does NOT include the top-level "version" field first, since
# that field commonly represents the *package* version for a library, not
# the deployed product version.
COMPOSER_EXTRA_VERSION_KEYS = [
    ("extra", "version"),
    ("extra", "app-version"),
    ("extra", "application-version"),
]
COMPOSER_TOP_LEVEL_VERSION_KEY = "version"

OUTPUT_DIR_NAME = "updates"
MANIFEST_FILENAME = "manifest.json"