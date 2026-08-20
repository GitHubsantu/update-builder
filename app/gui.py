"""
gui.py

PySide6 desktop GUI for StreamForge Update Builder.

Sections:
    1. Project      - path, browse, open
    2. Version      - detected version + new version input
    3. Git Changes  - table of detected changes with include checkboxes
    4. Build        - output folder + Build Update ZIP
    5. Output       - result of the last build
    Log panel       - running [INFO]/[SUCCESS]/[ERROR] log

All Git/file operations run on the UI thread except the ZIP build, which
runs on a background QThread so the window stays responsive.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import traceback
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QRectF, QThread, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import config, git_manager, update_builder, version_manager
from .git_manager import Change
from .update_builder import BuildPlan, ClassifiedFile, ExclusionRules


# ---------------------------------------------------------------------------
# Dark theme stylesheet
# ---------------------------------------------------------------------------
DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1e1f24;
    color: #e6e6e6;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #33343c;
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 10px;
    font-weight: 600;
    color: #b9bcc7;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}
QLineEdit, QPlainTextEdit, QListWidget {
    background-color: #26272e;
    border: 1px solid #3a3b44;
    border-radius: 4px;
    padding: 6px;
    color: #f0f0f0;
    selection-background-color: #4f7cff;
}
QLineEdit:read-only {
    color: #9a9ca6;
}
QPushButton {
    background-color: #33343e;
    border: 1px solid #45464f;
    border-radius: 4px;
    padding: 7px 14px;
    color: #f0f0f0;
}
QPushButton:hover {
    background-color: #3d3f4a;
    border: 1px solid #5a5cff;
}
QPushButton:pressed {
    background-color: #2a2b33;
}
QPushButton:disabled {
    color: #6b6c76;
    background-color: #26272e;
    border: 1px solid #33343c;
}
QPushButton#primary {
    background-color: #4f7cff;
    border: 1px solid #4f7cff;
    color: white;
    font-weight: 600;
}
QPushButton#primary:hover {
    background-color: #6690ff;
}
QPushButton#danger {
    background-color: #a73838;
    border: 1px solid #a73838;
    color: white;
}
QPushButton#danger:hover {
    background-color: #c04444;
}
QTableWidget {
    background-color: #212228;
    alternate-background-color: #26272e;
    gridline-color: #33343c;
    border: 1px solid #33343c;
    border-radius: 4px;
}
QHeaderView::section {
    background-color: #2b2c34;
    color: #c7c9d3;
    padding: 6px;
    border: none;
    border-bottom: 1px solid #3a3b44;
    font-weight: 600;
}
QPlainTextEdit {
    font-family: Consolas, 'Courier New', monospace;
    font-size: 12px;
    background-color: #17181c;
    color: #b6ffb0;
}
QLabel#heading {
    font-size: 18px;
    font-weight: 700;
    color: #ffffff;
}
QLabel#subheading {
    color: #9a9ca6;
}
QLabel#versionValue {
    font-size: 16px;
    font-weight: 700;
    color: #4f7cff;
}
QCheckBox {
    spacing: 6px;
}
"""


STATUS_COLORS = {
    "M": QColor("#e2b93b"),
    "A": QColor("#59c46a"),
    "D": QColor("#e05a5a"),
    "R": QColor("#4f9bff"),
    "?": QColor("#a389f4"),
}


# ---------------------------------------------------------------------------
# Self-painted "Include" checkbox
# ---------------------------------------------------------------------------
class TickCheckBox(QCheckBox):
    """
    A checkbox that paints its own box and tick instead of relying on the
    platform's native indicator (or QSS image: url(...), which doesn't
    render reliably across Qt styles/platforms). Guarantees a clearly
    visible green box + white tick when checked, and a clearly visible
    empty outlined box when unchecked.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.setText("")

    def paintEvent(self, event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(2, 2, self.width() - 4, self.height() - 4)

        if self.isChecked():
            painter.setBrush(QColor("#2fb84f"))
            painter.setPen(QPen(QColor("#2fb84f"), 1))
        else:
            painter.setBrush(QColor("#26272e"))
            painter.setPen(QPen(QColor("#7a7cff"), 1.5))

        painter.drawRoundedRect(rect, 4, 4)

        if self.isChecked():
            pen = QPen(QColor("white"))
            pen.setWidthF(2.4)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            path = QPainterPath()
            path.moveTo(rect.left() + rect.width() * 0.22, rect.top() + rect.height() * 0.53)
            path.lineTo(rect.left() + rect.width() * 0.42, rect.top() + rect.height() * 0.75)
            path.lineTo(rect.left() + rect.width() * 0.80, rect.top() + rect.height() * 0.26)
            painter.drawPath(path)

        painter.end()

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt override
        # QCheckBox normally toggles on release inside its native indicator
        # rect; since we fully custom-paint, just toggle on any release
        # inside the widget bounds.
        if self.rect().contains(event.position().toPoint()):
            self.toggle()
        event.accept()


# ---------------------------------------------------------------------------
# Background worker for building the ZIP (keeps UI responsive)
# ---------------------------------------------------------------------------
class BuildWorker(QThread):
    log_message = Signal(str)
    finished_ok = Signal(object)  # BuildResult
    finished_error = Signal(str, str)  # message, details

    def __init__(self, project_root: Path, plan: BuildPlan):
        super().__init__()
        self.project_root = project_root
        self.plan = plan

    def run(self):
        try:
            result = update_builder.build_update_zip(
                self.project_root,
                self.plan,
                log=lambda msg: self.log_message.emit(msg),
            )
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001 - surfaced to user via dialog
            details = traceback.format_exc()
            self.finished_error.emit(str(exc), details)


# ---------------------------------------------------------------------------
# Exclusion list editor dialog
# ---------------------------------------------------------------------------
class ExclusionEditorDialog(QDialog):
    def __init__(self, rules: ExclusionRules, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Exclusions")
        self.resize(480, 480)
        self.rules = rules

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Excluded directories (project-relative):"))
        self.dirs_list = QListWidget()
        self.dirs_list.addItems(rules.excluded_dirs)
        layout.addWidget(self.dirs_list)
        dir_row = QHBoxLayout()
        self.dir_input = QLineEdit()
        self.dir_input.setPlaceholderText("e.g. storage/app/private")
        add_dir_btn = QPushButton("Add")
        add_dir_btn.clicked.connect(self._add_dir)
        remove_dir_btn = QPushButton("Remove Selected")
        remove_dir_btn.clicked.connect(lambda: self._remove_selected(self.dirs_list))
        dir_row.addWidget(self.dir_input)
        dir_row.addWidget(add_dir_btn)
        dir_row.addWidget(remove_dir_btn)
        layout.addLayout(dir_row)

        layout.addWidget(QLabel("Excluded file name patterns (e.g. *.log, .DS_Store):"))
        self.patterns_list = QListWidget()
        self.patterns_list.addItems(rules.excluded_patterns)
        layout.addWidget(self.patterns_list)
        pattern_row = QHBoxLayout()
        self.pattern_input = QLineEdit()
        self.pattern_input.setPlaceholderText("e.g. *.bak")
        add_pattern_btn = QPushButton("Add")
        add_pattern_btn.clicked.connect(self._add_pattern)
        remove_pattern_btn = QPushButton("Remove Selected")
        remove_pattern_btn.clicked.connect(lambda: self._remove_selected(self.patterns_list))
        pattern_row.addWidget(self.pattern_input)
        pattern_row.addWidget(add_pattern_btn)
        pattern_row.addWidget(remove_pattern_btn)
        layout.addLayout(pattern_row)

        self.sensitive_override_checkbox = QCheckBox(
            "Allow including sensitive files (.env, keys, credentials) -- NOT recommended"
        )
        self.sensitive_override_checkbox.setChecked(rules.allow_sensitive_override)
        layout.addWidget(self.sensitive_override_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_dir(self):
        text = self.dir_input.text().strip().strip("/")
        if text:
            self.dirs_list.addItem(text)
            self.dir_input.clear()

    def _add_pattern(self):
        text = self.pattern_input.text().strip()
        if text:
            self.patterns_list.addItem(text)
            self.pattern_input.clear()

    @staticmethod
    def _remove_selected(list_widget: QListWidget):
        for item in list_widget.selectedItems():
            list_widget.takeItem(list_widget.row(item))

    def result_rules(self) -> ExclusionRules:
        dirs = [self.dirs_list.item(i).text() for i in range(self.dirs_list.count())]
        patterns = [self.patterns_list.item(i).text() for i in range(self.patterns_list.count())]
        return ExclusionRules(
            excluded_dirs=dirs,
            excluded_files=list(self.rules.excluded_files),
            excluded_patterns=patterns,
            allow_sensitive_override=self.sensitive_override_checkbox.isChecked(),
        )


# ---------------------------------------------------------------------------
# Technical error dialog with collapsible details
# ---------------------------------------------------------------------------
class ErrorDialog(QDialog):
    def __init__(self, message: str, details: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Error")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)

        icon_label = QLabel(message)
        icon_label.setWordWrap(True)
        layout.addWidget(icon_label)

        self.details_box = QPlainTextEdit()
        self.details_box.setPlainText(details or "No additional details.")
        self.details_box.setReadOnly(True)
        self.details_box.setVisible(False)
        self.details_box.setFixedHeight(180)
        layout.addWidget(self.details_box)

        button_row = QHBoxLayout()
        self.toggle_btn = QPushButton("Show Details")
        self.toggle_btn.clicked.connect(self._toggle_details)
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self.accept)
        button_row.addWidget(self.toggle_btn)
        button_row.addStretch()
        button_row.addWidget(ok_btn)
        layout.addLayout(button_row)

        if not details:
            self.toggle_btn.setVisible(False)

    def _toggle_details(self):
        visible = not self.details_box.isVisible()
        self.details_box.setVisible(visible)
        self.toggle_btn.setText("Hide Details" if visible else "Show Details")


def show_error(parent, message: str, details: str = ""):
    dlg = ErrorDialog(message, details, parent)
    dlg.exec()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(config.APP_NAME)
        self.resize(1080, 780)

        self.project_root: Optional[Path] = None
        self.detected_version: Optional[str] = None
        self.version_source: str = ""
        self.classified_files: List[ClassifiedFile] = []
        self.exclusion_rules = ExclusionRules()
        self.last_build_result = None
        self.build_worker: Optional[BuildWorker] = None

        self._build_ui()
        self._update_enabled_states()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        # Wrap everything in a scroll area. On a short/small screen, the
        # fixed-height sections (Project, Version, Build, Output, Log) can
        # otherwise squeeze the Git Changes table down until only its header
        # row is visible even though rows exist -- scrolling instead of
        # clipping keeps every row reachable.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.setCentralWidget(scroll)

        central = QWidget()
        scroll.setWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        heading = QLabel(config.APP_NAME)
        heading.setObjectName("heading")
        subheading = QLabel(
            "Create delta update ZIP packages for your Laravel project using Git-detected changes."
        )
        subheading.setObjectName("subheading")
        root_layout.addWidget(heading)
        root_layout.addWidget(subheading)

        root_layout.addWidget(self._build_project_group())
        root_layout.addWidget(self._build_version_group())
        root_layout.addWidget(self._build_changes_group(), stretch=1)
        root_layout.addWidget(self._build_build_group())
        root_layout.addWidget(self._build_output_group())
        root_layout.addWidget(self._build_log_group())

    def _build_project_group(self) -> QGroupBox:
        group = QGroupBox("1. Project")
        layout = QHBoxLayout(group)

        self.project_path_input = QLineEdit()
        self.project_path_input.setReadOnly(True)
        self.project_path_input.setPlaceholderText("No project selected...")

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._on_browse_project)

        self.open_project_btn = QPushButton("Open Project")
        self.open_project_btn.setObjectName("primary")
        self.open_project_btn.clicked.connect(self._on_open_project)
        self.open_project_btn.setEnabled(False)

        layout.addWidget(self.project_path_input, stretch=1)
        layout.addWidget(browse_btn)
        layout.addWidget(self.open_project_btn)
        return group

    def _build_version_group(self) -> QGroupBox:
        group = QGroupBox("2. Version")
        layout = QHBoxLayout(group)

        current_box = QVBoxLayout()
        current_box.addWidget(QLabel("Current Version"))
        self.current_version_label = QLabel("--")
        self.current_version_label.setObjectName("versionValue")
        current_box.addWidget(self.current_version_label)
        self.version_source_label = QLabel("")
        self.version_source_label.setObjectName("subheading")
        self.version_source_label.setWordWrap(True)
        current_box.addWidget(self.version_source_label)

        override_box = QVBoxLayout()
        override_box.addWidget(QLabel("Override Detected Version (optional)"))
        self.version_override_input = QLineEdit()
        self.version_override_input.setPlaceholderText("Leave blank to use detected version")
        override_box.addWidget(self.version_override_input)

        new_box = QVBoxLayout()
        new_box.addWidget(QLabel("New Version"))
        self.new_version_input = QLineEdit()
        self.new_version_input.setPlaceholderText("e.g. 2.4.2")
        new_box.addWidget(self.new_version_input)

        layout.addLayout(current_box, stretch=1)
        layout.addLayout(override_box, stretch=1)
        layout.addLayout(new_box, stretch=1)
        return group

    def _build_changes_group(self) -> QGroupBox:
        group = QGroupBox("3. Git Changes")
        layout = QVBoxLayout(group)

        toolbar = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh Git Changes")
        self.refresh_btn.clicked.connect(self._on_refresh_changes)
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self.unselect_all_btn = QPushButton("Unselect All")
        self.unselect_all_btn.clicked.connect(lambda: self._set_all_checked(False))
        self.manage_exclusions_btn = QPushButton("Manage Exclusions...")
        self.manage_exclusions_btn.clicked.connect(self._on_manage_exclusions)

        toolbar.addWidget(self.refresh_btn)
        toolbar.addWidget(self.select_all_btn)
        toolbar.addWidget(self.unselect_all_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.manage_exclusions_btn)
        layout.addLayout(toolbar)

        self.changes_table = QTableWidget(0, 4)
        self.changes_table.setHorizontalHeaderLabels(["Status", "File Path", "Note", "Include"])
        self.changes_table.setAlternatingRowColors(True)
        self.changes_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.changes_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self.changes_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.changes_table.setMinimumHeight(260)
        layout.addWidget(self.changes_table)

        self.summary_label = QLabel("No changes detected yet.")
        self.summary_label.setObjectName("subheading")
        layout.addWidget(self.summary_label)

        return group

    def _build_build_group(self) -> QGroupBox:
        group = QGroupBox("4. Build")
        layout = QHBoxLayout(group)

        self.output_dir_input = QLineEdit()
        self.output_dir_input.setReadOnly(True)

        browse_output_btn = QPushButton("Change Output Folder...")
        browse_output_btn.clicked.connect(self._on_browse_output_dir)

        self.build_btn = QPushButton("Build Update ZIP")
        self.build_btn.setObjectName("primary")
        self.build_btn.clicked.connect(self._on_build_clicked)

        layout.addWidget(QLabel("Output Folder:"))
        layout.addWidget(self.output_dir_input, stretch=1)
        layout.addWidget(browse_output_btn)
        layout.addWidget(self.build_btn)
        return group

    def _build_output_group(self) -> QGroupBox:
        group = QGroupBox("5. Output")
        layout = QHBoxLayout(group)

        self.last_zip_label = QLabel("Last generated ZIP: --")
        self.zip_size_label = QLabel("Size: --")
        self.zip_files_label = QLabel("Files: --")

        self.open_output_btn = QPushButton("Open Output Folder")
        self.open_output_btn.clicked.connect(self._on_open_output_folder)
        self.open_output_btn.setEnabled(False)

        layout.addWidget(self.last_zip_label, stretch=2)
        layout.addWidget(self.zip_size_label, stretch=1)
        layout.addWidget(self.zip_files_label, stretch=1)
        layout.addStretch()
        layout.addWidget(self.open_output_btn)
        return group

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("Log")
        layout = QVBoxLayout(group)
        self.log_panel = QPlainTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setFixedHeight(150)
        layout.addWidget(self.log_panel)
        return group

    # ------------------------------------------------------------------
    # Logging helper
    # ------------------------------------------------------------------
    def log(self, message: str):
        self.log_panel.appendPlainText(message)
        scrollbar = self.log_panel.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def log_info(self, message: str):
        self.log(f"[INFO] {message}")

    def log_success(self, message: str):
        self.log(f"[SUCCESS] {message}")

    def log_error(self, message: str):
        self.log(f"[ERROR] {message}")

    # ------------------------------------------------------------------
    # Project selection
    # ------------------------------------------------------------------
    def _on_browse_project(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Laravel Project Root")
        if directory:
            self.project_path_input.setText(directory)
            self.open_project_btn.setEnabled(True)

    def _on_open_project(self):
        path_text = self.project_path_input.text().strip()
        if not path_text:
            return
        candidate = Path(path_text)

        if not candidate.is_dir():
            show_error(self, "The selected path is not a valid directory.")
            return

        git_dir = candidate / ".git"
        if not git_dir.exists():
            show_error(
                self,
                "This folder does not appear to be a Git repository "
                "(no .git directory found). Please select the Laravel project root.",
            )
            return

        composer_path = candidate / "composer.json"
        if not composer_path.is_file():
            show_error(
                self,
                "composer.json was not found in the selected folder. "
                "Please select the Laravel project root.",
            )
            return

        try:
            if not git_manager.is_git_installed():
                show_error(
                    self,
                    "Git was not found in PATH. Please install Git and make sure "
                    "it is available from the command line, then try again.",
                )
                return

            if not git_manager.verify_is_work_tree(candidate):
                show_error(
                    self,
                    "This folder is not recognized as a Git working tree "
                    "(`git rev-parse --is-inside-work-tree` failed).",
                )
                return
        except git_manager.GitNotInstalledError as exc:
            show_error(self, str(exc))
            return

        self.project_root = candidate
        self.log_info("Project loaded")
        self.log_info("Git repository detected")

        self.output_dir_input.setText(str(candidate / config.OUTPUT_DIR_NAME))

        self._load_version()
        self._on_refresh_changes()
        self._update_enabled_states()

    # ------------------------------------------------------------------
    # Version detection
    # ------------------------------------------------------------------
    def _load_version(self):
        self.log_info("Reading composer.json")
        try:
            result = version_manager.get_current_version(self.project_root)
        except version_manager.ComposerNotFoundError as exc:
            show_error(self, str(exc))
            self.current_version_label.setText("--")
            self.version_source_label.setText("")
            self.detected_version = None
            return
        except version_manager.ComposerParseError as exc:
            show_error(self, "Invalid composer.json.", details=str(exc))
            self.current_version_label.setText("--")
            self.version_source_label.setText("")
            self.detected_version = None
            return

        if result.version:
            self.detected_version = result.version
            self.version_source = result.source
            self.current_version_label.setText(result.version)
            self.version_source_label.setText(f"Source: {result.source}")
            self.log_info(f"Current version: {result.version}")
        else:
            self.detected_version = None
            self.version_source = ""
            self.current_version_label.setText("Not found")
            self.version_source_label.setText("Version not found in composer.json.")
            self.log_error("Version not found in composer.json.")

    def _effective_current_version(self) -> Optional[str]:
        override = self.version_override_input.text().strip()
        if override:
            return override
        return self.detected_version

    # ------------------------------------------------------------------
    # Git change detection
    # ------------------------------------------------------------------
    def _on_refresh_changes(self):
        if self.project_root is None:
            return

        self.log_info("Detecting Git changes")
        try:
            changes: List[Change] = git_manager.get_working_tree_changes(self.project_root)
        except git_manager.GitNotInstalledError as exc:
            show_error(self, str(exc))
            return
        except git_manager.GitCommandError as exc:
            show_error(self, "Git command failed while detecting changes.", details=exc.stderr or str(exc))
            return
        except git_manager.DisallowedGitCommandError as exc:
            show_error(self, str(exc))
            return

        self.classified_files = [
            update_builder.classify_change(change, self.exclusion_rules) for change in changes
        ]

        self._populate_table()

        modified = sum(1 for c in changes if c.status == "M")
        added = sum(1 for c in changes if c.status == "A")
        deleted = sum(1 for c in changes if c.status == "D")
        renamed = sum(1 for c in changes if c.status == "R")
        untracked = sum(1 for c in changes if c.status == "?")

        self.log_info(f"{modified} modified files detected")
        self.log_info(f"{added + untracked} new files detected")
        if deleted:
            self.log_info(f"{deleted} deleted file{'s' if deleted != 1 else ''} detected")
        if renamed:
            self.log_info(f"{renamed} renamed file{'s' if renamed != 1 else ''} detected")

        self._warn_if_dependency_files_changed(changes)

    def _warn_if_dependency_files_changed(self, changes: List[Change]):
        dependency_changed = [c.path for c in changes if update_builder.is_dependency_file(c.path)]
        if dependency_changed:
            names = ", ".join(sorted(set(dependency_changed)))
            self.log_info(
                f"composer.json/composer.lock changed ({names}). "
                "The server may require Composer dependency installation after this update."
            )

    def _populate_table(self):
        self.changes_table.setRowCount(0)
        self.changes_table.setRowCount(len(self.classified_files))

        for row, cf in enumerate(self.classified_files):
            change = cf.change

            status_item = QTableWidgetItem(change.status)
            status_item.setForeground(STATUS_COLORS.get(change.status, QColor("#e6e6e6")))
            font = QFont()
            font.setBold(True)
            status_item.setFont(font)
            status_item.setToolTip(change.status_label)
            self.changes_table.setItem(row, 0, status_item)

            display_path = change.path
            if change.status == "R" and change.old_path:
                display_path = f"{change.old_path}  ->  {change.path}"
            path_item = QTableWidgetItem(display_path)
            self.changes_table.setItem(row, 1, path_item)

            note = ""
            if cf.excluded:
                note = cf.excluded_reason or "Excluded"
            elif cf.is_dependency_file:
                note = "Dependency file -- review before uploading"
            elif cf.is_sensitive:
                note = "Sensitive -- included via override"
            note_item = QTableWidgetItem(note)
            note_item.setForeground(QColor("#9a9ca6"))
            self.changes_table.setItem(row, 2, note_item)

            checkbox = TickCheckBox()
            checkbox.setChecked(not cf.excluded)
            checkbox.stateChanged.connect(self._update_summary)
            container = QWidget()
            hbox = QHBoxLayout(container)
            hbox.addWidget(checkbox)
            hbox.setAlignment(Qt.AlignCenter)
            hbox.setContentsMargins(0, 0, 0, 0)
            self.changes_table.setCellWidget(row, 3, container)
            cf._checkbox = checkbox  # type: ignore[attr-defined]

        self._update_summary()

    def _row_checkbox(self, row: int) -> Optional[QCheckBox]:
        widget = self.changes_table.cellWidget(row, 3)
        if widget is None:
            return None
        return widget.findChild(QCheckBox)

    def _set_all_checked(self, checked: bool):
        for row in range(self.changes_table.rowCount()):
            checkbox = self._row_checkbox(row)
            if checkbox is not None:
                checkbox.setChecked(checked)
        self._update_summary()

    def _update_summary(self, *_args):
        included = 0
        for row in range(self.changes_table.rowCount()):
            checkbox = self._row_checkbox(row)
            if checkbox is not None and checkbox.isChecked():
                included += 1
        total = self.changes_table.rowCount()
        self.summary_label.setText(f"{included} of {total} detected changes selected for the update.")

    def _on_manage_exclusions(self):
        dialog = ExclusionEditorDialog(self.exclusion_rules, self)
        if dialog.exec() == QDialog.Accepted:
            self.exclusion_rules = dialog.result_rules()
            self.log_info("Exclusion rules updated")
            if self.project_root is not None:
                self._on_refresh_changes()

    # ------------------------------------------------------------------
    # Output folder
    # ------------------------------------------------------------------
    def _on_browse_output_dir(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if directory:
            self.output_dir_input.setText(directory)

    def _on_open_output_folder(self):
        if self.last_build_result is None:
            return
        folder = self.last_build_result.zip_path.parent
        self._open_folder(folder)

    @staticmethod
    def _open_folder(folder: Path):
        try:
            if platform.system() == "Windows":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif platform.system() == "Darwin":
                subprocess.run(["open", str(folder)], check=False)
            else:
                subprocess.run(["xdg-open", str(folder)], check=False)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Build flow
    # ------------------------------------------------------------------
    def _on_build_clicked(self):
        if self.project_root is None:
            show_error(self, "Please open a project first.")
            return

        # 1. Refresh Git status
        self._on_refresh_changes()

        current_version = self._effective_current_version()
        new_version = self.new_version_input.text().strip()

        if not new_version:
            show_error(self, "Please enter a new version before building.")
            return
        if not version_manager.is_valid_version_string(new_version):
            show_error(self, "The new version is not valid. It must be non-empty and contain no whitespace.")
            return
        if current_version and new_version == current_version:
            show_error(self, "The new version must be different from the current version.")
            return

        # 2 & 3. Read selected files, split by status
        included: List[ClassifiedFile] = []
        deleted: List[ClassifiedFile] = []
        renamed: List[ClassifiedFile] = []

        for row, cf in enumerate(self.classified_files):
            checkbox = self._row_checkbox(row)
            if checkbox is None or not checkbox.isChecked():
                continue
            if cf.change.status == "D":
                deleted.append(cf)
            elif cf.change.status == "R":
                renamed.append(cf)
                # If the new path still exists, embed it as content too.
                if (self.project_root / cf.change.path).is_file():
                    included.append(cf)
            else:
                included.append(cf)

        if not included and not deleted and not renamed:
            show_error(self, "No files are selected for this update.")
            return

        output_dir = Path(self.output_dir_input.text().strip() or (self.project_root / config.OUTPUT_DIR_NAME))
        zip_name = f"update-{new_version}.zip"
        output_zip_path = output_dir / zip_name

        if output_zip_path.exists():
            answer = QMessageBox.question(
                self,
                "Update Package Already Exists",
                f"An update package for version {new_version} already exists.\nReplace it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self.log_info("Build cancelled -- existing package kept.")
                return

        if not self._show_pre_build_summary(
            current_version, new_version, len(included), len(deleted), len(renamed), output_zip_path
        ):
            self.log_info("Build cancelled by user.")
            return

        plan = BuildPlan(
            from_version=current_version,
            to_version=new_version,
            included=included,
            deleted=deleted,
            renamed=renamed,
            output_zip_path=output_zip_path,
        )

        self.log_info("Building update package")
        self._set_build_in_progress(True)

        self.build_worker = BuildWorker(self.project_root, plan)
        self.build_worker.log_message.connect(self.log)
        self.build_worker.finished_ok.connect(self._on_build_finished_ok)
        self.build_worker.finished_error.connect(self._on_build_finished_error)
        self.build_worker.finished.connect(lambda: self._set_build_in_progress(False))
        self.build_worker.start()

    def _show_pre_build_summary(
        self,
        from_version: Optional[str],
        to_version: str,
        file_count: int,
        deleted_count: int,
        renamed_count: int,
        zip_path: Path,
    ) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle("StreamForge Update")
        layout = QVBoxLayout(dialog)

        text = (
            f"<b>From Version:</b> {from_version or 'Unknown'}<br>"
            f"<b>To Version:</b> {to_version}<br><br>"
            f"<b>Files to update:</b> {file_count}<br>"
            f"<b>Files to delete:</b> {deleted_count}<br>"
            f"<b>Files renamed:</b> {renamed_count}<br><br>"
            f"<b>ZIP:</b> {zip_path}"
        )
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)

        buttons = QDialogButtonBox()
        cancel_btn = buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        build_btn = buttons.addButton("Build Update", QDialogButtonBox.AcceptRole)
        build_btn.setObjectName("primary")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        return dialog.exec() == QDialog.Accepted

    def _set_build_in_progress(self, in_progress: bool):
        self.build_btn.setEnabled(not in_progress)
        self.refresh_btn.setEnabled(not in_progress)
        self.open_project_btn.setEnabled(not in_progress and self.project_root is not None)
        if in_progress:
            self.build_btn.setText("Building...")
        else:
            self.build_btn.setText("Build Update ZIP")

    def _on_build_finished_ok(self, result):
        self.last_build_result = result
        self.last_zip_label.setText(f"Last generated ZIP: {result.zip_path.name}")
        self.zip_size_label.setText(f"Size: {self._format_size(result.zip_size)}")
        self.zip_files_label.setText(f"Files: {result.file_count}")
        self.open_output_btn.setEnabled(True)
        self.log_success(f"{result.zip_path.name} created")

        # Update "current version" to reflect the just-built target version
        # in the UI only -- composer.json itself is never modified.
        new_version = self.new_version_input.text().strip()
        if new_version:
            self.version_override_input.setText(new_version)

        QMessageBox.information(
            self,
            "Build Complete",
            f"Update package created successfully:\n{result.zip_path}",
        )

    def _on_build_finished_error(self, message: str, details: str):
        self.log_error(message)
        show_error(self, self._friendly_build_error(message), details)

    @staticmethod
    def _friendly_build_error(message: str) -> str:
        return f"Failed to build the update package.\n\n{message}"

    @staticmethod
    def _format_size(num_bytes: int) -> str:
        size = float(num_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    # ------------------------------------------------------------------
    def _update_enabled_states(self):
        has_project = self.project_root is not None
        self.refresh_btn.setEnabled(has_project)
        self.select_all_btn.setEnabled(has_project)
        self.unselect_all_btn.setEnabled(has_project)
        self.build_btn.setEnabled(has_project)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLESHEET)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()