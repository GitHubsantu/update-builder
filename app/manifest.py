"""
manifest.py

Builds the ``sfdelta-v1`` manifest.json embedded in every generated delta
ZIP.  This is the exact contract consumed by the StreamForge Pro updater.

{
    "format": "sfdelta-v1",
    "from_version": "2.4.1",
    "to_version": "2.4.2",
    "generated_at": "2026-08-20T12:34:56+00:00",
    "entries": {
        "routes/web.php": {"action": "modify", "before_sha256": "...", "after_sha256": "..."}
    }
}
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional


def sha256_of_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def build_manifest(
    from_version: Optional[str],
    to_version: str,
    entries: Mapping[str, dict],
) -> dict:
    """Build the updater's intentionally small, versioned manifest."""
    return {
        "format": "sfdelta-v1",
        "package_type": "delta",
        "from_version": from_version,
        "to_version": to_version,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entries": dict(entries),
    }


def build_full_manifest(to_version: str, entries: Mapping[str, dict]) -> dict:
    """Build the self-describing full-release package contract.

    Full packages deliberately use the same ``files/`` payload layout as a
    delta.  That makes the artifact unambiguous at upload time and lets an
    installer copy only files explicitly listed in the manifest.
    """
    return {
        "format": "sfpackage-v1",
        "package_type": "full",
        "to_version": to_version,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entries": dict(entries),
    }


def write_manifest_file(manifest: dict, destination: Path) -> None:
    destination.write_text(
        json.dumps(manifest, indent=4, ensure_ascii=False),
        encoding="utf-8",
    )


def manifest_to_json_bytes(manifest: dict) -> bytes:
    return json.dumps(manifest, indent=4, ensure_ascii=False).encode("utf-8")
