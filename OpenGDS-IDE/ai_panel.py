"""Polished AI assistant dock with Ask/Agent modes and explicit change review."""
from __future__ import annotations

import html
import logging
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QEvent, QThread, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QColor, QTextCharFormat, QTextCursor, QFont, QTextOption
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QTextBrowser, QToolButton, QVBoxLayout, QWidget, QLineEdit,
    QSpinBox, QTabWidget, QFrame, QSplitter, QCheckBox, QTextEdit,
    QScrollArea, QSizePolicy,
)

from ai_agent import (AgentCancelled, AgentConfig, AgentEngine, CredentialStore, PROVIDERS,
                      requires_change_proposal, scope_allows)
from logging_system import log_event


def _setting_enabled(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _set_agent_diff_text(view: QPlainTextEdit, patch: str):
    view.setPlainText(patch or "No textual diff is available.")
    block = view.document().begin()
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
        if not fmt.isEmpty():
            cursor = QTextCursor(block)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            cursor.mergeCharFormat(fmt)
        block = block.next()


class _AgentWorker(QThread):
    finishedText = Signal(str)
    failedText = Signal(str)
    streamChunk = Signal(str)
    cancelled = Signal()

    def __init__(self, engine: AgentEngine, prompt: str, context: str, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.prompt = prompt
        self.context = context
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()
        self.engine.cancel()

    def run(self):
        try:
            answer = self.engine.ask(
                self.prompt, editor_context=self.context,
                cancel_event=self.cancel_event, on_delta=self.streamChunk.emit,
            )
            self.finishedText.emit(answer)
        except AgentCancelled:
            self.cancelled.emit()
        except Exception as exc:
            if self.cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.failedText.emit(f"{type(exc).__name__}: {exc}")


class _ApprovalWorker(QThread):
    finishedResults = Signal(object)

    def __init__(self, engine: AgentEngine, action_ids: list[str], parent=None):
        super().__init__(parent)
        self.engine = engine
        self.action_ids = list(action_ids)

    def run(self):
        outcomes = []
        for action_id in self.action_ids:
            try:
                outcomes.append((action_id, self.engine.approve(action_id), False))
            except Exception as exc:
                outcomes.append((action_id, f"{type(exc).__name__}: {exc}", True))
        self.finishedResults.emit(outcomes)


class AgentSettingsDialog(QDialog):
    def __init__(self, settings, credentials: CredentialStore, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.credentials = credentials
        self._forget = False
        current_provider = str(settings.value("ai/provider", "OpenRouter Free"))
        if current_provider not in PROVIDERS:
            current_provider = "OpenRouter Free"
        self.setWindowTitle("AI assistant · Providers, models and retrieval")
        self.resize(700, 600)
        root = QVBoxLayout(self)
        intro = QLabel("Choose a hosted API or a local model. Free options are preconfigured for testing; hosted free tiers still require your own account/API key and are subject to provider quotas, model availability and data policies.")
        intro.setWordWrap(True)
        intro.setObjectName("dialogIntro")
        root.addWidget(intro)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.provider = QComboBox()
        self.provider.addItems(PROVIDERS.keys())
        self.provider.setCurrentText(current_provider)
        self.model = QLineEdit(str(settings.value("ai/model", PROVIDERS[current_provider].get("default_model", ""))))
        self.model.setPlaceholderText("Model ID")
        self.base_url = QLineEdit(str(settings.value("ai/base_url", PROVIDERS[current_provider]["base_url"])))
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Paste your provider key · stored for this Windows user")
        self.key_note = QLabel()
        self.key_note.setWordWrap(True)
        self.key_link = QPushButton("Get API key…")
        self.key_link.clicked.connect(self.open_provider_key_page)
        key_row = QHBoxLayout()
        key_row.addWidget(self.api_key, 1)
        key_row.addWidget(self.key_link)
        key_widget = QWidget(); key_widget.setLayout(key_row)
        self.timeout = QSpinBox(); self.timeout.setRange(10, 300); self.timeout.setSuffix(" s")
        self.timeout.setValue(int(settings.value("ai/timeout", 120)))
        self.embedding_enabled = QCheckBox("Use embeddings for semantic workspace retrieval")
        self.embedding_enabled.setChecked(_setting_enabled(settings.value("ai/use_embeddings", False)))
        self.embedding_model = QLineEdit(str(settings.value("ai/embedding_model", "")))
        self.embedding_model.setPlaceholderText("Embedding model ID, e.g. text-embedding-3-small")
        self.embeddings_url = QLineEdit(str(settings.value("ai/embeddings_url", "")))
        self.embeddings_url.setPlaceholderText("Optional custom URL · https://host/v1/embeddings")
        form.addRow("Provider", self.provider)
        form.addRow("Model", self.model)
        form.addRow("API endpoint", self.base_url)
        form.addRow("API key", key_widget)
        form.addRow("Provider notes", self.key_note)
        form.addRow("Request timeout", self.timeout)
        form.addRow("Semantic retrieval", self.embedding_enabled)
        form.addRow("Embeddings model", self.embedding_model)
        form.addRow("Embeddings endpoint (optional)", self.embeddings_url)
        root.addLayout(form)

        privacy = QLabel("Embeddings are optional. By default the IDE derives an OpenAI-compatible /embeddings URL from the chat API endpoint. You may override it with a separate HTTPS endpoint (HTTP is allowed for localhost). The embedding model can differ from the chat model. Embeddings requests use the configured provider API key. Semantic retrieval sends selected workspace text to that endpoint and may have separate quotas or costs. Claude's native Messages API does not expose this endpoint. Credentials are stored outside the project; review provider data policies before sending source code.")
        privacy.setWordWrap(True)
        privacy.setObjectName("mutedHint")
        root.addWidget(privacy)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_validated)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.provider.currentTextChanged.connect(self._provider_changed)
        self._provider_changed(current_provider, initial=True)

    def _provider_changed(self, provider, initial=False):
        preset = PROVIDERS.get(provider, {})
        old_provider = str(self.settings.value("ai/provider", "OpenRouter Free"))
        old_base = PROVIDERS.get(old_provider, {}).get("base_url", "")
        if not initial and (not self.base_url.text().strip() or self.base_url.text().strip() == old_base):
            self.base_url.setText(preset.get("base_url", ""))
        old_default_model = PROVIDERS.get(old_provider, {}).get("default_model", "")
        if not initial and (not self.model.text().strip() or self.model.text().strip() == old_default_model):
            self.model.setText(preset.get("default_model", ""))
        requires_key = preset.get("requires_api_key", True)
        self.api_key.setEnabled(requires_key)
        self.api_key.setPlaceholderText("Not required for local Ollama" if not requires_key else "Paste your provider key · stored for this Windows user")
        self.key_link.setEnabled(bool(preset.get("signup_url")))
        self.key_note.setText(f"{preset.get('tier', 'Custom')}\n{preset.get('note', '')}")

    def _accept_validated(self):
        if self.embedding_enabled.isChecked() and not self.embedding_model.text().strip():
            QMessageBox.warning(self, "Embeddings model required",
                                "Enter a model ID supported by the selected embeddings endpoint, or turn semantic retrieval off.")
            self.embedding_model.setFocus()
            return
        custom_endpoint = self.embeddings_url.text().strip()
        if custom_endpoint:
            try:
                parsed = urlsplit(custom_endpoint)
                local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                valid_endpoint = ((parsed.scheme == "https" or local_http) and bool(parsed.netloc)
                                  and not parsed.username and not parsed.password
                                  and not parsed.query and not parsed.fragment)
            except ValueError:
                valid_endpoint = False
            if not valid_endpoint:
                QMessageBox.warning(self, "Invalid embeddings endpoint",
                                    "Use an HTTPS endpoint without credentials, query parameters or fragments. HTTP is allowed only for localhost.")
                self.embeddings_url.setFocus()
                return
        elif self.embedding_enabled.isChecked() and not self.base_url.text().strip():
            QMessageBox.warning(self, "Embeddings endpoint required",
                                "Enter a chat API base URL or provide a separate embeddings endpoint.")
            self.base_url.setFocus()
            return
        elif (self.embedding_enabled.isChecked()
              and PROVIDERS.get(self.provider.currentText(), {}).get("protocol") == "anthropic"):
            QMessageBox.warning(self, "Separate embeddings endpoint required",
                                "Claude's chat API does not provide embeddings. Enter an OpenAI-compatible embeddings endpoint to use semantic retrieval.")
            self.embeddings_url.setFocus()
            return
        self.accept()

    def open_provider_key_page(self):
        url = PROVIDERS.get(self.provider.currentText(), {}).get("signup_url", "")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def save_values(self):
        provider = self.provider.currentText()
        model = self.model.text().strip() or PROVIDERS.get(provider, {}).get("default_model", "")
        embedding_model = self.embedding_model.text().strip()
        if self.embedding_enabled.isChecked() and not embedding_model:
            raise ValueError("Enter an embeddings model ID or turn semantic retrieval off.")
        self.settings.setValue("ai/provider", provider)
        self.settings.setValue("ai/model", model)
        self.settings.setValue("ai/base_url", self.base_url.text().strip() or PROVIDERS[provider]["base_url"])
        self.settings.setValue("ai/timeout", self.timeout.value())
        self.settings.setValue("ai/use_embeddings", "true" if self.embedding_enabled.isChecked() else "false")
        self.settings.setValue("ai/embedding_model", embedding_model)
        self.settings.setValue("ai/embeddings_url", self.embeddings_url.text().strip())
        if self._forget:
            self.credentials.set(provider, "")
        elif self.api_key.text().strip():
            self.credentials.set(provider, self.api_key.text().strip())


class AgentChangeReviewDialog(QDialog):
    """Review all AI proposals in one list-and-diff workspace."""
    acceptRequested = Signal(object)
    declineRequested = Signal(object)

    def __init__(self, engine: AgentEngine, actions, selected_ids=None, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.actions = list(actions)
        self.setWindowTitle("Review Agent Changes")
        self.resize(1120, 720)
        root = QVBoxLayout(self)
        header = QLabel("REVIEW PROPOSED CHANGES  ·  Nothing is applied until you accept it")
        header.setObjectName("panelTitle")
        root.addWidget(header)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.items = QListWidget()
        self.items.setMinimumWidth(280)
        self.items.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setObjectName("diffPreview")
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        splitter.addWidget(self.items)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 760])
        root.addWidget(splitter, 1)
        self.meta = QLabel("Select a proposal to inspect its diff or operation details.")
        self.meta.setObjectName("mutedHint")
        self.meta.setWordWrap(True)
        root.addWidget(self.meta)
        actions_row = QHBoxLayout()
        select_all = QPushButton("Select All")
        select_all.clicked.connect(self._select_all)
        accept = QPushButton("Accept Selected")
        accept.setObjectName("primaryButton")
        accept.clicked.connect(self._accept)
        decline = QPushButton("Decline Selected")
        decline.clicked.connect(self._decline)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        actions_row.addWidget(select_all)
        actions_row.addStretch(1)
        actions_row.addWidget(decline)
        actions_row.addWidget(accept)
        actions_row.addWidget(close)
        root.addLayout(actions_row)
        self.items.currentItemChanged.connect(self._show_item)
        selected_ids = set(selected_ids or [])
        for action in self.actions:
            if action.kind == "file":
                label = f"{action.operation.upper()}  ·  {action.path}"
                color = "#82b8ed"
            elif action.kind == "opengds":
                label = f"OPEN GDS  ·  {action.path}"
                color = "#8bc7a2"
            else:
                label = f"COMMAND  ·  {' '.join(action.argv)}"
                color = "#e5b567"
            item = QListWidgetItem(label)
            item.setForeground(QColor(color))
            item.setData(Qt.ItemDataRole.UserRole, action.action_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setToolTip(action.reason)
            self.items.addItem(item)
            if action.action_id in selected_ids:
                item.setSelected(True)
                item.setCheckState(Qt.CheckState.Checked)
        if self.items.count():
            self.items.setCurrentRow(0)
            if selected_ids:
                for i in range(self.items.count()):
                    if self.items.item(i).data(Qt.ItemDataRole.UserRole) in selected_ids:
                        self.items.setCurrentRow(i)
                        break

    def _selected_ids(self):
        checked = [self.items.item(index).data(Qt.ItemDataRole.UserRole)
                   for index in range(self.items.count())
                   if self.items.item(index).checkState() == Qt.CheckState.Checked]
        if checked:
            ids = checked
        else:
            ids = [item.data(Qt.ItemDataRole.UserRole) for item in self.items.selectedItems()]
        if not ids and self.items.currentItem():
            ids = [self.items.currentItem().data(Qt.ItemDataRole.UserRole)]
        return [value for value in ids if value]

    def _select_all(self):
        for index in range(self.items.count()):
            item = self.items.item(index)
            item.setSelected(True)
            item.setCheckState(Qt.CheckState.Checked)

    def _show_item(self, item, _previous=None):
        if not item:
            return
        action_id = item.data(Qt.ItemDataRole.UserRole)
        action = next((row for row in self.actions if row.action_id == action_id), None)
        if not action:
            return
        self.meta.setText(f"{action.reason}  ·  {action.path or action.operation or action.kind}")
        try:
            if action.kind == "file":
                body = self.engine.preview(action_id)
            elif action.kind == "opengds":
                body = self.engine.preview(action_id)
            else:
                body = ("COMMAND PROPOSAL\n\n"
                        + "Arguments: " + " ".join(action.argv) + "\n"
                        + f"Working directory: {action.cwd or '.'}\n\n"
                        + f"Reason: {action.reason}\n\n"
                        "This command has not been executed. Approving it will run the exact argument array without a shell.")
            _set_agent_diff_text(self.preview, body)
        except Exception as exc:
            _set_agent_diff_text(self.preview, f"Could not generate preview: {type(exc).__name__}: {exc}")

    def set_approving(self, busy: bool):
        self.items.setEnabled(not busy)
        self.meta.setText("Applying approved changes…" if busy else self.meta.text())

    def resolve_approvals(self, outcomes):
        failed_ids = {action_id for action_id, _message, failed in outcomes if failed}
        declined_ids = {action_id for action_id, message, failed in outcomes
                        if not failed and str(message).startswith("Declined by user.")}
        successful_ids = {action_id for action_id, _message, failed in outcomes
                          if not failed and action_id not in declined_ids}
        removed_ids = successful_ids | declined_ids
        for index in range(self.items.count() - 1, -1, -1):
            item = self.items.item(index)
            action_id = item.data(Qt.ItemDataRole.UserRole)
            if action_id in removed_ids:
                self.items.takeItem(index)
            elif action_id in failed_ids:
                message = next((text for key, text, failed in outcomes if key == action_id and failed), "Approval failed")
                item.setForeground(QColor("#f08a91"))
                item.setToolTip(str(message))
                item.setCheckState(Qt.CheckState.Unchecked)
        self.actions = [action for action in self.actions if action.action_id not in removed_ids]
        self.items.setEnabled(True)
        failures = [text for _key, text, failed in outcomes if failed]
        if failures:
            self.meta.setText("Some changes could not be applied. They remain pending and were not overwritten:\n" + "\n".join(failures))
        elif declined_ids:
            self.meta.setText("Selected proposals were declined. No files were changed.")
        else:
            self.meta.setText("All selected changes were applied successfully.")
        if self.items.count() and not self.items.currentItem():
            self.items.setCurrentRow(0)

    def _accept(self):
        ids = self._selected_ids()
        if ids:
            self.acceptRequested.emit(ids)

    def _decline(self):
        ids = self._selected_ids()
        if ids:
            self.declineRequested.emit(ids)


class AIAgentDock(QWidget):
    def __init__(self, settings, workspace_getter, editor_getter, parent=None, *, backend_getter=None, open_path=None):
        super().__init__(parent)
        self.setWindowTitle("AI ASSISTANT")
        self.settings = settings
        self.workspace_getter = workspace_getter
        self.editor_getter = editor_getter
        self.backend_getter = backend_getter
        self.open_path = open_path
        self.credentials = CredentialStore()
        self.engine: AgentEngine | None = None
        self.engine_root: Path | None = None
        self.worker: _AgentWorker | None = None
        self.approval_worker: _ApprovalWorker | None = None
        self.transcript: list[tuple[str, str]] = []
        self.approval_buttons: list[QPushButton] = []
        self._streaming_text = ""
        self._stream_buffer = ""
        self._stream_cursor: QTextCursor | None = None
        self._stream_timer = QTimer(self)
        self._stream_timer.setSingleShot(True)
        self._stream_timer.setInterval(35)
        self._stream_timer.timeout.connect(self._flush_stream_buffer)
        self._pending_before_request: set[str] = set()
        self._request_requires_changes = False
        self._active_review_dialog: AgentChangeReviewDialog | None = None
        self._approval_paths: dict[str, str] = {}
        self._build_ui()

    def _build_ui(self):
        root_widget = self
        root_widget.setObjectName("aiAssistantPanel")
        root = QVBoxLayout(root_widget)
        self._root_layout = root
        root.setContentsMargins(8, 7, 8, 8)
        root.setSpacing(7)

        header = QHBoxLayout()
        identity = QVBoxLayout()
        title = QLabel("AI ASSISTANT")
        title.setObjectName("panelTitle")
        self.provider_label = QLabel("OpenRouter Free · setup required")
        self.provider_label.setObjectName("mutedHint")
        self.provider_label.setWordWrap(True)
        self.provider_label.setMinimumWidth(0)
        self.provider_label.setToolTip("Selected chat provider and model")
        identity.addWidget(title)
        identity.addWidget(self.provider_label)
        header.addLayout(identity, 1)
        self.pending_badge = QPushButton("0 changes")
        self.pending_badge.setObjectName("pendingBadge")
        self.pending_badge.setToolTip("Open the AI changes review")
        self.pending_badge.clicked.connect(lambda: self.pages.setCurrentIndex(1))
        header.addWidget(self.pending_badge)
        self.overflow = QToolButton()
        self.overflow.setObjectName("overflowButton")
        self.overflow.setText("⋯")
        self.overflow.setToolTip("Assistant options")
        self.overflow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        menu.addAction("Configure provider and model…", self.configure)
        menu.addAction("New conversation", self.clear_chat)
        menu.addAction("Forget saved provider key…", self.forget_current_key)
        menu.addSeparator()
        menu.addAction("Open pending changes", lambda: self.pages.setCurrentIndex(1))
        menu.addAction("Accept all pending changes…", self.accept_all)
        menu.addAction("Decline all pending changes…", self.reject_all)
        self.overflow.setMenu(menu)
        header.addWidget(self.overflow)
        root.addLayout(header)

        self.pages = QTabWidget()
        self.pages.setObjectName("assistantPages")
        self.pages.setMinimumSize(0, 88)
        self.pages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.chat = QTextBrowser()
        self.chat.setObjectName("assistantTranscript")
        # Keep the vertical scrollbar visible so users can always discover and
        # operate transcript scrolling, even when the current response is short.
        # It becomes scrollable as soon as the document exceeds the viewport.
        self.chat.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.chat.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chat.setMinimumWidth(0)
        self.chat.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.chat.verticalScrollBar().setObjectName("assistantChatScrollBar")
        self.chat.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        # PySide6's QTextOption constructor accepts no wrap-mode argument.
        # Configure the option after construction for compatibility across Qt 6 builds.
        chat_text_option = QTextOption()
        chat_text_option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.chat.document().setDefaultTextOption(chat_text_option)
        self.chat.setOpenExternalLinks(True)
        self.chat.setHtml(self._welcome_html())
        self.pages.addTab(self.chat, "Chat")

        changes_page = QWidget()
        changes_layout = QVBoxLayout(changes_page)
        changes_layout.setContentsMargins(2, 8, 2, 2)
        self.changes_summary = QLabel("No proposed changes. Agent mode keeps all edits pending until you approve them.")
        self.changes_summary.setObjectName("mutedHint")
        self.changes_summary.setWordWrap(True)
        changes_layout.addWidget(self.changes_summary)
        review_all = QPushButton("Review All Changes…")
        review_all.setObjectName("primaryButton")
        review_all.clicked.connect(self.review_all)
        changes_layout.addWidget(review_all)
        self.pending_list = QListWidget()
        self.pending_list.setObjectName("agentChangeList")
        self.pending_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.pending_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pending_list.setMinimumWidth(0)
        self.pending_list.verticalScrollBar().setObjectName("assistantChangesScrollBar")
        self.pending_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.pending_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.pending_list.customContextMenuRequested.connect(self._pending_context_menu)
        self.pending_list.itemDoubleClicked.connect(lambda _item: self.preview_selected())
        changes_layout.addWidget(self.pending_list, 1)
        review_hint = QLabel("Double-click a file proposal to review its diff. Right-click selected proposals to review, accept or decline.")
        review_hint.setObjectName("mutedHint")
        review_hint.setWordWrap(True)
        changes_layout.addWidget(review_hint)
        self.pages.addTab(changes_page, "Changes · 0")
        root.addWidget(self.pages, 1)

        composer = QFrame()
        composer.setObjectName("assistantComposer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(9, 8, 9, 8)
        composer_layout.setSpacing(7)
        context_row = QHBoxLayout()
        context_caption = QLabel("CONTEXT")
        context_caption.setObjectName("sectionEyebrow")
        self.context_summary = QLabel("Workspace files · Active file included")
        self.context_summary.setObjectName("contextSummary")
        self.context_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        context_row.addWidget(context_caption)
        context_row.addWidget(self.context_summary, 1)
        composer_layout.addLayout(context_row)
        self.prompt = QPlainTextEdit()
        self.prompt.setObjectName("assistantPrompt")
        self.prompt.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # A coding prompt wraps to the available editor width; it should never
        # introduce a horizontal scrollbar that steals room from the composer.
        self.prompt.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.prompt.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.prompt.setMinimumWidth(0)
        self.prompt.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.prompt.setPlaceholderText("Ask a question or describe a coding task…  (Ctrl+Enter to send)")
        self.prompt.setMinimumHeight(68)
        self.prompt.setMaximumHeight(132)
        self.prompt.installEventFilter(self)
        composer_layout.addWidget(self.prompt)
        focus_row = QHBoxLayout()
        focus_caption = QLabel("FOCUS")
        focus_caption.setObjectName("sectionEyebrow")
        self.scope_picker = QComboBox()
        self.scope_picker.setObjectName("focusPicker")
        self.scope_picker.addItem("GDScript & Godot", "gdscript")
        self.scope_picker.addItem("OpenGDS core", "opengds")
        self.scope_picker.addItem("General coding", "general")
        saved_scope = str(self.settings.value("ai/scope", "gdscript"))
        scope_index = self.scope_picker.findData(saved_scope)
        self.scope_picker.setCurrentIndex(max(0, scope_index))
        self.scope_picker.setToolTip("Restricts the assistant's file context and coding guidance to the selected domain.")
        self.scope_picker.currentIndexChanged.connect(self._scope_changed)
        focus_row.addWidget(focus_caption)
        focus_row.addWidget(self.scope_picker, 1)
        composer_layout.addLayout(focus_row)

        mode_row = QHBoxLayout()
        self.mode_picker = QComboBox()
        self.mode_picker.addItem("Ask", "ask")
        self.mode_picker.addItem("Agent", "agent")
        self.mode_picker.setCurrentIndex(1 if self.settings.value("ai/mode", "agent") == "agent" else 0)
        self.mode_picker.setToolTip("Ask is read-only. Agent can propose edits and commands for your approval.")
        self.include_current = QPushButton("Active file")
        self.include_current.setObjectName("contextChip")
        self.include_current.setCheckable(True)
        self.include_current.setChecked(True)
        self.include_current.setToolTip("Include the active editor buffer in the prompt context sent to the selected provider.")
        self.include_current.toggled.connect(self._update_context_summary)
        self.send_button = QPushButton("Send  ↗")
        self.send_button.setObjectName("primaryButton")
        self.send_button.clicked.connect(self.send_prompt)
        self.task_picker = QComboBox()
        self.task_picker.setObjectName("taskPicker")
        self.task_picker.addItem("Task: Custom", "")
        self.task_picker.addItem("Explain / explore", "Explain the relevant code and architecture. Focus on a clear explanation; do not propose changes unless I ask.")
        self.task_picker.addItem("Fix a bug", "Investigate the reported bug, identify its root cause, and propose the smallest robust fix with regression tests.")
        self.task_picker.addItem("Refactor safely", "Refactor only where it improves clarity or maintainability. Preserve existing behavior and add or update tests.")
        self.task_picker.addItem("Add tests", "Design and propose focused automated tests for the requested behavior, including edge cases and failure paths.")
        self.task_picker.addItem("Review security", "Review the relevant code for security issues. Rank findings by severity and propose precise, testable remediations.")
        self.task_picker.addItem("Document code", "Improve the documentation for the requested code or feature, including usage examples and limitations.")
        self.task_picker.addItem("Review GDScript", "Review the selected GDScript for Godot 4 correctness, typed GDScript conventions, signal/lifecycle mistakes, performance issues, and maintainability. Report findings by severity with file and line references; do not invent APIs.")
        self.task_picker.addItem("Debug a Godot scene", "Trace the scene/node/resource interactions relevant to the reported issue. Inspect project.godot, relevant .tscn/.tres files and scripts. Explain the likely root cause, then propose the smallest safe fix and a reproducible validation step.")
        self.task_picker.addItem("Debug OpenGDS core", "Investigate the OpenGDS compiler/decompiler or IDE integration path. Trace the relevant implementation and tests, identify the root cause, propose a minimal regression-tested fix, and preserve the GDSC format and CLI compatibility.")
        mode_row.addWidget(self.mode_picker)
        mode_row.addWidget(self.task_picker, 1)
        composer_layout.addLayout(mode_row)
        action_row = QHBoxLayout()
        action_row.addWidget(self.include_current)
        self.include_selection = QPushButton("Selection")
        self.include_selection.setObjectName("contextChip")
        self.include_selection.setCheckable(True)
        self.include_selection.setChecked(False)
        self.include_selection.setToolTip("Send only the selected editor text instead of the full active file.")
        self.include_selection.toggled.connect(self._update_context_summary)
        action_row.addWidget(self.include_selection)
        self.context_options = QToolButton()
        self.context_options.setText("Context ▾")
        self.context_options.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        context_menu = QMenu(self)
        self.include_workspace_map_action = context_menu.addAction("Include workspace file map")
        self.include_workspace_map_action.setCheckable(True)
        self.include_workspace_map_action.setChecked(bool(self.settings.value("ai/include_workspace_map", True) == "true"))
        self.include_instructions_action = context_menu.addAction("Include project instructions")
        self.include_instructions_action.setCheckable(True)
        self.include_instructions_action.setChecked(_setting_enabled(self.settings.value("ai/include_project_instructions", False)))
        self.include_selection_action = context_menu.addAction("Include editor selection")
        self.include_selection_action.setCheckable(True)
        self.include_selection_action.setChecked(self.include_selection.isChecked())
        self.include_selection_action.toggled.connect(self.include_selection.setChecked)
        self.include_selection.toggled.connect(self.include_selection_action.setChecked)
        self.use_embeddings_action = context_menu.addAction("Use semantic embeddings for workspace retrieval")
        self.use_embeddings_action.setCheckable(True)
        self.use_embeddings_action.setChecked(_setting_enabled(self.settings.value("ai/use_embeddings", False)))
        context_menu.addSeparator()
        context_menu.addAction("Configure provider, chat and embeddings models…", self.configure)
        context_menu.addAction("Clear conversation history", self.clear_chat)
        self.context_options.setMenu(context_menu)
        context_menu.triggered.connect(lambda _action: self._save_context_options())
        action_row.addWidget(self.context_options)
        action_row.addStretch(1)
        action_row.addWidget(self.send_button)
        composer_layout.addLayout(action_row)
        self.mode_hint = QLabel()
        self.mode_hint.setObjectName("mutedHint")
        self.mode_hint.setWordWrap(True)
        composer_layout.addWidget(self.mode_hint)
        self.mode_picker.currentIndexChanged.connect(self._update_mode_hint)
        self._update_mode_hint()
        self._scope_changed()
        # The composer has several rows of controls. Give it a bounded viewport
        # so short AI panes can scroll the controls instead of compressing them
        # into overlapping rows. Chat remains independently scrollable above.
        self.composer_layout = composer_layout
        self.composer_scroll = QScrollArea(self)
        self.composer_scroll.setObjectName("assistantComposerScroll")
        self.composer_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.composer_scroll.setWidgetResizable(True)
        self.composer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Keep a clearly visible vertical control on the composer viewport too.
        # The viewport scrolls the context/focus/task/action rows when the dock
        # is short; the prompt retains its own internal vertical scrolling.
        self.composer_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.composer_scroll.setMinimumSize(0, 112)
        self.composer_scroll.setMinimumWidth(0)
        self.composer_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.composer_scroll.verticalScrollBar().setObjectName("assistantComposerScrollBar")
        self.composer_scroll.setMaximumHeight(238)
        self.composer_scroll.setWidget(composer)
        root.addWidget(self.composer_scroll, 0)

        footer = QLabel("Your API key stays on this device. Agent edits and commands always require your approval.")
        footer.setObjectName("mutedHint")
        footer.setWordWrap(True)
        self.footer = footer
        root.addWidget(footer, 0)
        self._refresh_provider_label()
        self._apply_responsive_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def _apply_responsive_layout(self):
        """Switch to a compact, scroll-safe composer at small pane sizes."""
        width = max(0, self.width())
        height = max(0, self.height())
        compact = height < 520
        very_compact = height < 390
        ultra_compact = height < 285
        narrow = width < 370

        self._root_layout.setContentsMargins(3 if ultra_compact else (6 if compact else 8),
                                             3 if ultra_compact else (5 if compact else 7),
                                             3 if ultra_compact else (6 if compact else 8),
                                             3 if ultra_compact else (6 if compact else 8))
        self._root_layout.setSpacing(3 if ultra_compact else (5 if compact else 7))
        self.pages.setMinimumHeight(58 if ultra_compact else (68 if very_compact else (92 if compact else 120)))
        self.composer_scroll.setMinimumHeight(68 if ultra_compact else (80 if very_compact else (124 if compact else 148)))
        self.composer_scroll.setMaximumHeight(112 if ultra_compact else (136 if compact else 238))
        self.composer_layout.setContentsMargins(3 if ultra_compact else (6 if compact else 9),
                                                3 if ultra_compact else (5 if compact else 8),
                                                3 if ultra_compact else (6 if compact else 9),
                                                3 if ultra_compact else (5 if compact else 8))
        self.composer_layout.setSpacing(3 if ultra_compact else (4 if compact else 7))
        self.prompt.setMinimumHeight(38 if ultra_compact else (44 if compact else 68))
        self.prompt.setMaximumHeight(58 if ultra_compact else (72 if compact else 132))
        self.mode_hint.setVisible(not compact)
        self.footer.setVisible(not compact)
        self.provider_label.setVisible(not ultra_compact)
        self.include_selection.setVisible(not narrow)
        self.context_options.setText("⋯" if narrow else "Context ▾")
        self.context_options.setToolTip("Context options, including editor selection")
        self.context_summary.setMinimumWidth(0)
        self.provider_label.setMinimumWidth(0)
        self.scope_picker.setMinimumWidth(0)
        self.task_picker.setMinimumWidth(0)
        self.mode_picker.setMinimumWidth(0)
        self.send_button.setMinimumWidth(58 if narrow else 68)

    def _welcome_html(self):
        return (
            "<div style='padding:18px 12px;color:#aeb8c5'>"
            "<div style='font-size:19px;font-weight:650;color:#e7edf5'>What are we building?</div>"
            "<p>Use <b>Ask</b> for read-only explanations and diagnostics, or <b>Agent</b> to let the assistant inspect the workspace and propose changes.</p>"
            "<p>Every file edit or command appears in <b>Changes</b> for review. Nothing is applied automatically.</p>"
            "<div style='margin-top:18px;padding:12px;border:1px solid #344052;border-radius:9px;background:#202938'>"
            "<b style='color:#9fc2ff'>Start with a free model</b><br>"
            "Try OpenRouter Free, Gemini Free Tier, Groq Free Tier, or a local Ollama model. Each remote provider uses your own account and API key."
            "</div></div>"
        )

    def _update_mode_hint(self, *_args):
        mode = str(self.mode_picker.currentData() or "agent")
        if mode == "ask":
            self.mode_hint.setText("ASK MODE  ·  Read-only inspection and explanations. The assistant cannot propose file edits or commands.")
        else:
            self.mode_hint.setText("AGENT MODE  ·  Can inspect the workspace and propose file edits or commands. Nothing is applied until you approve it.")

    def eventFilter(self, obj, event):
        if obj is self.prompt and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.send_prompt()
                return True
        return super().eventFilter(obj, event)

    def _config(self) -> AgentConfig:
        provider = str(self.settings.value("ai/provider", "OpenRouter Free"))
        preset = PROVIDERS.get(provider, PROVIDERS["OpenRouter Free"])
        key = self.credentials.get(provider)
        if not preset.get("requires_api_key", True) and provider == "Ollama Local":
            key = key or "ollama"
        return AgentConfig(
            provider=provider,
            model=str(self.settings.value("ai/model", preset.get("default_model", ""))),
            base_url=str(self.settings.value("ai/base_url", preset["base_url"])),
            api_key=key,
            timeout=int(self.settings.value("ai/timeout", 120)),
            agent_mode=str(self.mode_picker.currentData() or self.settings.value("ai/mode", "agent")),
            scope=str(self.scope_picker.currentData() or self.settings.value("ai/scope", "gdscript")),
            use_embeddings=_setting_enabled(self.settings.value("ai/use_embeddings", False)),
            embedding_model=str(self.settings.value("ai/embedding_model", "")).strip(),
            embeddings_url=str(self.settings.value("ai/embeddings_url", "")).strip(),
        )

    def _scope_changed(self, *_args):
        scope = str(self.scope_picker.currentData() or "gdscript")
        self.settings.setValue("ai/scope", scope)
        # Change the active tool scope without dropping safety-reviewed proposals.
        # A scope switch starts a fresh chat history, but pending actions remain
        # available in the Changes view until accepted or declined.
        if self.engine:
            self.engine.config.scope = scope
            self.engine.history.clear()
        if hasattr(self, "transcript"):
            self.transcript.clear()
            self._streaming_text = ""
            if hasattr(self, "chat"):
                self.chat.setHtml(self._welcome_html())
            if hasattr(self, "pending_list"):
                self.refresh_pending()
        labels = {"gdscript": "GDScript & Godot", "opengds": "OpenGDS core", "general": "General coding"}
        self.mode_hint.setText(f"FOCUS  ·  {labels.get(scope, 'GDScript & Godot')}  ·  File tools are scoped to this domain.")
        self._update_context_summary()

    def _refresh_provider_label(self):
        provider = str(self.settings.value("ai/provider", "OpenRouter Free"))
        preset = PROVIDERS.get(provider, PROVIDERS["OpenRouter Free"])
        model = str(self.settings.value("ai/model", preset.get("default_model", "model not set")))
        has_key = bool(self.credentials.get(provider)) or not preset.get("requires_api_key", True)
        state = preset.get("tier", "Provider")
        embeddings = "  ·  embeddings on" if _setting_enabled(self.settings.value("ai/use_embeddings", False)) else ""
        self.provider_label.setText(f"{provider}  ·  {model}  ·  {state}" + ("" if has_key else "  ·  key needed") + embeddings)

    def configure(self):
        if self.is_busy():
            QMessageBox.information(self, "AI assistant", "Wait for the current operation to finish before changing providers.")
            return
        dialog = AgentSettingsDialog(self.settings, self.credentials, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                dialog.save_values()
                self.engine = None
                self._refresh_provider_label()
                QMessageBox.information(self, "AI assistant", "Provider settings saved. Keys are stored outside the project.")
            except Exception as exc:
                QMessageBox.critical(self, "AI assistant", str(exc))

    def forget_current_key(self):
        provider = str(self.settings.value("ai/provider", "OpenRouter Free"))
        answer = QMessageBox.question(self, "Remove provider key", f"Forget the saved API key for {provider}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.credentials.set(provider, "")
            self.engine = None
            self._refresh_provider_label()

    def clear_chat(self):
        if self.is_busy():
            QMessageBox.information(self, "AI assistant", "Wait for the current operation to finish before starting a new conversation.")
            return
        self.transcript.clear()
        if self.engine:
            self.engine.history.clear()
        self.chat.setHtml(self._welcome_html())
        self.prompt.clear()
        self.refresh_pending()
        self.pages.setCurrentIndex(0)

    def set_workspace(self, workspace):
        root = Path(workspace).resolve() if workspace else None
        if root != self.engine_root:
            self.engine_root = root
            self.engine = None
            self.transcript.clear()
            self._streaming_text = ""
            self.chat.setHtml(self._welcome_html())
            self.pending_list.clear()
            self.refresh_pending()

    def _get_engine(self) -> AgentEngine:
        root = self.workspace_getter()
        if not root:
            raise RuntimeError("Open a project or workspace before using the AI assistant.")
        root = Path(root).resolve()
        config = self._config()
        if self.engine is None or self.engine_root != root:
            backend = self.backend_getter() if self.backend_getter else None
            self.engine = AgentEngine(root, config, credential_store=self.credentials, backend=backend)
            self.engine_root = root
        else:
            self.engine.config = config
        return self.engine

    def _save_context_options(self):
        self.settings.setValue("ai/include_workspace_map", "true" if self.include_workspace_map_action.isChecked() else "false")
        self.settings.setValue("ai/include_project_instructions", "true" if self.include_instructions_action.isChecked() else "false")
        self.settings.setValue("ai/use_embeddings", "true" if self.use_embeddings_action.isChecked() else "false")
        if self.use_embeddings_action.isChecked() and not str(self.settings.value("ai/embedding_model", "")).strip():
            self.use_embeddings_action.setChecked(False)
            self.settings.setValue("ai/use_embeddings", "false")
            QMessageBox.information(self, "Semantic retrieval", "Configure an embeddings model in AI provider settings before enabling semantic retrieval.")
        if self.engine:
            self.engine.config.use_embeddings = self.use_embeddings_action.isChecked()
            self.engine.config.embedding_model = str(self.settings.value("ai/embedding_model", "")).strip()
            self.engine.config.embeddings_url = str(self.settings.value("ai/embeddings_url", "")).strip()
            self.engine._embedding_cache.clear()
        self._update_context_summary()

    def _update_context_summary(self, *_args):
        workspace = self.workspace_getter()
        workspace_name = Path(workspace).name if workspace else "No workspace"
        editor = self.editor_getter()
        pieces = []
        if self.include_current.isChecked() and editor:
            path = getattr(editor, "file_path", None)
            file_name = Path(path).name if path else "Untitled buffer"
            included = True
            if path and workspace:
                try:
                    relative = Path(path).resolve().relative_to(Path(workspace).resolve()).as_posix()
                    included = scope_allows(str(self.scope_picker.currentData() or "gdscript"), relative)
                except (ValueError, OSError, TypeError):
                    included = False
            elif path and not workspace:
                included = False
            pieces.append(f"{file_name} {'included' if included else 'excluded by focus'}")
        else:
            pieces.append("Active file excluded")
        if self.include_selection.isChecked():
            pieces.append("selection mode")
        if self.include_workspace_map_action.isChecked():
            pieces.append("workspace map")
        if self.include_instructions_action.isChecked():
            pieces.append("project instructions")
        if _setting_enabled(self.settings.value("ai/use_embeddings", False)):
            pieces.append("semantic embeddings")
        self.context_summary.setText(f"{workspace_name}  ·  {' + '.join(pieces)}  ·  {self.scope_picker.currentText()}")

    def _editor_context(self) -> str:
        chunks = []
        editor = self.editor_getter()
        if self.include_current.isChecked() and editor:
            path = getattr(editor, "file_path", None)
            label = "Current unsaved editor buffer"
            include = True
            if path:
                try:
                    workspace = Path(self.workspace_getter()).resolve()
                    relative = Path(path).resolve().relative_to(workspace).as_posix()
                    if not scope_allows(str(self.scope_picker.currentData() or "gdscript"), relative):
                        include = False
                    label = "Current file: " + relative
                except (ValueError, OSError, TypeError):
                    include = False
            if include:
                if self.include_selection.isChecked() and editor.textCursor().hasSelection():
                    body = editor.textCursor().selectedText().replace("\u2029", "\n")
                    label = "Selected editor text from " + label
                else:
                    body = editor.toPlainText()
                chunks.append(label + "\n" + body[:200_000])
        workspace = self.workspace_getter()
        if workspace and self.engine and self.include_workspace_map_action.isChecked():
            try:
                files = self.engine._project_files(200)
                chunks.append("WORKSPACE FILE MAP (paths only)\n" + "\n".join(files))
            except Exception:
                pass
        if workspace and self.include_instructions_action.isChecked():
            candidates = ("AGENTS.md", "README.md", "GEMINI.md", ".github/copilot-instructions.md")
            for relative in candidates:
                try:
                    if self.engine:
                        path = self.engine._safe_path(relative)
                    else:
                        path = (Path(workspace) / relative).resolve()
                        root = Path(workspace).resolve()
                        if path != root and root not in path.parents:
                            continue
                    if path.is_file() and path.stat().st_size <= 24_000:
                        chunks.append(f"PROJECT INSTRUCTIONS: {relative}\n" + path.read_text(encoding="utf-8-sig")[:24_000])
                except (OSError, UnicodeError):
                    continue
        return "\n\n--- CONTEXT SOURCE ---\n\n".join(chunks)

    def _render_chat(self, *, preserve_scroll: bool = False):
        bar = self.chat.verticalScrollBar()
        old_value = bar.value()
        was_at_bottom = old_value >= bar.maximum() - 4
        blocks = []
        rows = list(self.transcript[-80:])
        if self._streaming_text:
            rows.append(("Assistant · streaming", self._streaming_text))
        for who, body in rows:
            safe_role = html.escape(who)
            safe_body = html.escape(body).replace("\r\n", "\n").replace("\r", "\n")
            safe_body = safe_body.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;").replace("\n", "<br>")
            if who == "You":
                bg, border, color = "#263b55", "#385777", "#e7f1ff"
            elif "error" in who.lower():
                bg, border, color = "#442b31", "#74414c", "#ffd8dc"
            elif "streaming" in who.lower():
                bg, border, color = "#1f3445", "#39759a", "#dceefa"
            else:
                bg, border, color = "#222b36", "#364454", "#dce5ef"
            blocks.append(
                f"<div style='margin:10px 5px;padding:11px 13px;border:1px solid {border};border-radius:10px;background:{bg};color:{color}'>"
                f"<div style='font-size:11px;font-weight:700;letter-spacing:1px;margin-bottom:6px'>{safe_role.upper()}</div>"
                f"<div style='white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.45'>{safe_body}</div></div>"
            )
        self.chat.setHtml("".join(blocks) or self._welcome_html())
        self._stream_cursor = None
        if not preserve_scroll or was_at_bottom:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(min(old_value, bar.maximum()))

    def _begin_stream_message(self):
        cursor = self.chat.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not cursor.atBlockStart():
            cursor.insertBlock()
        heading = QTextCharFormat()
        heading.setForeground(QColor("#91bfea"))
        heading.setFontWeight(QFont.Weight.Bold)
        heading.setFontPointSize(8)
        cursor.insertText("ASSISTANT · STREAMING", heading)
        cursor.insertBlock()
        body = QTextCharFormat()
        body.setForeground(QColor("#dceefa"))
        body.setFontPointSize(10)
        cursor.setCharFormat(body)
        self._stream_cursor = cursor
        self.chat.setTextCursor(cursor)

    def _flush_stream_buffer(self):
        chunk = self._stream_buffer
        self._stream_buffer = ""
        if not chunk:
            return
        bar = self.chat.verticalScrollBar()
        was_at_bottom = bar.value() >= bar.maximum() - 4
        self._streaming_text += chunk
        if self._stream_cursor is not None:
            self._stream_cursor.insertText(chunk)
            # Do not move the text cursor for every streamed batch: doing so
            # forces QTextBrowser to jump to the end and makes manual scrolling
            # feel broken while the model is responding.
            if was_at_bottom:
                bar.setValue(bar.maximum())

    def _append_message(self, role: str, text: str):
        if self._stream_timer.isActive():
            self._stream_timer.stop()
        self._flush_stream_buffer()
        self.transcript.append((role, text))
        self._streaming_text = ""
        self._stream_buffer = ""
        self._stream_cursor = None
        self._render_chat(preserve_scroll=True)

    def _append_stream_chunk(self, chunk: str):
        self._stream_buffer += str(chunk)
        if not self._stream_timer.isActive():
            self._stream_timer.start()

    def is_busy(self) -> bool:
        return bool((self.worker and self.worker.isRunning()) or
                    (self.approval_worker and self.approval_worker.isRunning()))

    def send_prompt(self):
        if self.is_busy():
            self.cancel_request()
            return
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            return
        task_instruction = str(self.task_picker.currentData() or "").strip()
        if task_instruction:
            prompt = task_instruction + "\n\nUser request:\n" + prompt
        try:
            engine = self._get_engine()
            self._update_context_summary()
            context = self._editor_context()
            provider_meta = PROVIDERS.get(engine.config.provider, {})
            if provider_meta.get("requires_api_key", True) and not engine.config.api_key:
                raise RuntimeError("Add your own provider key in ⋯ → Configure provider and model. Free-tier keys are available from the provider's signup page.")
            if not engine.config.model:
                raise RuntimeError("Select a model ID in provider settings first.")
            self.settings.setValue("ai/mode", self.mode_picker.currentData())
            engine.config.agent_mode = str(self.mode_picker.currentData() or "agent")
            engine.config.use_embeddings = _setting_enabled(self.settings.value("ai/use_embeddings", False))
            engine.config.embedding_model = str(self.settings.value("ai/embedding_model", "")).strip()
            engine.config.embeddings_url = str(self.settings.value("ai/embeddings_url", "")).strip()
            if engine.config.use_embeddings and not engine.config.embedding_model:
                raise RuntimeError("Semantic retrieval is enabled but no embeddings model is configured. Open AI settings or disable embeddings in Context.")
            if engine.config.use_embeddings and PROVIDERS.get(engine.config.provider, {}).get("protocol") == "anthropic":
                raise RuntimeError("The selected Claude/Anthropic endpoint does not expose the OpenAI-compatible embeddings API. Choose another provider or disable embeddings.")
        except Exception as exc:
            QMessageBox.warning(self, "AI assistant", str(exc))
            return
        self.prompt.clear()
        self._pending_before_request = {action.action_id for action in engine.pending_actions()}
        self._request_requires_changes = (engine.config.agent_mode == "agent" and requires_change_proposal(prompt))
        self._append_message("You", prompt)
        self.pages.setCurrentIndex(0)
        self._streaming_text = ""
        self._stream_buffer = ""
        self._begin_stream_message()
        self.send_button.setEnabled(True)
        self.send_button.setText("Cancel  ×")
        self.send_button.setToolTip("Cancel the in-flight AI request")
        self.send_button.setObjectName("cancelButton")
        self.send_button.style().unpolish(self.send_button)
        self.send_button.style().polish(self.send_button)
        self.scope_picker.setEnabled(False)
        self.mode_picker.setEnabled(False)
        self.task_picker.setEnabled(False)
        self.worker = _AgentWorker(engine, prompt, context, self)
        self.worker.streamChunk.connect(self._append_stream_chunk)
        self.worker.finishedText.connect(self._worker_finished)
        self.worker.failedText.connect(self._worker_failed)
        self.worker.cancelled.connect(self._worker_cancelled)
        self.worker.finished.connect(self._worker_stopped)
        self.worker.start()

    def cancel_request(self):
        if self.worker and self.worker.isRunning():
            self.send_button.setEnabled(False)
            self.send_button.setText("Cancelling…")
            self.worker.cancel()

    def _worker_finished(self, answer: str):
        self._append_message("Assistant", answer)
        current_ids = {action.action_id for action in self.engine.pending_actions()} if self.engine else set()
        new_ids = current_ids - self._pending_before_request
        approval_language = bool(re.search(r"\b(approve|accept)\b.{0,100}\b(change|proposal|patch|edit)\b", answer, re.IGNORECASE))
        if not current_ids and (self._request_requires_changes or approval_language):
            self._append_message("AI change status",
                "No reviewable change was created for this response. Nothing was written to disk, and there is nothing to approve. "
                "Ask the agent to inspect the current file and call the edit tool to prepare a complete-file proposal.")
        self.refresh_pending()
        self._open_new_proposal_files()
        if new_ids:
            # Surface pending edits immediately rather than leaving the user
            # on a completed chat response with the review tab hidden.
            self.pages.setCurrentIndex(1)
        log_event("AI", logging.INFO, "AI assistant completed a streamed response")

    def _open_new_proposal_files(self):
        if not self.engine or not self.open_path:
            return
        actions = [action for action in self.engine.pending_actions()
                   if action.action_id not in self._pending_before_request and action.kind == "file"]
        root = self.workspace_getter()
        if not root:
            return
        root_path = Path(root).resolve()
        owner = self.parent()
        opened = []
        for action in actions[:12]:
            try:
                target = (root_path / action.path).resolve()
                if root_path not in target.parents:
                    continue
                if target.is_file():
                    self.open_path(target)
                elif action.kind == "file" and action.operation == "write" and hasattr(owner, "open_agent_proposal_preview"):
                    owner.open_agent_proposal_preview(target, action.content)
                else:
                    continue
                opened.append(target)
            except Exception as exc:
                log_event("AI", logging.WARNING, f"Could not open proposal preview {action.path}: {exc}")
        if opened:
            self.refresh_inline_decorations()

    def _worker_failed(self, message: str):
        # Preserve any useful streamed partial output before surfacing the error.
        if self._stream_timer.isActive():
            self._stream_timer.stop()
        self._flush_stream_buffer()
        partial = self._streaming_text.strip()
        rendered = (partial + "\n\nRequest failed: " + str(message)) if partial else str(message)
        self._append_message("Assistant error", rendered)
        # A tool may already have queued an approval action before a later
        # provider round fails. Never leave that real proposal hidden.
        self.refresh_pending()
        self._open_new_proposal_files()
        current_ids = {action.action_id for action in self.engine.pending_actions()} if self.engine else set()
        if current_ids - self._pending_before_request:
            self.pages.setCurrentIndex(1)
        log_event("AI", logging.ERROR, f"AI assistant request failed: {message}")

    def _worker_cancelled(self):
        if self._stream_timer.isActive():
            self._stream_timer.stop()
        self._flush_stream_buffer()
        partial = self._streaming_text.strip()
        rendered = (partial + "\n\n[Request cancelled by user.] ").strip() if partial else "Request cancelled by user."
        self._append_message("Assistant", rendered)
        # Cancellation can happen after an edit tool returned successfully;
        # keep its approval request visible and reviewable.
        self.refresh_pending()
        self._open_new_proposal_files()
        current_ids = {action.action_id for action in self.engine.pending_actions()} if self.engine else set()
        if current_ids - self._pending_before_request:
            self.pages.setCurrentIndex(1)
        log_event("AI", logging.INFO, "AI assistant request cancelled by user")

    def _worker_stopped(self):
        if self._stream_timer.isActive():
            self._stream_timer.stop()
        if self._stream_buffer:
            self._flush_stream_buffer()
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()
        self.send_button.setEnabled(True)
        self.send_button.setText("Send  ↗")
        self.send_button.setToolTip("")
        self.send_button.setObjectName("primaryButton")
        self.send_button.style().unpolish(self.send_button)
        self.send_button.style().polish(self.send_button)
        self.scope_picker.setEnabled(True)
        self.mode_picker.setEnabled(True)
        self.task_picker.setEnabled(True)
        self._pending_before_request = set()
        self._request_requires_changes = False

    def refresh_pending(self):
        self.pending_list.clear()
        actions = self.engine.pending_actions() if self.engine else []
        for action in actions:
            if action.kind == "file":
                verb = "DECOMPILE" if action.metadata.get("tool") == "OpenGDS decompiler" else action.operation.upper()
                label = f"FILE CHANGE  ·  {verb}\n{action.path}\n{action.reason}"
                color = "#82b8ed"
            elif action.kind == "opengds":
                label = f"OPENGDS COMPILE  ·  {action.path}\n{action.metadata.get('source_path', '')}\n{action.reason}"
                color = "#8bc7a2"
            else:
                label = f"COMMAND PROPOSAL\n{' '.join(action.argv)}\n{action.reason}"
                color = "#e5b567"
            item = QListWidgetItem(label)
            item.setForeground(QColor(color))
            item.setData(Qt.ItemDataRole.UserRole, action.action_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setToolTip(label)
            self.pending_list.addItem(item)
        count = len(actions)
        self.pending_badge.setText(f"{count} pending" if count else "0 changes")
        self.pending_badge.setEnabled(count > 0)
        self.pending_badge.setToolTip(f"Open {count} pending AI proposal(s)" if count else "No pending AI proposals")
        self.pages.setTabText(1, f"Changes · {count}")
        if count:
            self.changes_summary.setText(f"{count} proposed action(s) across {len({a.path for a in actions if a.path})} file(s). Review the complete change set before accepting.")
        else:
            self.changes_summary.setText("No pending changes. Agent edits, decompiles and compile operations appear here before they are applied.")
        self.refresh_inline_decorations()

    def refresh_inline_decorations(self):
        owner = self.parent()
        editors = list(getattr(owner, "editors", {}).values()) if owner is not None else []
        active = self.editor_getter()
        if active is not None and active not in editors:
            editors.append(active)
        workspace = self.workspace_getter()
        if not workspace:
            for editor in editors:
                editor.clear_ai_diff()
                editor._ai_proposal_pending = False
                if owner is not None and hasattr(owner, "mark_tab"):
                    owner.mark_tab(editor)
            return
        pending_by_path = {}
        for action in (self.engine.pending_actions() if self.engine else []):
            if action.kind == "file":
                pending_by_path[action.path] = action
        for editor in editors:
            path = getattr(editor, "file_path", None)
            if not path:
                editor.clear_ai_diff()
                editor._ai_proposal_pending = False
                if owner is not None and hasattr(owner, "mark_tab"):
                    owner.mark_tab(editor)
                continue
            try:
                relative = Path(path).resolve().relative_to(Path(workspace).resolve()).as_posix()
            except (ValueError, OSError):
                editor.clear_ai_diff()
                editor._ai_proposal_pending = False
                if owner is not None and hasattr(owner, "mark_tab"):
                    owner.mark_tab(editor)
                continue
            proposal = pending_by_path.get(relative)
            editor._ai_proposal_pending = bool(proposal)
            if proposal:
                if getattr(editor, "_ai_proposal_placeholder", False):
                    editor.set_ai_diff_preview(proposal.content, path=relative, base_text="")
                else:
                    editor.set_ai_diff_preview("" if proposal.operation == "delete" else proposal.content, path=relative)
            else:
                editor.clear_ai_diff()
            if owner is not None and hasattr(owner, "mark_tab"):
                owner.mark_tab(editor)

    def _pending_context_menu(self, point):
        if not self.pending_list.itemAt(point):
            return
        menu = QMenu(self)
        menu.addAction("Review selected in Change Review…", self.preview_selected)
        menu.addSeparator()
        menu.addAction("Accept selected proposals", self.accept_selected)
        menu.addAction("Decline selected proposals", self.reject_selected)
        menu.exec(self.pending_list.mapToGlobal(point))

    def _selected_ids(self):
        ids = []
        for index in range(self.pending_list.count()):
            item = self.pending_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                ids.append(item.data(Qt.ItemDataRole.UserRole))
        if not ids and self.pending_list.currentItem():
            ids.append(self.pending_list.currentItem().data(Qt.ItemDataRole.UserRole))
        return [value for value in ids if value]

    def review_all(self, selected_ids=None):
        if not self.engine:
            return
        actions = self.engine.pending_actions()
        if not actions:
            QMessageBox.information(self, "Review Agent Changes", "There are no pending proposals.")
            return
        dialog = AgentChangeReviewDialog(self.engine, actions, selected_ids, self)
        def approve_from_review(ids):
            if self._approve_ids(ids, review_dialog=dialog):
                dialog.set_approving(True)
        def decline_from_review(ids):
            if self._reject_ids(ids):
                dialog.resolve_approvals([(action_id, "Declined by user.", False) for action_id in ids])
                self.refresh_pending()
        dialog.acceptRequested.connect(approve_from_review)
        dialog.declineRequested.connect(decline_from_review)
        dialog.exec()
        self._active_review_dialog = None

    def preview_selected(self):
        ids = self._selected_ids()
        if not ids:
            QMessageBox.information(self, "Review Agent Changes", "Select one or more proposals first.")
            return
        self.review_all(ids)

    def _approve_ids(self, ids, *, review_dialog=None):
        if not self.engine or not ids or self.is_busy():
            return False
        actions = {item.action_id: item for item in self.engine.pending_actions()}
        selected_actions = [actions[item] for item in ids if item in actions]
        owner = self.parent()
        open_editors = getattr(owner, "editors", {}).values() if owner is not None else []
        dirty_paths = {Path(editor.file_path).resolve() for editor in open_editors
                       if getattr(editor, "file_path", None) and editor.document().isModified()}
        workspace_root = Path(self.workspace_getter()).resolve()
        if any(action.kind == "file" and (workspace_root / action.path).resolve() in dirty_paths
               for action in selected_actions):
            QMessageBox.warning(self, "Unsaved editor buffer", "Save every affected editor buffer before accepting these AI proposals. This prevents approved disk changes from replacing unsaved editor text.")
            return False
        commands = [action for action in selected_actions if action.kind == "command"]
        compile_actions = [action for action in selected_actions if action.kind == "opengds"]
        if compile_actions:
            summary = "The OpenGDS compiler will run for these outputs:\n\n" + "\n".join(
                f"• {a.metadata.get('source_path', '')} → {a.path}" for a in compile_actions)
            answer = QMessageBox.warning(self, "Approve OpenGDS compilation", summary + "\n\nExisting outputs may be replaced only if the source and output have not changed since proposal. Continue?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
        self._approval_paths = {action.action_id: action.path for action in selected_actions if action.kind in {"file", "opengds"}}
        if commands:
            summary = "The following commands will run in the workspace without a shell:\n\n" + "\n".join(
                f"• {' '.join(action.argv)}\n  Working directory: {action.cwd}" for action in commands)
            summary += "\n\nA command can access resources outside the workspace. Approve only commands you understand and trust."
            answer = QMessageBox.warning(self, "Approve command execution", summary + "\n\nRun the selected approved actions?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
        self.send_button.setEnabled(False)
        for button in self.approval_buttons:
            button.setEnabled(False)
        self._active_review_dialog = review_dialog
        self.approval_worker = _ApprovalWorker(self.engine, list(ids), self)
        self.approval_worker.finishedResults.connect(self._approval_finished)
        self.approval_worker.finished.connect(self._approval_thread_stopped)
        self.approval_worker.start()
        return True

    def _approval_thread_stopped(self):
        worker = self.approval_worker
        self.approval_worker = None
        if worker is not None:
            worker.deleteLater()

    def _approval_finished(self, outcomes):
        for _action_id, message, failed in outcomes:
            self._append_message("Approval error" if failed else "Applied", message)
        changed_paths = [self._approval_paths.pop(action_id, "") for action_id, _message, failed in outcomes if not failed]
        for action_id, _message, _failed in outcomes:
            self._approval_paths.pop(action_id, None)
        review_dialog = self._active_review_dialog
        if review_dialog is not None:
            review_dialog.resolve_approvals(outcomes)
            if not any(failed for _action_id, _message, failed in outcomes):
                review_dialog.accept()
        owner = self.parent()
        if changed_paths and owner is not None and hasattr(owner, "reload_agent_files"):
            owner.reload_agent_files(changed_paths)
        self.refresh_pending()
        self.send_button.setEnabled(True)
        for button in self.approval_buttons:
            button.setEnabled(True)
        log_event("AI", logging.INFO, f"Agent approval batch completed: {len(outcomes)} action(s)")

    def accept_selected(self):
        self._approve_ids(self._selected_ids())

    def accept_all(self):
        if self.engine:
            ids = [action.action_id for action in self.engine.pending_actions()]
            self._approve_ids(ids)

    def _reject_ids(self, ids):
        if not self.engine or not ids or self.is_busy():
            return False
        actions = {item.action_id: item for item in self.engine.pending_actions()}
        preview_paths = [actions[action_id].path for action_id in ids
                         if action_id in actions and actions[action_id].kind == "file"
                         and actions[action_id].operation == "write"]
        for action_id in ids:
            self.engine.reject(action_id)
        owner = self.parent()
        if owner is not None and hasattr(owner, "close_agent_proposal_previews"):
            owner.close_agent_proposal_previews(preview_paths)
        self.refresh_pending()
        return True

    def reject_selected(self):
        self._reject_ids(self._selected_ids())

    def reject_all(self):
        if self.engine and not self.is_busy():
            answer = QMessageBox.question(self, "Decline all changes", "Decline every pending file and command proposal?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self.engine.reject_all()
                self.refresh_pending()
