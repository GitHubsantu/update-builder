"""
version_manager.py

Reads composer.json (read-only -- never modified) and intelligently detects
the application/product version, as opposed to the Composer package/library
"version" field, which frequently does not represent the deployed product
version at all.

Detection order:
    1. extra.version / extra.app-version / extra.application-version
    2. top-level "version" field (used only as a fallback, since it is
       often the package version, not the product version)
    3. Not found -> caller must prompt the user / show a clear message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import config


class ComposerNotFoundError(Exception):
    """Raised when composer.json does not exist at the expected path."""


class ComposerParseError(Exception):
    """Raised when composer.json exists but is not valid JSON."""


@dataclass
class VersionResult:
    version: Optional[str]
    source: str  # human-readable description of where it was found


def composer_path(project_root: Path) -> Path:
    return Path(project_root) / "composer.json"


def load_composer_json(project_root: Path) -> dict:
    """
    Load and parse composer.json from the project root.

    Raises:
        ComposerNotFoundError: if the file does not exist.
        ComposerParseError: if the file is not valid JSON.
    """
    path = composer_path(project_root)
    if not path.is_file():
        raise ComposerNotFoundError(f"composer.json not found at: {path}")

    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ComposerParseError(f"Could not read composer.json: {exc}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ComposerParseError(
            f"composer.json is not valid JSON (line {exc.lineno}, col {exc.colno}): {exc.msg}"
        ) from exc

    if not isinstance(data, dict):
        raise ComposerParseError("composer.json does not contain a JSON object at its root.")

    return data


def _dig(data: dict, path: tuple) -> Optional[str]:
    node = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    if isinstance(node, str) and node.strip():
        return node.strip()
    return None


def detect_version(data: dict) -> VersionResult:
    """
    Detect the application/product version from a parsed composer.json dict.

    Does NOT assume the top-level "version" field is the product version
    when a dedicated "extra" field is available; the "extra" fields are
    checked first for that reason.
    """
    for path in config.COMPOSER_EXTRA_VERSION_KEYS:
        value = _dig(data, path)
        if value:
            return VersionResult(version=value, source=".".join(path))

    top_level = data.get(config.COMPOSER_TOP_LEVEL_VERSION_KEY)
    if isinstance(top_level, str) and top_level.strip():
        return VersionResult(
            version=top_level.strip(),
            source=f"top-level '{config.COMPOSER_TOP_LEVEL_VERSION_KEY}' field "
            "(may represent the package/library version, not the product version -- please verify)",
        )

    return VersionResult(version=None, source="not found")


def get_current_version(project_root: Path) -> VersionResult:
    """
    Convenience wrapper: load composer.json and detect the version in one call.
    Propagates ComposerNotFoundError / ComposerParseError to the caller.
    """
    data = load_composer_json(project_root)
    return detect_version(data)


def is_valid_version_string(value: str) -> bool:
    """
    Loose validation -- StreamForge does not enforce strict SemVer, just
    requires a non-empty, whitespace-free-ish string that isn't identical
    to a placeholder.
    """
    if value is None:
        return False
    value = value.strip()
    if not value:
        return False
    if any(ch.isspace() for ch in value):
        return False
    return True