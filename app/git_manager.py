"""
git_manager.py

Read-only Git integration.

This module NEVER mutates the repository. Every function that shells out to
Git is routed through run_git(), which hard-refuses any subcommand that is
not explicitly on the read-only allow list (see config.py). This is
defense-in-depth on top of the fact that only read-only commands are ever
called from this file in the first place.

Detected changes are normalized into a list of Change objects:
    status:    'M' (modified) | 'A' (added) | 'D' (deleted)
             | 'R' (renamed)  | '?' (untracked)
    path:      current project-relative path (forward slashes)
    old_path:  previous path, only set for renames
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import config


class GitNotInstalledError(Exception):
    pass


class GitCommandError(Exception):
    def __init__(self, message: str, stderr: str = "", returncode: Optional[int] = None):
        super().__init__(message)
        self.stderr = stderr
        self.returncode = returncode


class NotAGitRepositoryError(Exception):
    pass


class DisallowedGitCommandError(Exception):
    """Raised if something attempts to run a non-read-only git subcommand."""


@dataclass
class Change:
    status: str  # M, A, D, R, ?
    path: str  # project-relative, forward slashes
    old_path: Optional[str] = None  # only for renames

    @property
    def status_label(self) -> str:
        return {
            "M": "Modified",
            "A": "Added",
            "D": "Deleted",
            "R": "Renamed",
            "?": "Untracked",
        }.get(self.status, self.status)


def is_git_installed() -> bool:
    return shutil.which("git") is not None


def _normalize_path(raw: str) -> str:
    """Strip optional surrounding quotes Git adds for paths with special
    characters, and normalize to forward slashes."""
    raw = raw.strip()
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
        # Git C-style-escapes quoted paths; undo the common escapes.
        raw = (
            raw.replace('\\"', '"')
            .replace("\\\\", "\\")
        )
    return raw.replace("\\", "/")


def run_git(args: List[str], cwd: Path, timeout: int = 30) -> str:
    """
    Run a read-only git command and return stdout as text.

    Raises:
        DisallowedGitCommandError: if args[0] is not an explicitly
            allowed read-only subcommand.
        GitNotInstalledError: if the git executable cannot be found.
        GitCommandError: if git exits non-zero or the process fails.
    """
    if not args:
        raise DisallowedGitCommandError("No git subcommand specified.")

    subcommand = args[0]
    if subcommand in config.DISALLOWED_GIT_SUBCOMMANDS:
        raise DisallowedGitCommandError(
            f"Refusing to run disallowed git subcommand: '{subcommand}'"
        )
    if subcommand not in config.ALLOWED_GIT_SUBCOMMANDS:
        raise DisallowedGitCommandError(
            f"Refusing to run git subcommand not on the read-only allow list: '{subcommand}'"
        )

    if not is_git_installed():
        raise GitNotInstalledError(
            "Git executable was not found in PATH. Please install Git and ensure "
            "it is available from the command line."
        )

    full_cmd = ["git"] + args
    try:
        result = subprocess.run(
            full_cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise GitNotInstalledError(f"Could not execute git: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitCommandError(f"Git command timed out: {' '.join(full_cmd)}") from exc

    if result.returncode != 0:
        raise GitCommandError(
            f"Git command failed: {' '.join(full_cmd)}",
            stderr=result.stderr.strip(),
            returncode=result.returncode,
        )

    return result.stdout


def verify_is_work_tree(project_root: Path) -> bool:
    """
    Runs `git rev-parse --is-inside-work-tree`. Returns True/False.
    Raises GitNotInstalledError if git itself is missing.
    """
    if not is_git_installed():
        raise GitNotInstalledError(
            "Git executable was not found in PATH. Please install Git and ensure "
            "it is available from the command line."
        )
    try:
        output = run_git(["rev-parse", "--is-inside-work-tree"], cwd=project_root)
    except GitCommandError:
        return False
    return output.strip() == "true"


def get_repo_root(project_root: Path) -> Path:
    """Return the actual top-level directory of the git work tree."""
    output = run_git(["rev-parse", "--show-toplevel"], cwd=project_root)
    return Path(output.strip())


def _parse_porcelain_line(line: str) -> Optional[Change]:
    if not line:
        return None
    if len(line) < 4:
        return None

    code = line[0:2]
    rest = line[3:]

    x, y = code[0], code[1]

    # Untracked files
    if code == "??":
        return Change(status="?", path=_normalize_path(rest))

    # Renamed / copied: "R  old -> new" or "R100 old -> new"
    if x == "R" or y == "R" or x == "C" or y == "C":
        if " -> " in rest:
            old_path, new_path = rest.split(" -> ", 1)
            return Change(
                status="R",
                path=_normalize_path(new_path),
                old_path=_normalize_path(old_path),
            )
        return Change(status="R", path=_normalize_path(rest))

    # Deleted (either staged or in working tree)
    if x == "D" or y == "D":
        return Change(status="D", path=_normalize_path(rest))

    # Added (staged, new file)
    if x == "A":
        return Change(status="A", path=_normalize_path(rest))

    # Everything else (M, MM, AM, etc. and unmerged states) -> Modified
    return Change(status="M", path=_normalize_path(rest))


def get_working_tree_changes(project_root: Path) -> List[Change]:
    """
    Returns the full set of changes in the working tree + index, combining:
      - git status --porcelain=v1 --untracked-files=all  (primary source)
      - git ls-files --others --exclude-standard          (safety net for
        untracked files, merged in / de-duplicated with the above)

    De-duplicates by path, preferring the richer entry from porcelain status
    (which carries rename info) when both sources report the same path.
    """
    porcelain_output = run_git(
        ["status", "--porcelain=v1", "--untracked-files=all"],
        cwd=project_root,
    )

    changes: List[Change] = []
    seen_paths = set()
    for line in porcelain_output.splitlines():
        change = _parse_porcelain_line(line)
        if change is None:
            continue
        changes.append(change)
        seen_paths.add(change.path)

    # Safety net: explicitly ask for untracked files too, in case porcelain
    # parsing missed anything (e.g. unusual git versions/output quirks).
    try:
        untracked_output = run_git(
            ["ls-files", "--others", "--exclude-standard"],
            cwd=project_root,
        )
        for line in untracked_output.splitlines():
            path = _normalize_path(line)
            if path and path not in seen_paths:
                changes.append(Change(status="?", path=path))
                seen_paths.add(path)
    except GitCommandError:
        # Non-fatal -- porcelain output already covers the common case.
        pass

    return changes