"""
StreamForge Update Builder
--------------------------
Entry point. Launches the PySide6 desktop GUI.

This tool is READ-ONLY with respect to Git and the Laravel project:
it detects working-tree changes and packages them into a delta update
ZIP. It never commits, pushes, pulls, resets, checks out, stashes, or
otherwise mutates the project or its Git history.

Run with:
    python main.py
"""

from __future__ import annotations

import sys


def _check_dependencies() -> None:
    """Fail fast with a readable message if PySide6 isn't installed,
    instead of letting the user hit a raw ImportError traceback."""
    try:
        import PySide6  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "PySide6 is not installed.\n\n"
            "Install dependencies first:\n"
            "    pip install -r requirements.txt\n"
        )
        sys.exit(1)


def main() -> None:
    _check_dependencies()
    from app.gui import main as run_gui

    run_gui()


if __name__ == "__main__":
    main()
