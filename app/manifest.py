"""
manifest.py

Builds the manifest.json structure embedded in every generated
delta ZIP. Designed so a future StreamForge/Laravel updater can consume it
directly:

{
    "product": "StreamForge",
    "type": "delta",
    "from_version": "2.4.1",
    "to_version": "2.4.2",
    "generated_at": "2026-08-20T12:34:56+00:00",
    "generated_by": "StreamForge Update Builder",
    "file_count": 12,
    "total_uncompressed_size": 123456,
    "files": [
        {"path": "routes/web.php", "sha256": "..."}
    ],
    "deleted_files": ["app/Old/Example.php"],
    "renamed_files": [
        {"old_path": "app/Foo.php", "new_path": "app/Bar.php", "sha256": "..."}
    ]
}
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from . import config


def sha256_of_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def build_manifest(
    from_version: Optional[str],
    to_version: str,
    included_files: List[dict],
    deleted_files: List[str],
    renamed_files: List[dict],
    total_uncompressed_size: int,
) -> dict:
    """
    included_files: list of {"path": str, "sha256": str, "size": int}
    renamed_files:  list of {"old_path": str, "new_path": str, "sha256": str}
    """
    manifest = {
        "product": config.PRODUCT_NAME,
        "type": "delta",
        "from_version": from_version,
        "to_version": to_version,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generated_by": config.APP_NAME,
        "file_count": len(included_files),
        "total_uncompressed_size": total_uncompressed_size,
        "files": included_files,
        "deleted_files": deleted_files,
        "renamed_files": renamed_files,
    }
    return manifest


def write_manifest_file(manifest: dict, destination: Path) -> None:
    destination.write_text(
        json.dumps(manifest, indent=4, ensure_ascii=False),
        encoding="utf-8",
    )


def manifest_to_json_bytes(manifest: dict) -> bytes:
    return json.dumps(manifest, indent=4, ensure_ascii=False).encode("utf-8")