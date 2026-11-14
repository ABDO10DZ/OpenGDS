"""Compact, VS Code-inspired source control dock for OpenGDS-IDE.

Repository actions are centralized in a single overflow menu. The change list
stays readable, individual files can be staged from their context menu, and
remote pushes always require a deliberate confirmation.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSettings
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
    QInputDialog, QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPlainTextEdit, QLineEdit, QPushButton, QToolButton, QVBoxLayout, QWidget,
    QSplitter, QComboBox, QTabWidget, QScrollArea, QSizePolicy, QFrame,
)

from git_service import GitChange, GitError, GitService


def _set_diff_text(view: QPlainTextEdit, patch: str, empty_text: str = "No textual diff is available."):
    """Render unified patches with readable added/removed/hunk coloring."""
    view.setPlainText(patch or empty_text)
    document = view.document()
    block = document.begin()
    while block.isValid():
        line = block.text()
        fmt = QTextCharFormat()
        if line.startswith(("+++", "---")):
            fmt.setForeground(QColor("#a7b2c1"))
        elif line.startswith("+"):
            fmt.setForeground(QColor("#8bd5a5"))
            fmt.setBackground(QColor("#183b2c"))
        elif line.startswith("-"):
            fmt.setForeground(QColor("#f08a91"))
            fmt.setBackground(QColor("#45262b"))
        elif line.startswith("@@"):
            fmt.setForeground(QColor("#82b8ed"))
        elif line.startswith(("diff --git", "index ", "new file mode", "deleted file mode")):
            fmt.setForeground(QColor("#c1a4ec"))
        if not fmt.isEmpty():
            cursor = QTextCursor(block)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            cursor.mergeCharFormat(fmt)
        block = block.next()


class CommitGraphDialog(QDialog):
    """Git history browser with graph lanes, commit details and per-file patches."""

    def __init__(self, service: GitService, parent=None):
        super().__init__(parent)
        self.service = service
        self._rows = []
        self.setWindowTitle("Git History · Commit Graph")
        self.resize(1180, 760)
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("COMMIT HISTORY")
        title.setObjectName("panelTitle")
        header.addWidget(title)
        header.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        root.addLayout(header)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.graph = QListWidget()
        self.graph.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.graph.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.graph.setObjectName("gitHistoryGraph")
        self.graph.setMinimumWidth(360)
        self.pages = QTabWidget()
        self.details = QPlainTextEdit()
        self.details.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.details.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.details.setObjectName("diffPreview")
        patch_page = QWidget()
        patch_layout = QVBoxLayout(patch_page)
        patch_layout.setContentsMargins(4, 6, 4, 4)
        self.files = QComboBox()
        self.files.setMinimumHeight(30)
        self.files.currentIndexChanged.connect(self._show_patch)
        self.patch = QPlainTextEdit()
        self.patch.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.patch.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.patch.setReadOnly(True)
        self.patch.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.patch.setObjectName("diffPreview")
        patch_layout.addWidget(self.files)
        patch_layout.addWidget(self.patch, 1)
        self.pages.addTab(self.details, "Commit Details")
        self.pages.addTab(patch_page, "Inline Diff")
        splitter.addWidget(self.graph)
        splitter.addWidget(self.pages)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 760])
        root.addWidget(splitter, 1)
        footer = QHBoxLayout()
        self.status = QLabel("Select a commit to inspect its files and patch.")
        self.status.setObjectName("mutedHint")
        footer.addWidget(self.status, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)
        self.graph.currentItemChanged.connect(self._select_commit)
        self.refresh()

    def refresh(self):
        try:
            self._rows = self.service.history_graph(200)
            self.graph.clear()
            for row in self._rows:
                item = QListWidgetItem(row["line"])
                item.setData(Qt.ItemDataRole.UserRole, row["hash"])
                item.setToolTip(f"Commit {row['hash']}\n{row['subject']}")
                self.graph.addItem(item)
            if self.graph.count():
                self.graph.setCurrentRow(0)
                self.status.setText(f"Showing {len(self._rows)} commits across all local and remote branches.")
            else:
                self.details.setPlainText("No commits were found in this repository yet.")
                self.patch.setPlainText("Make the first commit to start building history.")
                self.status.setText("Repository history is empty.")
        except Exception as exc:
            self.details.setPlainText(f"Could not load Git history: {type(exc).__name__}: {exc}")
            self.status.setText("History unavailable")

    def _select_commit(self, item, _previous=None):
        if not item:
            return
        commit = str(item.data(Qt.ItemDataRole.UserRole) or "")
        try:
            self.details.setPlainText(self.service.commit_details(commit))
            names = self.service.commit_files(commit)
            self.files.blockSignals(True)
            self.files.clear()
            self.files.addItem("All changed files")
            for name in names:
                self.files.addItem(name, name)
            self.files.blockSignals(False)
            self._show_patch()
            self.status.setText(f"Commit {commit}  ·  {len(names)} changed file(s)")
        except Exception as exc:
            self.details.setPlainText(f"Could not read commit {commit}: {type(exc).__name__}: {exc}")

    def _show_patch(self, *_args):
        item = self.graph.currentItem()
        if not item:
            return
        commit = str(item.data(Qt.ItemDataRole.UserRole) or "")
        path = str(self.files.currentData() or "")
        try:
            patch = self.service.commit_diff(commit, path)
            _set_diff_text(self.patch, patch, "This commit contains no textual patch for the selected file.")
        except Exception as exc:
            _set_diff_text(self.patch, f"Could not load patch: {type(exc).__name__}: {exc}")


class GitDock(QWidget):
    """A clean change list with contextual actions and one repository menu."""

    statusChanged = Signal(object)

    _STATUS_COLORS = {
        "?": "#73b7ff", "A": "#78c99b", "M": "#e5b567",
        "D": "#e4777b", "R": "#8cafff", "C": "#8cafff",
        "U": "#f07178", "!": "#8b949e",
    }

    def __init__(self, workspace_getter, log_callback=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SOURCE CONTROL")
        self.workspace_getter = workspace_getter
        self.log_callback = log_callback or (lambda *args, **kwargs: None)
        self.settings = QSettings("OpenGDS", "IDE")
        self.service: GitService | None = None
        self._updating_list = False
        self._changes: list[GitChange] = []
        self._build_ui()

    def _build_ui(self):
        # Keep all source-control controls inside a resizable viewport. When the
        # user reduces this pane, the content becomes scrollable instead of
        # allowing the commit controls and hint label to collide.
        self.setObjectName("sourceControlPanel")
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        host_layout = QVBoxLayout(self)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        self.content_scroll = QScrollArea(self)
        self.content_scroll.setObjectName("sourceControlScroll")
        self.content_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.content_scroll.setMinimumSize(0, 0)
        content = QWidget()
        content.setObjectName("sourceControlContent")
        content.setMinimumWidth(0)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.content_root_layout = QVBoxLayout(content)
        self.content_root_layout.setContentsMargins(12, 10, 12, 12)
        self.content_root_layout.setSpacing(10)
        self.content_scroll.setWidget(content)
        host_layout.addWidget(self.content_scroll, 1)
        panel = content
        root = self.content_root_layout

        header = QHBoxLayout()
        identity = QVBoxLayout()
        title = QLabel("SOURCE CONTROL")
        title.setObjectName("panelTitle")
        subtitle = QLabel("Review, stage and commit workspace changes")
        subtitle.setObjectName("mutedHint")
        identity.addWidget(title)
        identity.addWidget(subtitle)
        header.addLayout(identity, 1)
        self.count_badge = QLabel("0")
        self.count_badge.setObjectName("statusPill")
        self.count_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.count_badge)
        self.overflow = QToolButton()
        self.overflow.setObjectName("overflowButton")
        self.overflow.setText("⋯")
        self.overflow.setToolTip("Repository, branch and remote actions")
        self.overflow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.overflow.setMenu(self._build_overflow_menu())
        header.addWidget(self.overflow)
        root.addLayout(header)

        branch_row = QHBoxLayout()
        branch_caption = QLabel("BRANCH")
        branch_caption.setObjectName("sectionEyebrow")
        self.branch_label = QLabel("—")
        self.branch_label.setObjectName("branchSummary")
        self.branch_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        branch_row.addWidget(branch_caption)
        branch_row.addWidget(self.branch_label, 1)
        branch_row.addStretch(1)
        root.addLayout(branch_row)

        changes_header = QHBoxLayout()
        changes_caption = QLabel("CHANGES")
        changes_caption.setObjectName("sectionEyebrow")
        changes_header.addWidget(changes_caption)
        changes_header.addStretch(1)
        self.summary = QLabel("No repository")
        self.summary.setObjectName("mutedHint")
        changes_header.addWidget(self.summary)
        root.addLayout(changes_header)

        self.changes = QListWidget()
        self.changes.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.changes.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.changes.setObjectName("gitChangesList")
        self.changes.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.changes.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.changes.customContextMenuRequested.connect(self._change_context_menu)
        self.changes.itemDoubleClicked.connect(self._open_item_diff)
        root.addWidget(self.changes, 1)

        commit_caption = QLabel("COMMIT MESSAGE")
        commit_caption.setObjectName("sectionEyebrow")
        root.addWidget(commit_caption)
        self.commit_message = QLineEdit()
        self.commit_message.setObjectName("commitMessage")
        self.commit_message.setPlaceholderText("Describe the changes in this commit…")
        self.commit_message.returnPressed.connect(self.commit)
        root.addWidget(self.commit_message)

        self.commit_button = QPushButton("Commit staged changes")
        self.commit_button.setObjectName("primaryButton")
        self.commit_button.setMinimumHeight(34)
        self.commit_button.setEnabled(False)
        self.commit_button.clicked.connect(self.commit)
        root.addWidget(self.commit_button)

        self.hint = QLabel("Open a project to see its working-tree changes.")
        self.hint.setObjectName("mutedHint")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)
        self.subtitle_label = subtitle
        self.setMinimumWidth(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Below this breakpoint, prioritize the change list and commit action;
        # less essential explanatory copy moves out of the visible viewport.
        compact = event.size().height() < 430
        very_compact = event.size().height() < 330
        self.subtitle_label.setVisible(not compact)
        self.hint.setVisible(not very_compact)
        self.content_root_layout.setContentsMargins(6 if very_compact else (8 if compact else 12),
                                                    4 if very_compact else (7 if compact else 10),
                                                    6 if very_compact else (8 if compact else 12),
                                                    5 if very_compact else (8 if compact else 12))
        self.content_root_layout.setSpacing(4 if very_compact else (6 if compact else 10))
        self.commit_button.setMinimumHeight(28 if very_compact else (30 if compact else 34))
        self.changes.setMinimumHeight(72 if very_compact else (96 if compact else 140))

    def _build_overflow_menu(self):
        menu = QMenu(self)
        menu.addAction("Refresh", self.refresh)
        menu.addAction("Locate Git executable…", self.locate_git)
        menu.addAction("History / Commit Graph…", self.show_history)
        menu.addSeparator()
        menu.addAction("Stage all changes", self.stage_all)
        menu.addAction("Unstage all changes", self.unstage_all)
        menu.addAction("Discard all changes…", self.discard_all)
        menu.addSeparator()
        menu.addAction("Initialize repository…", self.initialize)
        menu.addAction("Clone repository…", self.clone_repository)
        branches = menu.addMenu("Branch")
        branches.addAction("Switch branch…", self.switch_branch)
        branches.addAction("Create branch…", self.create_branch)
        branches.addAction("Refresh branch status", self.refresh)
        remote = menu.addMenu("Remote")
        remote.addAction("Add remote…", self.add_remote)
        remote.addAction("Show remotes", self.show_remotes)
        remote.addSeparator()
        remote.addAction("Fetch all", self.fetch)
        remote.addAction("Pull", self.pull)
        remote.addAction("Push…", self.push)
        menu.addSeparator()
        menu.addAction("Sign in to GitHub…", self.github_login)
        return menu

    def show_history(self):
        try:
            service = self._get_service()
            if not service.is_repository():
                QMessageBox.information(self, "Git History", "Initialize this workspace as a Git repository first.")
                return
            CommitGraphDialog(service, self).exec()
        except Exception as exc:
            self._show_error(exc)

    def set_workspace(self, workspace=None):
        self.service = None
        self.refresh()

    def _get_service(self) -> GitService:
        root = self.workspace_getter()
        if not root:
            raise GitError("Open a project or workspace first.")
        root = Path(root).resolve()
        if self.service is None or self.service.root != root:
            configured_git = str(self.settings.value("git/executable", "") or "").strip()
            self.service = GitService(root, git_executable=configured_git or None)
        return self.service

    def locate_git(self):
        current = str(self.settings.value("git/executable", "") or "")
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, "Locate Git executable", current,
            "Git executable (git.exe git);;All files (*)")
        if not path:
            return
        candidate = Path(path).expanduser().resolve()
        if not candidate.is_file():
            QMessageBox.warning(self, "Locate Git", "The selected Git executable does not exist.")
            return
        try:
            root = self.workspace_getter()
            if not root:
                raise GitError("Open a project or workspace first.")
            service = GitService(root, git_executable=str(candidate))
            version = service.run("--version").stdout.strip()
            if not version.lower().startswith("git version"):
                raise GitError("The selected program did not identify itself as Git.")
            self.settings.setValue("git/executable", str(candidate))
            self.service = service
            self.refresh()
            self.hint.setText(f"Using {version}  ·  Git executable saved for this Windows user.")
        except Exception as exc:
            QMessageBox.warning(self, "Locate Git", f"Could not use the selected executable:\n{type(exc).__name__}: {exc}")

    def _show_error(self, exc):
        QMessageBox.warning(self, "Source Control", str(exc))

    def _log_result(self, result):
        if result:
            self.log_callback(str(result), category="SYSTEM")

    @staticmethod
    def _status_code(status: str) -> str:
        if status == "??":
            return "?"
        return next((char for char in status if char not in {" "}), "M")

    def _append_change(self, change: GitChange):
        code = change.status if change.status == "??" else change.status.strip() or "M"
        item = QListWidgetItem(f"{code:<2}   {change.path}")
        item.setData(Qt.ItemDataRole.UserRole, change.path)
        item.setData(Qt.ItemDataRole.UserRole + 1, change.status)
        item.setForeground(QColor(self._STATUS_COLORS.get(self._status_code(change.status), "#9aa4b2")))
        item.setToolTip(
            f"{change.path}\nGit status: {change.status}\n"
            f"Staged: {'yes' if change.staged else 'no'}\n"
            f"Working-tree changes: {'yes' if change.unstaged else 'no'}\n"
            "Double-click to inspect the diff. Right-click for file actions."
        )
        self.changes.addItem(item)

    def refresh(self):
        self._updating_list = True
        self.changes.clear()
        self.commit_button.setEnabled(False)
        self.branch_label.setText("—")
        try:
            root = self.workspace_getter()
            if not root:
                self.summary.setText("No workspace")
                self.count_badge.setText("0")
                self._update_overflow_state(0, 0)
                empty = QListWidgetItem("Open a project or folder to inspect its Git working tree.")
                empty.setForeground(QColor("#8797aa"))
                self.changes.addItem(empty)
                self.hint.setText("Branch, remote, history and repository actions are available from the ⋯ menu.")
                self.statusChanged.emit({})
                return
            service = self._get_service()
            if not service.is_repository():
                self.branch_label.setText("Not initialized")
                self.summary.setText("Not initialized")
                self.count_badge.setText("0")
                self._update_overflow_state(0, 0)
                empty = QListWidgetItem("No repository yet\n\nInitialize Git here or clone an existing repository from the ⋯ menu.")
                empty.setForeground(QColor("#8797aa"))
                self.changes.addItem(empty)
                self.hint.setText("History and commit graph become available after the first commit.")
                self.statusChanged.emit({})
                return

            current = service.branch()
            self.branch_label.setText(current or "Detached HEAD")
            self.branch_label.setToolTip("Use ⋯ → Branch → Switch branch to change branches.")

            self._changes = sorted(service.status(), key=lambda item: (not item.staged, item.path.casefold()))
            staged_count = sum(1 for change in self._changes if change.staged)
            self.summary.setText(f"{len(self._changes)} pending" if self._changes else "Clean")
            self.count_badge.setText(str(len(self._changes)))
            self._update_overflow_state(len(self._changes), staged_count)
            self.statusChanged.emit({change.path: change.status for change in self._changes})

            if not self._changes:
                empty = QListWidgetItem("✓   Working tree clean\n\nYour workspace has no pending changes.")
                empty.setForeground(QColor("#8bc7a2"))
                self.changes.addItem(empty)
                self.hint.setText(f"{service.root.name}  ·  {current}  ·  History is available from ⋯ → History / Commit Graph.")
            else:
                for change in self._changes:
                    self._append_change(change)
                self.hint.setText(
                    "Select a file and right-click to stage, unstage, inspect or discard it. "
                    "Double-click opens its diff."
                )
            self.commit_button.setText(f"Commit staged changes  ·  {staged_count}")
            self.commit_button.setEnabled(staged_count > 0)
        except Exception as exc:
            self.summary.setText("Unavailable")
            self.count_badge.setText("!")
            self._update_overflow_state(0, 0, error=True)
            self.changes.addItem(f"Source control unavailable: {exc}")
            self.hint.setText("Install Git for Windows, or use ⋯ → Locate Git executable… to select git.exe. You can also set OPENGDS_GIT_EXECUTABLE.")
            self.statusChanged.emit({})
        finally:
            self._updating_list = False

    def _update_overflow_state(self, changed: int, staged: int, error: bool = False):
        """Use the single overflow control as the quiet repository activity indicator."""
        if error:
            color, label = "#e4777b", "Source control error"
        elif changed:
            color = "#78c99b" if staged and staged == changed else "#e5b567"
            label = f"{changed} changed · {staged} staged"
        else:
            color, label = "#8292a6", "Working tree clean"
        self.overflow.setStyleSheet(
            f"QToolButton#overflowButton {{ color:{color}; border:1px solid transparent; }}"
            f"QToolButton#overflowButton:hover {{ background:rgba(120,150,180,0.14); border-color:{color}; }}"
        )
        self.overflow.setToolTip(f"{label} · Repository, branch and remote actions")

    def _selected_paths(self):
        paths = []
        for item in self.changes.selectedItems():
            value = item.data(Qt.ItemDataRole.UserRole)
            if value:
                paths.append(str(value))
        return list(dict.fromkeys(paths))

    def _change_context_menu(self, point):
        item = self.changes.itemAt(point)
        path = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not path:
            return
        status = str(item.data(Qt.ItemDataRole.UserRole + 1) or "  ")
        menu = QMenu(self)
        if status[0:1] not in {" ", "?"}:
            unstage = menu.addAction("Unstage")
        else:
            unstage = None
        if status[1:2] != " " or status == "??":
            stage = menu.addAction("Stage")
        else:
            stage = None
        menu.addSeparator()
        diff = menu.addAction("Open diff")
        discard = menu.addAction("Discard changes…")
        chosen = menu.exec(self.changes.mapToGlobal(point))
        try:
            if chosen == stage:
                self.stage_paths([path])
            elif chosen == unstage:
                self.unstage_paths([path])
            elif chosen == diff:
                self.diff_path(path)
            elif chosen == discard:
                self.discard_paths([path])
        except Exception as exc:
            self._show_error(exc)

    def _open_item_diff(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.diff_path(path)

    def stage_paths(self, paths: list[str]):
        self._log_result(self._get_service().stage(paths))
        self.refresh()

    def unstage_paths(self, paths: list[str]):
        self._log_result(self._get_service().unstage(paths))
        self.refresh()

    def diff_path(self, path: str):
        output = self._get_service().diff(path)
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Diff · {Path(path).name}")
        dialog.resize(900, 620)
        layout = QVBoxLayout(dialog)
        heading = QLabel(str(path))
        heading.setObjectName("dialogIntro")
        layout.addWidget(heading)
        view = QPlainTextEdit()
        view.setObjectName("diffPreview")
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        _set_diff_text(view, output)
        layout.addWidget(view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def discard_paths(self, paths: list[str]):
        if not paths:
            return
        answer = QMessageBox.warning(
            self, "Discard changes",
            "Permanently discard uncommitted changes to:\n\n" + "\n".join(paths) +
            "\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Discard:
            self._log_result(self._get_service().discard(paths))
            self.refresh()

    def stage_all(self):
        try:
            paths = [change.path for change in self._get_service().status() if change.unstaged]
            if paths:
                self.stage_paths(paths)
        except Exception as exc:
            self._show_error(exc)

    def unstage_all(self):
        try:
            paths = [change.path for change in self._get_service().status() if change.staged]
            if paths:
                self.unstage_paths(paths)
        except Exception as exc:
            self._show_error(exc)

    def discard_all(self):
        try:
            paths = [change.path for change in self._get_service().status()]
            self.discard_paths(paths)
        except Exception as exc:
            self._show_error(exc)

    def initialize(self):
        try:
            self._log_result(self._get_service().init())
            self.refresh()
        except Exception as exc:
            self._show_error(exc)

    def commit(self):
        message = self.commit_message.text().strip()
        if not message:
            QMessageBox.information(self, "Commit", "Enter a commit message first.")
            self.commit_message.setFocus()
            return
        try:
            service = self._get_service()
            staged = [change for change in service.status() if change.staged]
            if not staged:
                QMessageBox.information(self, "Commit", "Stage at least one file before committing.")
                return
            for key, label in (
                ("user.name", "Name for commits (stored in this repository)"),
                ("user.email", "Email for commits (stored in this repository)"),
            ):
                existing = service.run("config", "--get", key, check=False).stdout.strip()
                if not existing:
                    value, ok = QInputDialog.getText(self, "Git identity", label + ":")
                    if not ok or not value.strip():
                        return
                    service.run("config", key, value.strip())
            self._log_result(service.commit(message))
            self.commit_message.clear()
            self.refresh()
        except Exception as exc:
            self._show_error(exc)

    def _run_remote_action(self, callback):
        try:
            self._log_result(callback(self._get_service()))
            self.refresh()
        except Exception as exc:
            self._show_error(exc)

    def fetch(self):
        self._run_remote_action(lambda service: service.fetch())

    def pull(self):
        self._run_remote_action(lambda service: service.pull())

    def push(self):
        try:
            service = self._get_service()
            remotes = service.remotes()
            if not remotes:
                raise GitError("No remote is configured. Use ⋯ → Remote → Add remote first.")
            remote = "origin" if "origin" in remotes else next(iter(remotes))
            branch = service.branch()
            remote_url = remotes.get(remote, "")
            is_github = "github.com" in remote_url.lower()
            auth_status = ""
            if is_github:
                try:
                    authenticated, auth_status = service.github_auth_status()
                except GitError as auth_error:
                    authenticated = False
                    auth_status = str(auth_error)
                auth_box = QMessageBox(self)
                auth_box.setWindowTitle("GitHub authentication")
                auth_box.setIcon(QMessageBox.Icon.Information)
                auth_box.setText("Review authentication before publishing to GitHub.")
                state = "GitHub CLI reports an authenticated account." if authenticated else "GitHub CLI does not report an authenticated account."
                auth_box.setInformativeText(
                    state + ("\n\n" + auth_status if auth_status else "") +
                    "\n\nSign in now, or continue with your configured Git Credential Manager / SSH credentials."
                )
                sign_in = auth_box.addButton("Sign in to GitHub…", QMessageBox.ButtonRole.ActionRole)
                use_credentials = auth_box.addButton("Continue with Git credentials", QMessageBox.ButtonRole.AcceptRole)
                auth_box.addButton(QMessageBox.StandardButton.Cancel)
                auth_box.setDefaultButton(auth_box.button(QMessageBox.StandardButton.Cancel))
                auth_box.exec()
                selected_auth = auth_box.clickedButton()
                if selected_auth == sign_in:
                    self.github_login()
                    return
                if selected_auth != use_credentials:
                    return
            box.setWindowTitle("Publish commits")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(f"Publish committed changes to <b>{remote}/{branch}</b>?")
            box.setInformativeText(
                "This sends local commits to the configured remote. "
                + ("GitHub authentication has been checked. " if is_github else "Authentication will use your configured Git Credential Manager or SSH key. ")
                + "Review the destination before continuing."
            )
            push_now = box.addButton("Publish changes", QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(box.button(QMessageBox.StandardButton.Cancel))
            box.exec()
            if box.clickedButton() != push_now:
                return
            self._log_result(service.push(remote=remote, branch=branch))
            QMessageBox.information(self, "Push complete", f"Local commits were pushed to {remote}/{branch}.")
            self.refresh()
        except Exception as exc:
            self._show_error(exc)

    def switch_branch(self):
        try:
            service = self._get_service()
            branches = service.branches()
            if not branches:
                QMessageBox.information(self, "Switch branch", "This repository has no local branches yet.")
                return
            current = service.branch()
            selected, ok = QInputDialog.getItem(
                self, "Switch branch", "Choose a local branch:", branches,
                max(0, branches.index(current)) if current in branches else 0, False,
            )
            if not ok or not selected or selected == current:
                return
            pending = service.status()
            if pending:
                answer = QMessageBox.warning(
                    self, "Switch branch with uncommitted changes",
                    f"There are {len(pending)} changed path(s). Git may refuse the switch if changes conflict.\n\nSwitch to '{selected}' anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            self._log_result(service.switch_branch(selected))
            self.refresh()
        except Exception as exc:
            self._show_error(exc)
            self.refresh()

    def create_branch(self):
        name, ok = QInputDialog.getText(self, "Create branch", "New branch name:")
        if ok and name.strip():
            try:
                self._log_result(self._get_service().create_branch(name.strip()))
                self.refresh()
            except Exception as exc:
                self._show_error(exc)

    def add_remote(self):
        name, ok = QInputDialog.getText(self, "Add remote", "Remote name:", text="origin")
        if not ok or not name.strip():
            return
        url, ok = QInputDialog.getText(self, "Add remote", "Remote URL (HTTPS or SSH):")
        if ok and url.strip():
            try:
                self._log_result(self._get_service().add_remote(name.strip(), url.strip()))
                self.refresh()
            except Exception as exc:
                self._show_error(exc)

    def show_remotes(self):
        try:
            remotes = self._get_service().remotes()
            content = "\n".join(f"{name}   {url}" for name, url in remotes.items()) or "No remotes configured."
            QMessageBox.information(self, "Git remotes", content)
        except Exception as exc:
            self._show_error(exc)

    def github_login(self):
        try:
            service = self._get_service()
            authenticated, status = service.github_auth_status()
            if authenticated:
                QMessageBox.information(self, "GitHub", status or "Already signed in to GitHub.")
                return
            answer = QMessageBox.question(
                self, "Sign in to GitHub",
                (status + "\n\n" if status else "") +
                "Open GitHub CLI sign-in in a separate terminal? GitHub CLI must be installed.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                service.launch_github_login()
        except Exception as exc:
            self._show_error(exc)

    def clone_repository(self):
        url, ok = QInputDialog.getText(self, "Clone repository", "Repository URL (HTTPS or SSH):")
        if not ok or not url.strip():
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose parent folder for clone")
        if not folder:
            return
        suggested = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git") or "repository"
        name, ok = QInputDialog.getText(self, "Clone repository", "Destination folder name:", text=suggested)
        if not ok or not name.strip():
            return
        try:
            target = Path(folder) / name.strip()
            cloned = GitService.clone(url.strip(), target)
            self.log_callback(f"Cloned {url.strip()} into {cloned}", category="FILE")
            QMessageBox.information(self, "Clone complete", f"Repository cloned to:\n{cloned}\n\nOpen that folder as a project in OpenGDS-IDE.")
        except Exception as exc:
            self._show_error(exc)
