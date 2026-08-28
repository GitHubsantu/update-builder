"""
update_builder.py

Turns a set of detected Git changes into a delta update ZIP:
    - Applies exclusion rules (default + user-managed) and sensitive-file
      protection.
    - Validates every path stays inside the project root (no traversal,
      no unsafe symlinks escaping the root).
    - Computes SHA-256 hashes.
    - Writes manifest.json + changed files into the ZIP, preserving
      the project-relative directory structure.

This module never modifies the source project. It only reads files from it
and writes a new ZIP into the chosen output directory.
"""

from __future__ import annotations

import fnmatch
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import config, git_manager, manifest as manifest_mod
from .git_manager import Change


class UnsafePathError(Exception):
    """Raised when a path would escape the project root or is an unsafe symlink."""


class FileVanishedError(Exception):
    """Raised when a file disappears between detection and packaging."""


def _sha256_at_baseline(project_root: Path, baseline_ref: str, rel_path: str) -> str:
    """Hash the file bytes recorded at the selected old Git release."""
    try:
        contents = git_manager.get_file_contents_at_ref(project_root, baseline_ref, rel_path)
    except git_manager.GitCommandError as exc:
        raise git_manager.GitCommandError(
            f"Could not read '{rel_path}' from Git baseline '{baseline_ref}'. "
            "Choose the release/commit that contains the old version.",
            stderr=exc.stderr,
            returncode=exc.returncode,
        ) from exc
    import hashlib

    return hashlib.sha256(contents).hexdigest()


@dataclass
class ExclusionRules:
    excluded_dirs: List[str] = field(default_factory=lambda: list(config.DEFAULT_EXCLUDED_DIRS))
    excluded_files: List[str] = field(default_factory=lambda: list(config.DEFAULT_EXCLUDED_FILES))
    excluded_patterns: List[str] = field(default_factory=lambda: list(config.DEFAULT_EXCLUDED_PATTERNS))
    allow_sensitive_override: bool = False


@dataclass
class ClassifiedFile:
    change: Change
    excluded: bool
    excluded_reason: Optional[str] = None
    is_sensitive: bool = False
    is_dependency_file: bool = False


def _path_is_under_dir(rel_path: str, dir_prefix: str) -> bool:
    dir_prefix = dir_prefix.strip("/")
    return rel_path == dir_prefix or rel_path.startswith(dir_prefix + "/")


def is_sensitive(rel_path: str) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    for pattern in config.SENSITIVE_PATTERNS:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_path, pattern):
            return True
    return False


def is_always_excluded_sensitive(rel_path: str) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    return any(
        fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_path, pattern)
        for pattern in config.ALWAYS_EXCLUDED_SENSITIVE_PATTERNS
    )


def is_dependency_file(rel_path: str) -> bool:
    return rel_path in config.NEVER_AUTO_EXCLUDE


def is_release_path(rel_path: str) -> bool:
    """Whether a path belongs to the configured deployable application tree."""
    return any(rel_path == allowed or rel_path.startswith(allowed.rstrip("/") + "/") for allowed in config.DEFAULT_RELEASE_PATHS)


def is_release_path(rel_path: str) -> bool:
    """Whether a path belongs to the configured deployable application tree."""
    return any(
        rel_path == allowed or rel_path.startswith(allowed.rstrip("/") + "/")
        for allowed in config.DEFAULT_RELEASE_PATHS
    )


def classify_change(change: Change, rules: ExclusionRules) -> ClassifiedFile:
    """
    Decide whether a detected change should be excluded by default, and why.
    Never auto-excludes composer.json / composer.lock.
    """
    rel_path = change.path
    name = rel_path.rsplit("/", 1)[-1]

    dependency_file = is_dependency_file(rel_path)
    sensitive = is_sensitive(rel_path)

    if is_always_excluded_sensitive(rel_path):
        return ClassifiedFile(
            change=change,
            excluded=True,
            excluded_reason="Environment file (.env) -- never included in update packages.",
            is_sensitive=True,
            is_dependency_file=dependency_file,
        )

    if sensitive and not rules.allow_sensitive_override:
        return ClassifiedFile(
            change=change,
            excluded=True,
            excluded_reason="Sensitive file (secrets/keys) -- excluded by default.",
            is_sensitive=True,
            is_dependency_file=dependency_file,
        )

    if dependency_file:
        # Always shown, never auto-excluded, regardless of dir/pattern rules.
        return ClassifiedFile(
            change=change,
            excluded=False,
            is_sensitive=sensitive,
            is_dependency_file=True,
        )

    for dir_prefix in rules.excluded_dirs:
        if _path_is_under_dir(rel_path, dir_prefix):
            return ClassifiedFile(
                change=change,
                excluded=True,
                excluded_reason=f"Inside excluded directory '{dir_prefix}/'",
                is_sensitive=sensitive,
            )

    for excluded_name in rules.excluded_files:
        if name == excluded_name or rel_path == excluded_name:
            return ClassifiedFile(
                change=change,
                excluded=True,
                excluded_reason=f"Matches excluded file '{excluded_name}'",
                is_sensitive=sensitive,
            )

    for pattern in rules.excluded_patterns:
        if fnmatch.fnmatch(name, pattern):
            return ClassifiedFile(
                change=change,
                excluded=True,
                excluded_reason=f"Matches excluded pattern '{pattern}'",
                is_sensitive=sensitive,
            )

    return ClassifiedFile(change=change, excluded=False, is_sensitive=sensitive)


def validate_safe_path(project_root: Path, rel_path: str) -> Path:
    """
    Resolve rel_path against project_root and ensure the result is actually
    inside project_root -- guards against path traversal (e.g. "../../etc")
    and symlinks that point outside the project root.

    Returns the resolved absolute Path if safe.
    Raises UnsafePathError otherwise.
    """
    project_root_resolved = Path(project_root).resolve()

    # Normalize Windows-style separators to forward slashes first, so
    # traversal can't hide behind backslashes regardless of the host OS
    # (on POSIX, "..\\.." is just a literal filename unless normalized here).
    normalized = rel_path.replace("\\", "/")

    if normalized.startswith("/"):
        raise UnsafePathError(f"Absolute path not allowed: {rel_path}")

    if any(part == ".." for part in normalized.split("/")):
        raise UnsafePathError(f"Path traversal ('..') not allowed: {rel_path}")

    candidate = (project_root_resolved / normalized)

    # Resolve symlinks / ".." components.
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise UnsafePathError(f"Could not resolve path '{rel_path}': {exc}") from exc

    try:
        resolved.relative_to(project_root_resolved)
    except ValueError:
        raise UnsafePathError(
            f"Path escapes project root and was blocked: {rel_path}"
        )

    # If any path component up to (not including) the final file is a
    # symlink pointing outside the root, relative_to() above will already
    # have caught it since resolve() follows symlinks fully. This extra
    # check catches a symlink *at* the leaf that points outside the root
    # even when the leaf itself doesn't exist yet (rare, but be strict).
    if candidate.is_symlink():
        link_target = candidate.resolve()
        try:
            link_target.relative_to(project_root_resolved)
        except ValueError:
            raise UnsafePathError(
                f"Symlink points outside the project root and was blocked: {rel_path}"
            )

    return resolved


@dataclass
class BuildPlan:
    from_version: Optional[str]
    to_version: str
    included: List[ClassifiedFile]
    deleted: List[ClassifiedFile]
    renamed: List[ClassifiedFile]
    output_zip_path: Path
    baseline_ref: str = "HEAD"
    package_type: str = "delta"  # delta | full
    rules: Optional[ExclusionRules] = None


@dataclass
class BuildResult:
    manifest: dict
    zip_path: Path
    file_count: int
    total_uncompressed_size: int
    zip_size: int


def build_update_zip(
    project_root: Path,
    plan: BuildPlan,
    log: Optional[Callable[[str], None]] = None,
) -> BuildResult:
    """
    Creates the delta update ZIP described by `plan`.

    - `plan.included`  : ClassifiedFile entries with status in {M, A, ?} (or R
                          treated as an addition of the new path) to embed.
    - `plan.deleted`    : ClassifiedFile entries with status D.
    - `plan.renamed`    : ClassifiedFile entries with status R (old_path set).

    Raises UnsafePathError / FileVanishedError / OSError on failure. Callers
    (GUI layer) are expected to catch and present these as friendly errors.
    """

    def _log(msg: str) -> None:
        if log:
            log(msg)

    if plan.package_type not in {"delta", "full"}:
        raise ValueError("package_type must be either 'delta' or 'full'.")

    project_root = Path(project_root).resolve()
    output_zip_path = Path(plan.output_zip_path)
    output_zip_path.parent.mkdir(parents=True, exist_ok=True)

    total_uncompressed_size = 0
    entries: Dict[str, dict] = {}

    _log(f"Building update package: {output_zip_path.name}")

    tmp_zip_path = output_zip_path.with_suffix(output_zip_path.suffix + ".tmp")

    if plan.package_type == "full":
        try:
            with zipfile.ZipFile(tmp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                manifest_dict, file_count, total_uncompressed_size = _write_full_package(project_root, plan, zf, _log)
            if output_zip_path.exists():
                output_zip_path.unlink()
            tmp_zip_path.rename(output_zip_path)
        except Exception:
            if tmp_zip_path.exists():
                tmp_zip_path.unlink()
            raise
        zip_size = output_zip_path.stat().st_size
        _log(f"[SUCCESS] {output_zip_path.name} created ({zip_size:,} bytes)")
        return BuildResult(manifest_dict, output_zip_path, file_count, total_uncompressed_size, zip_size)

    try:
        with zipfile.ZipFile(tmp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Renames are represented as an add at the new path plus a delete
            # at the old path, which is the safe sfdelta-v1 equivalent.
            payload_changes = {cf.change.path: cf for cf in plan.included}
            for cf in plan.renamed:
                payload_changes.setdefault(cf.change.path, cf)

            for rel_path, cf in payload_changes.items():
                try:
                    safe_path = validate_safe_path(project_root, rel_path)
                except UnsafePathError:
                    _log(f"[SKIP] Unsafe path blocked: {rel_path}")
                    raise

                if not safe_path.is_file():
                    raise FileVanishedError(
                        f"File disappeared before packaging: {rel_path}"
                    )

                size = safe_path.stat().st_size
                file_hash = manifest_mod.sha256_of_file(safe_path)
                total_uncompressed_size += size

                zf.write(safe_path, arcname=f"files/{rel_path}")
                if cf.change.status in {"A", "?", "R"}:
                    entries[rel_path] = {"action": "add", "after_sha256": file_hash}
                else:
                    before_hash = _sha256_at_baseline(project_root, plan.baseline_ref, rel_path)
                    entries[rel_path] = {
                        "action": "modify",
                        "before_sha256": before_hash,
                        "after_sha256": file_hash,
                    }
                _log(f"[ADD] {rel_path}")

            deleted_changes = {cf.change.path: cf for cf in plan.deleted}
            for cf in plan.renamed:
                if cf.change.old_path:
                    deleted_changes.setdefault(cf.change.old_path, cf)
            for rel_path in deleted_changes:
                try:
                    validate_safe_path(project_root, rel_path)
                except UnsafePathError:
                    _log(f"[SKIP] Unsafe deleted path blocked: {rel_path}")
                    raise
                entries[rel_path] = {
                    "action": "delete",
                    "before_sha256": _sha256_at_baseline(project_root, plan.baseline_ref, rel_path),
                }
                _log(f"[DELETE] {rel_path}")

            manifest_dict = manifest_mod.build_manifest(
                from_version=plan.from_version,
                to_version=plan.to_version,
                entries=entries,
            )

            zf.writestr(config.MANIFEST_FILENAME, manifest_mod.manifest_to_json_bytes(manifest_dict))
            _log(f"[INFO] Manifest written: {config.MANIFEST_FILENAME}")

        # Atomic-ish replace: only overwrite the real target after the zip
        # was fully written without error.
        if output_zip_path.exists():
            output_zip_path.unlink()
        tmp_zip_path.rename(output_zip_path)

    except Exception:
        if tmp_zip_path.exists():
            try:
                tmp_zip_path.unlink()
            except OSError:
                pass
        raise

    zip_size = output_zip_path.stat().st_size
    _log(f"[SUCCESS] {output_zip_path.name} created ({zip_size:,} bytes)")

    return BuildResult(
        manifest=manifest_dict,
        zip_path=output_zip_path,
        file_count=len(payload_changes),
        total_uncompressed_size=total_uncompressed_size,
        zip_size=zip_size,
    )


def _write_full_package(
    project_root: Path, plan: BuildPlan, zf: zipfile.ZipFile, log: Callable[[str], None]
) -> tuple[dict, int, int]:
    """Write a complete, self-describing release without trusting Git state."""
    rules = plan.rules or ExclusionRules()
    entries: Dict[str, dict] = {}
    total_size = 0

    for path in sorted(project_root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel_path = path.relative_to(project_root).as_posix()
        if not is_release_path(rel_path):
            continue
        classified = classify_change(Change(status="A", path=rel_path), rules)
        if classified.excluded:
            continue
        safe_path = validate_safe_path(project_root, rel_path)
        file_hash = manifest_mod.sha256_of_file(safe_path)
        total_size += safe_path.stat().st_size
        zf.write(safe_path, arcname=f"files/{rel_path}")
        entries[rel_path] = {"after_sha256": file_hash}
        log(f"[ADD] {rel_path}")

    if not entries:
        raise ValueError("The full package contains no eligible files.")

    missing_boot_files = sorted(set(config.REQUIRED_FULL_PACKAGE_FILES) - set(entries))
    if missing_boot_files:
        raise ValueError(
            "Cannot build a full release: required boot files are missing: "
            + ", ".join(missing_boot_files)
        )

    manifest_dict = manifest_mod.build_full_manifest(plan.to_version, entries)
    zf.writestr(config.MANIFEST_FILENAME, manifest_mod.manifest_to_json_bytes(manifest_dict))
    log(f"[INFO] Full-release manifest written: {config.MANIFEST_FILENAME}")

    return manifest_dict, len(entries), total_size
