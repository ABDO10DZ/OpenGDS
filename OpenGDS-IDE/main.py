from __future__ import annotations
import json, os, shutil, sys, logging, html, subprocess, configparser
from pathlib import Path

# Give a useful setup message when users invoke `python main.py` before installing
# the GUI dependency. The Windows/Linux launchers create an isolated venv and
# install requirements automatically; this guard prevents a confusing traceback.
try:
    import PySide6  # noqa: F401
except ModuleNotFoundError as _qt_import_error:
    if (_qt_import_error.name or "").split(".", 1)[0] == "PySide6":
        _message = (
            "\nOpenGDS - IDE cannot start because PySide6 is not installed.\n\n"
            "Recommended: run the launcher from this folder; it creates .venv and\n"
            "installs the required packages automatically:\n"
            "  Windows:  launch_windows.bat\n"
            "  Linux/macOS: ./launch_linux.sh\n\n"
            "Manual setup: python -m pip install -r requirements.txt\n"
            "Then run:    python main.py\n"
        )
        print(_message, file=sys.stderr)
        raise SystemExit(2) from None
    raise

from PySide6.QtCore import Qt, QDir, QObject, QProcess, QSettings, QTimer, QUrl, QModelIndex, Signal, QThread, qInstallMessageHandler
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QFont, QTextCursor, QIcon, QBrush, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTreeView,
    QFileSystemModel, QTabWidget, QPlainTextEdit, QDockWidget, QToolBar,
    QStatusBar, QFileDialog, QMessageBox, QInputDialog, QDialog, QFormLayout,
    QLineEdit, QCheckBox, QSpinBox, QComboBox, QPushButton, QDialogButtonBox,
    QListWidget, QListWidgetItem, QMenu, QToolButton, QLabel, QTextEdit
)

from project_manager import create_project, load_project, save_project, History, workspace_from_directory
from backend import OpenGDSBackend, BackendError
from editor import CodeEditor
from language_service import extract_symbols, analyze_gdscript, project_symbols
from lsp_client import GodotLanguageClient
from dap_client import GodotDebugClient
from logging_system import CATEGORY_COLORS, configure_logging, log_directory, log_event, install_exception_hooks
from project_ops import compile_project, decompile_project, validate_project_with_godot as godot_validate_project, godot_check_command, OperationSummary, iter_project_files
from archive_tools import read_pck, pck_report, extract_pck, zip_report, extract_zip, ArchiveError, looks_like_pck_or_executable
from app_info import APP_NAME, VERSION, DEVELOPER

DARK = """
QMainWindow,QWidget { background:#1e1e1e; color:#d4d4d4; }
QMenuBar,QMenu,QToolBar { background:#252526; color:#ddd; border:0; }
QMenu::item:selected { background:#094771; }
QTreeView,QListWidget,QPlainTextEdit,QTextEdit,QLineEdit,QComboBox,QSpinBox { background:#181818; color:#ddd; border:1px solid #3c3c3c; selection-background-color:#264f78; }
QTabWidget::pane { border:1px solid #333; } QTabBar::tab { background:#2d2d2d; padding:8px 14px; } QTabBar::tab:selected { background:#1e1e1e; border-top:2px solid #007acc; }
QPushButton { background:#333; border:1px solid #555; padding:6px 12px; } QPushButton:hover { background:#444; }
QDockWidget::title { background:#252526; padding:6px; }
QStatusBar { background:#007acc; color:white; }
"""
LIGHT = """
QMainWindow,QWidget { background:#f5f5f5; color:#222; }
QMenuBar,QMenu,QToolBar { background:#ededed; color:#222; border:0; }
QTreeView,QListWidget,QPlainTextEdit,QTextEdit,QLineEdit,QComboBox,QSpinBox { background:white; color:#222; border:1px solid #bbb; selection-background-color:#cce5ff; }
QTabWidget::pane { border:1px solid #bbb; } QTabBar::tab { background:#e5e5e5; padding:8px 14px; } QTabBar::tab:selected { background:white; border-top:2px solid #007acc; }
QPushButton { background:#eee; border:1px solid #aaa; padding:6px 12px; } QDockWidget::title { background:#e5e5e5; padding:6px; }
QStatusBar { background:#007acc; color:white; }
"""


class LogSignal(QObject):
    record = Signal(object)


class QtLogHandler(logging.Handler):
    """Deliver log records to the GUI thread through a queued Qt signal."""
    def __init__(self, signal):
        super().__init__(logging.DEBUG)
        self.signal = signal

    def emit(self, record):
        try:
            self.signal.emit(record)
        except Exception:
            self.handleError(record)


class FunctionWorker(QThread):
    resultReady = Signal(object)
    errorRaised = Signal(object)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.resultReady.emit(self.function())
        except Exception as exc:
            self.errorRaised.emit(exc)


class ColorFileSystemModel(QFileSystemModel):
    """Color key Godot/OpenGDS files in the explorer without changing their icons."""
    FILE_COLORS = {
        ".gd": "#73c991",       # GDScript source: green
        ".gdc": "#ff6b6b",      # compiled GDSC: red
        ".godot": "#69aefc",    # project descriptor/config: blue
        ".ogds": "#69aefc",     # OpenGDS project descriptor: blue
    }

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.ForegroundRole and index.isValid() and index.column() == 0:
            path = Path(self.filePath(index))
            suffix = path.suffix.lower()
            if path.name.lower() == "project.godot" or path.name.lower() == ".godot":
                suffix = ".godot"
            color = self.FILE_COLORS.get(suffix)
            if color:
                return QBrush(QColor(color))
        return super().data(index, role)



class SettingsDialog(QDialog):
    def __init__(self, settings, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} Settings")
        self.resize(680, 620)
        self.settings = settings
        self.project = project
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)

        general = QWidget()
        form = QFormLayout(general)
        self.theme = QComboBox(); self.theme.addItems(["dark", "light"]); self.theme.setCurrentText(settings.value("theme", "dark"))
        self.font = QLineEdit(settings.value("font", "Consolas"))
        self.fontsize = QSpinBox(); self.fontsize.setRange(8, 32); self.fontsize.setValue(int(settings.value("font_size", 11)))
        self.autosave = QCheckBox("Automatically save modified files"); self.autosave.setChecked(settings.value("autosave", "true") == "true")
        self.tabwidth = QSpinBox(); self.tabwidth.setRange(1, 8); self.tabwidth.setValue(int(settings.value("tab_width", 4)))
        self.backend = QLineEdit(settings.value("backend_path", str(Path(__file__).with_name("OpenGDS.py"))))
        backend_button = QPushButton("Browse…"); backend_button.clicked.connect(lambda: self.pick(self.backend, "Python backend (*.py)"))
        backend_row = QHBoxLayout(); backend_row.addWidget(self.backend); backend_row.addWidget(backend_button)
        backend_widget = QWidget(); backend_widget.setLayout(backend_row)
        self.godot = QLineEdit(settings.value("godot_path", ""))
        godot_button = QPushButton("Browse…"); godot_button.clicked.connect(lambda: self.pick(self.godot, "Godot executable (*)"))
        godot_row = QHBoxLayout(); godot_row.addWidget(self.godot); godot_row.addWidget(godot_button)
        godot_widget = QWidget(); godot_widget.setLayout(godot_row)
        form.addRow("Appearance", self.theme); form.addRow("Editor font", self.font); form.addRow("Font size", self.fontsize)
        form.addRow("Tab width", self.tabwidth); form.addRow("Autosave", self.autosave)
        form.addRow("OpenGDS.py path", backend_widget); form.addRow("Godot executable (legacy CLI)", godot_widget)
        tabs.addTab(general, "General")

        editor_page = QWidget(); ef = QFormLayout(editor_page)
        self.auto_pairs = QCheckBox("Automatically insert matching brackets and quotes")
        self.auto_pairs.setChecked(settings.value("auto_pairs", "true") == "true")
        self.auto_indent = QCheckBox("Automatically indent new lines")
        self.auto_indent.setChecked(settings.value("auto_indent", "true") == "true")
        self.auto_completion = QCheckBox("Enable local and Godot completion popups")
        self.auto_completion.setChecked(settings.value("auto_completion", "true") == "true")
        self.line_numbers = QCheckBox("Show line numbers and breakpoint gutter")
        self.line_numbers.setChecked(settings.value("line_numbers", "true") == "true")
        self.word_wrap = QCheckBox("Wrap long lines")
        self.word_wrap.setChecked(settings.value("word_wrap", "false") == "true")
        self.autosave_interval = QSpinBox(); self.autosave_interval.setRange(5, 600)
        self.autosave_interval.setSuffix(" seconds")
        self.autosave_interval.setValue(int(settings.value("autosave_interval", 30)))
        ef.addRow(self.auto_pairs); ef.addRow(self.auto_indent); ef.addRow(self.auto_completion)
        ef.addRow(self.line_numbers); ef.addRow(self.word_wrap); ef.addRow("Autosave interval", self.autosave_interval)
        tabs.addTab(editor_page, "Editor")

        language = QWidget(); lf = QFormLayout(language)
        self.lsp_host = QLineEdit(settings.value("lsp_host", "127.0.0.1"))
        self.lsp_port = QSpinBox(); self.lsp_port.setRange(1, 65535); self.lsp_port.setValue(int(settings.value("lsp_port", 6005)))
        self.lsp_autoconnect = QCheckBox("Connect automatically when a project opens")
        self.lsp_autoconnect.setChecked(settings.value("lsp_autoconnect", "false") == "true")
        lf.addRow("Godot LSP host", self.lsp_host); lf.addRow("Godot LSP port", self.lsp_port); lf.addRow(self.lsp_autoconnect)
        note = QLabel("Godot Editor must be running with this project open. Enable the GDScript language server in Editor Settings → Network → Language Server.")
        note.setWordWrap(True); lf.addRow(note)
        tabs.addTab(language, "Language Server")

        debug = QWidget(); df = QFormLayout(debug)
        self.dap_host = QLineEdit(settings.value("dap_host", "127.0.0.1"))
        self.dap_port = QSpinBox(); self.dap_port.setRange(1, 65535); self.dap_port.setValue(int(settings.value("dap_port", 6006)))
        self.remote_port = QSpinBox(); self.remote_port.setRange(1, 65535); self.remote_port.setValue(int(settings.value("godot_remote_port", 6007)))
        self.headless = QCheckBox("Run legacy OpenGDS debugger headless"); self.headless.setChecked(bool(project.get("debug", {}).get("headless", False)))
        self.interrupt = QCheckBox("Automatically break at lifecycle methods (legacy debugger)"); self.interrupt.setChecked(bool(project.get("debug", {}).get("interrupt", False)))
        self.frames = QCheckBox("Include recurring frame callbacks (legacy debugger)"); self.frames.setChecked(bool(project.get("debug", {}).get("include_frame_callbacks", False)))
        self.dryrun = QCheckBox("Legacy debugger dry run (show command only)"); self.dryrun.setChecked(bool(project.get("debug", {}).get("dry_run", False)))
        self.context = QSpinBox(); self.context.setRange(0, 100); self.context.setValue(int(project.get("debug", {}).get("context", 4)))
        self.max_tokens = QSpinBox(); self.max_tokens.setRange(1, 100000); self.max_tokens.setValue(int(project.get("debug", {}).get("max_tokens", 200)))
        self.show_tokens = QCheckBox("Include token listing in static debugger output"); self.show_tokens.setChecked(bool(project.get("debug", {}).get("show_tokens", False)))
        self.scene = QLineEdit(project.get("debug", {}).get("scene", ""))
        self.source = QLineEdit(project.get("debug", {}).get("source_path", ""))
        self.extra = QLineEdit(" ".join(project.get("debug", {}).get("extra_args", [])))
        df.addRow("Godot DAP host", self.dap_host); df.addRow("Godot DAP port", self.dap_port); df.addRow("Remote game port", self.remote_port)
        df.addRow(self.headless); df.addRow(self.interrupt); df.addRow(self.frames); df.addRow(self.dryrun)
        df.addRow("Static debugger token context", self.context); df.addRow("Maximum displayed tokens", self.max_tokens)
        df.addRow(self.show_tokens); df.addRow("Scene (res://…)", self.scene); df.addRow("Source override (res://…)", self.source)
        df.addRow("Extra Godot arguments", self.extra)
        debug_note = QLabel("Native Continue / Pause / Step / Stack / Variables controls use Godot's DAP server. Open the project in Godot and enable Debug Adapter under Editor Settings → Network.")
        debug_note.setWordWrap(True); df.addRow(debug_note)
        tabs.addTab(debug, "Debugging")

        compiler = QWidget(); cf = QFormLayout(compiler)
        self.compile_tab_size = QSpinBox(); self.compile_tab_size.setRange(1, 8); self.compile_tab_size.setValue(int(project.get("compile", {}).get("tab_size", 4)))
        self.compressed = QCheckBox("Compress compiled GDSC output"); self.compressed.setChecked(project.get("compile", {}).get("compressed", True))
        self.overwrite = QCheckBox("Allow overwriting compiled output"); self.overwrite.setChecked(project.get("compile", {}).get("overwrite", False))
        self.continue_error = QCheckBox("Continue compiling other files after an error"); self.continue_error.setChecked(project.get("compile", {}).get("continue_on_error", True))
        self.compile_output = QLineEdit(project.get("compile", {}).get("output_directory", ".opengds/compiled"))
        self.validate_after_compile = QCheckBox("Offer Godot --check-only validation after project compilation")
        self.validate_after_compile.setChecked(project.get("compile", {}).get("validate_with_godot", True))
        cf.addRow("Tokenizer tab size", self.compile_tab_size); cf.addRow(self.compressed); cf.addRow(self.overwrite); cf.addRow(self.continue_error)
        cf.addRow("Project output directory", self.compile_output); cf.addRow(self.validate_after_compile)
        compile_note = QLabel("OpenGDS comp creates GDSC v101 token buffers. Godot --check-only performs engine parser/type validation; it is not an export of a standalone .gdc file.")
        compile_note.setWordWrap(True); cf.addRow(compile_note)
        tabs.addTab(compiler, "Compiler")

        advanced = QWidget(); af = QFormLayout(advanced)
        self.show_hidden = QCheckBox("Show hidden files and folders in the project explorer")
        self.show_hidden.setChecked(settings.value("show_hidden_files", "false") == "true")
        self.max_log_records = QSpinBox(); self.max_log_records.setRange(1000, 100000)
        self.max_log_records.setSingleStep(1000); self.max_log_records.setValue(int(settings.value("max_log_records", 12000)))
        self.backend_timeout = QSpinBox(); self.backend_timeout.setRange(10, 3600); self.backend_timeout.setSuffix(" seconds")
        self.backend_timeout.setValue(int(settings.value("backend_timeout", 300)))
        af.addRow(self.show_hidden); af.addRow("Maximum records in log viewer", self.max_log_records)
        af.addRow("OpenGDS command timeout", self.backend_timeout)
        advanced_note = QLabel("The log files rotate on disk. This controls only the in-memory GUI viewer. Binary files such as .gdc are inspected, never decoded as UTF-8 editor text.")
        advanced_note.setWordWrap(True); af.addRow(advanced_note)
        tabs.addTab(advanced, "Advanced")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); root.addWidget(buttons)

    def pick(self, target, filter_text):
        path, _ = QFileDialog.getOpenFileName(self, "Select file", target.text(), filter_text)
        if path:
            target.setText(path)

    def apply(self):
        for key, value in {
            "theme": self.theme.currentText(), "font": self.font.text(), "font_size": self.fontsize.value(),
            "tab_width": self.tabwidth.value(), "autosave": str(self.autosave.isChecked()).lower(),
            "autosave_interval": self.autosave_interval.value(),
            "auto_pairs": str(self.auto_pairs.isChecked()).lower(),
            "auto_indent": str(self.auto_indent.isChecked()).lower(),
            "auto_completion": str(self.auto_completion.isChecked()).lower(),
            "line_numbers": str(self.line_numbers.isChecked()).lower(),
            "word_wrap": str(self.word_wrap.isChecked()).lower(),
            "show_hidden_files": str(self.show_hidden.isChecked()).lower(),
            "max_log_records": self.max_log_records.value(),
            "backend_timeout": self.backend_timeout.value(),
            "backend_path": self.backend.text(), "godot_path": self.godot.text(),
            "lsp_host": self.lsp_host.text(), "lsp_port": self.lsp_port.value(),
            "lsp_autoconnect": str(self.lsp_autoconnect.isChecked()).lower(),
            "dap_host": self.dap_host.text(), "dap_port": self.dap_port.value(),
            "godot_remote_port": self.remote_port.value(),
        }.items():
            self.settings.setValue(key, value)
        self.project.setdefault("debug", {}).update({
            "headless": self.headless.isChecked(), "interrupt": self.interrupt.isChecked(),
            "include_frame_callbacks": self.frames.isChecked(), "dry_run": self.dryrun.isChecked(),
            "context": self.context.value(), "max_tokens": self.max_tokens.value(),
            "show_tokens": self.show_tokens.isChecked(), "scene": self.scene.text(),
            "source_path": self.source.text(), "extra_args": self.extra.text().split(),
        })
        self.project.setdefault("compile", {}).update({
            "compressed": self.compressed.isChecked(), "overwrite": self.overwrite.isChecked(),
            "continue_on_error": self.continue_error.isChecked(), "tab_size": self.compile_tab_size.value(),
            "output_directory": self.compile_output.text().strip() or ".opengds/compiled",
            "validate_with_godot": self.validate_after_compile.isChecked(),
        })


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {VERSION} — GDScript IDE")
        icon_file = Path(__file__).with_name("assets") / "opengds-ide.svg"
        if icon_file.is_file():
            self.setWindowIcon(QIcon(str(icon_file)))
        self.resize(1520, 960)
        self.settings = QSettings("OpenGDS", "IDE")
        self.log_path = configure_logging(log_directory() / "studio.log")
        self.log_signal = LogSignal(self)
        self.log_signal.record.connect(self.render_log_record)
        self.qt_log_handler = QtLogHandler(self.log_signal.record)
        self.qt_log_handler.setLevel(logging.DEBUG)
        self.app_logger = logging.getLogger("opengds")
        self.app_logger.addHandler(self.qt_log_handler)
        self.log_formatter = logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)s [%(category)s] %(message)s", "%H:%M:%S")
        self.log_records = []
        self._logged_diagnostics = {}
        self._last_lsp_diagnostics = {}
        install_exception_hooks()
        self._qt_message_handler = self.qt_message_handler
        self.data = None
        self.root: Path | None = None
        self.backend: OpenGDSBackend | None = None
        self.editors: dict[Path, CodeEditor] = {}
        self.process: QProcess | None = None
        self.legacy_debug_active = False
        self._workers = set()
        self.lsp = GodotLanguageClient(self)
        self.dap = GodotDebugClient(self)
        self.lsp_diagnostics: dict[str, list] = {}
        self.server_completions: list[str] = []
        self.server_insertions: dict[str, str] = {}
        self.workspace_completions: list[str] = []
        self.godot_process: QProcess | None = None
        appdata = Path.home() / ".opengds-studio"
        self.history = History(appdata / "history.json")

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.tab_changed)
        self.setCentralWidget(self.tabs)

        self._make_docks()
        qInstallMessageHandler(self._qt_message_handler)
        log_event("GUI", logging.INFO, f"{APP_NAME} {VERSION} session started; IDE log: {self.log_path}")
        log_event("CORE", logging.INFO, f"OpenGDS core log directory: {log_directory()}")
        self._make_actions()
        self._make_toolbar()
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

        self.lsp.statusChanged.connect(self.on_lsp_status)
        self.lsp.diagnosticsReceived.connect(self.on_lsp_diagnostics)
        self.lsp.completionReceived.connect(self.on_lsp_completions)
        self.lsp.readyChanged.connect(self.on_lsp_ready)
        self.dap.statusChanged.connect(self.on_dap_status)
        self.dap.outputReceived.connect(lambda message: self.log(message, category="GODOT_DEBUG"))
        self.dap.stopped.connect(self.on_debug_stopped)
        self.dap.continued.connect(self.on_debug_continued)
        self.dap.terminated.connect(self.on_debug_terminated)
        self.dap.stackChanged.connect(self.populate_stack)
        self.dap.variablesChanged.connect(self.populate_variables)
        self.dap.breakpointResult.connect(lambda rows: self.log(f"Godot breakpoint response: {rows}", category="DAP"))

        self.apply_theme()
        self.restore_geometry()
        self.show_welcome()
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(int(self.settings.value("autosave_interval", 30)) * 1000)
        self.autosave_timer.timeout.connect(self.autosave_modified)
        self.autosave_timer.start()
        self.analysis_timer = QTimer(self)
        self.analysis_timer.setSingleShot(True)
        self.analysis_timer.setInterval(350)
        self.analysis_timer.timeout.connect(self.refresh_language_tools)

    def restore_geometry(self):
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def _make_docks(self):
        self.tree = QTreeView()
        self.fs = ColorFileSystemModel()
        self.fs.setReadOnly(False)
        fs_filter = QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot
        if self.settings.value("show_hidden_files", "false") == "true":
            fs_filter |= QDir.Filter.Hidden
        self.fs.setFilter(fs_filter)
        self.tree.setModel(self.fs)
        self.tree.doubleClicked.connect(self.tree_open)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_context_menu)
        for column in (1, 2, 3):
            self.tree.hideColumn(column)
        self.explorer = QDockWidget("EXPLORER", self)
        self.explorer.setWidget(self.tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.explorer)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.document().setMaximumBlockCount(int(self.settings.value("max_log_records", 12000)))
        self.log_filter = QComboBox()
        self.log_filter.addItem("All categories")
        self.log_filter.addItems(sorted(CATEGORY_COLORS))
        self.log_filter.currentTextChanged.connect(self.apply_log_filter)
        self.log_search = QLineEdit()
        self.log_search.setPlaceholderText("Search log messages…")
        self.log_search.textChanged.connect(lambda _text: self.apply_log_filter(self.log_filter.currentText()))
        open_logs = QPushButton("Open logs folder")
        open_logs.clicked.connect(self.open_logs_folder)
        clear_logs = QPushButton("Clear view")
        clear_logs.clicked.connect(self.clear_log_view)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Category:")); filter_row.addWidget(self.log_filter)
        filter_row.addWidget(self.log_search, 2)
        filter_row.addWidget(open_logs); filter_row.addWidget(clear_logs)
        self.console_input = QLineEdit()
        self.console_input.setPlaceholderText("Evaluate watch expression while paused… (Enter)")
        self.console_input.returnPressed.connect(self.evaluate_watch_expression)
        terminal = QWidget(); terminal_layout = QVBoxLayout(terminal)
        terminal_layout.setContentsMargins(4, 4, 4, 4)
        terminal_layout.addLayout(filter_row)
        terminal_layout.addWidget(self.output); terminal_layout.addWidget(self.console_input)
        self.output_dock = QDockWidget("DETAILED LOG / DEBUG CONSOLE", self)
        self.output_dock.setWidget(terminal)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.output_dock)
        self.output_dock.setMinimumHeight(170)

        self.inspector = QListWidget()
        self.outline = QListWidget()
        self.outline.itemDoubleClicked.connect(self.go_to_outline_item)
        self.problems = QListWidget()
        self.problems.itemDoubleClicked.connect(self.go_to_problem_item)
        self.breakpoints_view = QListWidget()
        self.breakpoints_view.itemDoubleClicked.connect(self.go_to_breakpoint_item)
        self.call_stack_view = QListWidget()
        self.call_stack_view.itemDoubleClicked.connect(self.go_to_stack_item)
        self.variables_view = QListWidget()
        self.variables_view.itemDoubleClicked.connect(self.expand_variable_item)

        self.watch_view = QListWidget()
        self.watch_view.itemDoubleClicked.connect(self.evaluate_selected_watch)
        watch_widget = QWidget(); watch_layout = QVBoxLayout(watch_widget)
        watch_layout.setContentsMargins(4, 4, 4, 4)
        watch_input_row = QHBoxLayout()
        self.watch_input = QLineEdit(); self.watch_input.setPlaceholderText("Expression to watch")
        add_watch = QPushButton("Add"); add_watch.clicked.connect(self.add_watch)
        remove_watch = QPushButton("Remove"); remove_watch.clicked.connect(self.remove_watch)
        watch_input_row.addWidget(self.watch_input); watch_input_row.addWidget(add_watch); watch_input_row.addWidget(remove_watch)
        watch_layout.addLayout(watch_input_row); watch_layout.addWidget(self.watch_view)

        self.debug_tabs = QTabWidget()
        self.debug_tabs.addTab(self.breakpoints_view, "Breakpoints")
        self.debug_tabs.addTab(self.call_stack_view, "Call Stack")
        self.debug_tabs.addTab(self.variables_view, "Variables")
        self.debug_tabs.addTab(watch_widget, "Watch")
        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.inspector, "Project")
        self.right_tabs.addTab(self.outline, "Outline")
        self.right_tabs.addTab(self.problems, "Problems")
        self.right_tabs.addTab(self.debug_tabs, "Debug")
        self.inspector_dock = QDockWidget("CODE INSIGHT", self)
        self.inspector_dock.setWidget(self.right_tabs)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_dock)

    def act(self, name, slot, shortcut=None):
        action = QAction(name, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        return action

    def _make_actions(self):
        file_menu = self.menuBar().addMenu("File")
        for action in [
            self.act("New Project…", self.new_project, "Ctrl+Shift+N"),
            self.act("Open Project / Folder…", self.open_project, "Ctrl+K, Ctrl+O"),
            self.act("Open File…", self.open_file, "Ctrl+O"),
            self.act("Create / Save OpenGDS Workspace (.ogds)…", self.new_workspace_descriptor),
            self.act("Save", self.save_file, "Ctrl+S"),
            self.act("Save All", self.save_all, "Ctrl+Shift+S"),
            self.act("Close Tab", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W"),
        ]:
            file_menu.addAction(action)
        history = file_menu.addMenu("Recent Projects")
        self.history_menu = history
        self.refresh_history_menu()
        history.addSeparator(); history.addAction("Manage History…", self.manage_history)
        file_menu.addSeparator(); file_menu.addAction("Exit", self.close)

        edit = self.menuBar().addMenu("Edit")
        edit.addAction(self.act("Find", self.find_in_editor, "Ctrl+F"))
        edit.addAction(self.act("Go to Symbol…", self.go_to_symbol, "Ctrl+Shift+O"))
        edit.addAction(self.act("Toggle Breakpoint", self.toggle_breakpoint, "F9"))
        edit.addAction(self.act("Undo", lambda: self.current_editor() and self.current_editor().undo(), "Ctrl+Z"))
        edit.addAction(self.act("Redo", lambda: self.current_editor() and self.current_editor().redo(), "Ctrl+Y"))

        build = self.menuBar().addMenu("OpenGDS")
        for label, mode in [
            ("Compile current GDScript…", "compile"),
            ("Compile selected folder…", "compile_folder"),
            ("Compile entire project…", "compile_project"),
            ("Decompile GDSC file…", "decompile"),
            ("Decompile selected folder…", "decompile_folder"),
            ("Decompile all project GDSC…", "decompile_project"),
            ("GDSC Info / Validate…", "info"),
            ("Static GDSC Debugger…", "dbg"),
            ("Security Audit…", "audit"),
            ("Disassemble Tokens…", "disasm"),
            ("Extract Constants…", "consts"),
            ("Decoded Payload Hex Dump…", "hexdump"),
            ("Compare GDSC Files…", "diff"),
        ]:
            build.addAction(self.act(label, lambda checked=False, m=mode: self.backend_action(m)))
        build.addSeparator()
        build.addAction(self.act("Run Advanced OpenGDS CLI Command…", self.run_custom_core_command))
        build.addSeparator()
        analysis = build.addMenu("Analyze all project GDSC files")
        for label, mode in [
            ("Info / Validate", "project_info"), ("Security Audit", "project_audit"),
            ("Static Debugger", "project_dbg"), ("Disassemble Tokens", "project_disasm"),
            ("Extract Constants", "project_consts"), ("Decoded Payload Hex Dump", "project_hexdump"),
        ]:
            analysis.addAction(self.act(label, lambda checked=False, m=mode: self.backend_action(m)))
        build.addAction(self.act("Inspect / Extract PCK, ZIP, APK or EXE…", self.extract_archive))
        build.addSeparator()
        build.addAction(self.act("Godot Validate Current .gd (--check-only)…", self.validate_current_script_with_godot))
        build.addAction(self.act("Godot Headless Script Validation (--check-only)…", self.validate_project_with_godot))
        build.addAction(self.act("Godot Headless Project Import…", self.godot_import_project))
        build.addAction(self.act("Create Project ZIP Snapshot…", self.create_project_zip))
        build.addAction(self.act("Godot Export PCK…", lambda: self.godot_export("pack")))
        build.addAction(self.act("Godot Export Debug Build…", lambda: self.godot_export("debug")))
        build.addAction(self.act("Godot Export Release Build…", lambda: self.godot_export("release")))
        build.addSeparator()
        build.addAction(self.act("OpenGDS Runtime Debug with Godot (--godot)…", self.start_legacy_debug))
        build.addAction(self.act("OpenGDS Runtime Debug + Break at Startup (--interrupt)…", self.start_legacy_debug_interrupt))

        run = self.menuBar().addMenu("Run")
        run.addAction(self.act("Run Project with Godot", lambda: self.run_godot_project(debug=False), "Ctrl+F5"))
        run.addAction(self.act("Run Project with Godot Local Debugger (--debug)", lambda: self.run_godot_project(debug=True)))
        run.addSeparator()
        run.addAction(self.act("Start / Continue DAP Debugging", self.start_debug, "F5"))
        run.addAction(self.act("Continue", self.dap.continue_execution, "F6"))
        run.addAction(self.act("Step Over", self.dap.step_over, "F10"))
        run.addAction(self.act("Step Into", self.dap.step_into, "F11"))
        run.addAction(self.act("Step Out", self.dap.step_out, "Shift+F11"))
        run.addAction(self.act("Pause", self.dap.pause, "Ctrl+F6"))
        run.addAction(self.act("Stop Debugging", self.stop_debug, "Shift+F5"))

        language = self.menuBar().addMenu("Language")
        language.addAction(self.act("Connect to Godot Language Server…", self.connect_language_server))
        language.addAction(self.act("Disconnect Language Server", self.lsp.disconnect_from_server))
        language.addAction(self.act("Analyze Current File", self.refresh_language_tools, "Ctrl+Shift+M"))

        view = self.menuBar().addMenu("View")
        for dock in (self.explorer, self.output_dock, self.inspector_dock):
            view.addAction(dock.toggleViewAction())
        view.addAction(self.act("Toggle Dark / Light", self.toggle_theme))

        tools = self.menuBar().addMenu("Tools")
        tools.addAction(self.act("Settings…", self.open_settings, "Ctrl+,"))
        tools.addAction(self.act("Launch Godot Editor for Project…", self.launch_godot_editor))
        tools.addAction(self.act("Run Custom Godot CLI Arguments…", self.run_custom_godot_command))
        tools.addAction(self.act("Update OpenGDS.py Core…", self.update_backend))
        tools.addAction(self.act("Open Project Folder", self.open_root_folder))
        tools.addAction(self.act("Open Logs Folder…", self.open_logs_folder))
        tools.addAction(self.act("OpenGDS Core CLI Help…", self.show_core_help))
        tools.addAction(self.act("Environment / Dependency Diagnostics…", self.show_environment_diagnostics))
        tools.addAction(self.act("Clear Log View", self.clear_log_view))
        help_menu = self.menuBar().addMenu("Help")
        developer_action = QAction(f"Developer: {DEVELOPER}", self)
        developer_action.setEnabled(False)
        help_menu.addAction(developer_action)
        help_menu.addSeparator()
        help_menu.addAction(self.act("About OpenGDS - IDE", self.about))

    def _make_toolbar(self):
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        for text, slot in [
            ("New", self.new_project), ("Open", self.open_project), ("Save", self.save_file),
            ("Compile", lambda: self.backend_action("compile")), ("Launch Godot", self.launch_godot_editor), ("Connect LSP", self.connect_language_server),
            ("Debug", self.start_debug), ("Continue", self.dap.continue_execution),
            ("Step Over", self.dap.step_over), ("Stop", self.stop_debug),
        ]:
            button = QToolButton(); button.setText(text); button.clicked.connect(slot); toolbar.addWidget(button)

    def show_welcome(self):
        welcome = QPlainTextEdit(); welcome.setReadOnly(True)
        welcome.setPlainText(
            f"{APP_NAME} {VERSION}\n\n"
            "GDScript / GDSC desktop IDE\n\n"
            "• Open a file.ogds project or any project folder.\n"
            "• Connect to the Godot 4.x language server for live completion and diagnostics.\n"
            "• Connect to Godot's DAP server for breakpoints, stepping, stack frames and variables.\n"
            "• Right-click the project tree to create, rename or delete files and folders.\n\n"
            "Godot Editor must have the same project open for LSP and DAP.\n"
            "Default ports: LSP 6005, DAP 6006, remote game debugger 6007.\n\n"
            f"OpenGDS backend: {Path(__file__).with_name('OpenGDS.py')}"
        )
        self.tabs.addTab(welcome, "Welcome")

    def apply_theme(self):
        theme = self.settings.value("theme", "dark")
        QApplication.instance().setStyleSheet(DARK if theme == "dark" else LIGHT)
        for editor in self.editors.values():
            editor.set_theme(theme)

    def toggle_theme(self):
        self.settings.setValue("theme", "light" if self.settings.value("theme", "dark") == "dark" else "dark")
        self.apply_theme()

    def current_editor(self):
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, CodeEditor) else None

    def project_root(self):
        return Path(self.data["root"]).resolve() if self.data and self.data.get("root") else self.root

    def set_project(self, data):
        if self.root and Path(data["root"]).resolve() != self.root:
            self.dap.disconnect_from_server()
            self.lsp.disconnect_from_server()
            self.lsp_diagnostics.clear()
            self.server_completions.clear()
        self.data = data
        self.root = Path(data["root"]).resolve()
        self.fs.setRootPath(str(self.root))
        self.tree.setRootIndex(self.fs.index(str(self.root)))
        self.explorer.setWindowTitle("EXPLORER — " + data.get("name", self.root.name))
        backend_path = self.settings.value("backend_path", data.get("backend") or str(Path(__file__).with_name("OpenGDS.py")))
        self.backend = OpenGDSBackend(backend_path)
        self.backend.default_timeout = int(self.settings.value("backend_timeout", 300))
        self.data["backend"] = str(self.backend.script)
        if data.get("descriptor"):
            self.history.add(data["descriptor"])
        else:
            self.history.add(str(self.root))
        self.refresh_history_menu()
        self.inspector.clear()
        self.inspector.addItems([
            f"Project: {data.get('name', self.root.name)}", f"Root: {self.root}",
            f"Backend: {self.backend.script}",
            f"Godot: {data.get('godot_executable') or self.settings.value('godot_path', 'Not configured')}",
        ])
        self.workspace_completions = project_symbols(self.root)
        self.statusBar().showMessage(f"Project loaded: {self.root}")
        self.log(f"Project loaded: {self.root}", category="FILE")
        if self.settings.value("lsp_autoconnect", "false") == "true":
            self.connect_language_server()

    def new_project(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose project folder")
        if not folder:
            return
        name, ok = QInputDialog.getText(self, "New OpenGDS project", "Project name:", text=Path(folder).name)
        if not ok:
            return
        try:
            self.set_project(load_project(create_project(folder, name)))
        except Exception as exc:
            self.error(exc)

    def new_workspace_descriptor(self, selected_root=None):
        """Create an IDE-owned .ogds descriptor without modifying project.godot."""
        root = Path(selected_root).resolve() if selected_root else self._choose_project_root()
        if not root:
            return
        suggested = root / "file.ogds"
        chosen, _ = QFileDialog.getSaveFileName(self, "Create OpenGDS workspace descriptor", str(suggested), "OpenGDS workspace (*.ogds)")
        if not chosen:
            return
        descriptor = Path(chosen).resolve()
        if descriptor.suffix.lower() != ".ogds":
            descriptor = descriptor.with_suffix(".ogds")
        name, ok = QInputDialog.getText(self, "Workspace name", "Display name:", text=root.name)
        if not ok:
            return
        try:
            path = create_project(root, name or root.name, descriptor=descriptor)
            self.set_project(load_project(path))
            self.log(f"Created OpenGDS workspace descriptor: {path}", category="FILE")
        except Exception as exc:
            self.error(exc)

    def show_environment_diagnostics(self):
        import importlib.util
        rows = [f"Application: {APP_NAME} {VERSION}", f"Python: {sys.version}", f"Interpreter: {sys.executable}",
                f"Platform: {sys.platform}", f"Working directory: {Path.cwd()}"]
        for module in ("PySide6", "zstandard"):
            try:
                spec = importlib.util.find_spec(module)
                rows.append(f"{module}: {'available' if spec else 'MISSING'}")
            except Exception as exc:
                rows.append(f"{module}: detection failed ({exc})")
        try:
            backend = self.ensure_backend()
            result = subprocess.run([sys.executable, str(backend.script), "--version"],
                cwd=str(self.project_root() or backend.script.parent), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=10, check=False)
            rows += [f"OpenGDS backend: {backend.script}", f"OpenGDS version: {result.stdout.strip() or 'unknown'} (exit {result.returncode})"]
        except Exception as exc:
            rows.append(f"OpenGDS backend: ERROR — {exc}")
        godot = self.find_godot(prompt=False)
        if godot:
            try:
                result = subprocess.run([godot, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", timeout=10, check=False)
                rows += [f"Godot executable: {godot}", f"Godot version: {result.stdout.strip() or 'unknown'} (exit {result.returncode})"]
            except Exception as exc:
                rows.append(f"Godot executable: {godot} (version check failed: {exc})")
        else:
            rows.append("Godot executable: not detected (OpenGDS offline features remain available)")
        rows += [f"Workspace: {self.project_root() or 'not open'}", f"Logs: {log_directory()}",
                 f"LSP endpoint: {self.settings.value('lsp_host', '127.0.0.1')}:{self.settings.value('lsp_port', 6005)}",
                 f"DAP endpoint: {self.settings.value('dap_host', '127.0.0.1')}:{self.settings.value('dap_port', 6006)}"]
        report = "\n".join(rows)
        self.show_report_tab("Environment Diagnostics", report)
        self.log("Environment diagnostics generated", category="SYSTEM")

    def show_core_help(self):
        try:
            backend = self.ensure_backend()
            result = subprocess.run([sys.executable, str(backend.script), "--help"], cwd=str(self.project_root() or backend.script.parent),
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=15, check=False)
            self.show_report_tab("OpenGDS Core CLI Reference", result.stdout)
        except Exception as exc:
            self.error(exc)

    def open_project(self):
        path = QFileDialog.getOpenFileName(
            self, "Open OpenGDS workspace or Godot project", str(self.project_root() or Path.home()),
            "Project files (*.ogds project.godot);;OpenGDS workspace (*.ogds);;Godot project (project.godot);;All files (*)"
        )[0]
        if not path:
            path = QFileDialog.getExistingDirectory(self, "Open any project/workspace folder", str(Path.home()))
        if not path:
            return
        try:
            candidate = Path(path).expanduser().resolve()
            if candidate.is_dir():
                descriptor = candidate / "file.ogds"
                data = load_project(descriptor) if descriptor.is_file() else workspace_from_directory(candidate)
            elif candidate.name.lower() == "project.godot":
                data = workspace_from_directory(candidate.parent)
            elif candidate.suffix.lower() == ".ogds":
                data = load_project(candidate)
            else:
                raise ValueError("Choose file.ogds, project.godot, or any directory")
            self.set_project(data)
        except Exception as exc:
            self.error(exc)

    def ensure_backend(self):
        if not self.backend:
            configured = self.settings.value("backend_path", str(Path(__file__).with_name("OpenGDS.py")))
            self.backend = OpenGDSBackend(configured)
        self.backend.default_timeout = int(self.settings.value("backend_timeout", 300))
        return self.backend

    def show_report_tab(self, title, content, source_path=None):
        source = Path(source_path).resolve() if source_path else None
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if getattr(widget, "report_source", None) == str(source) and source:
                view = getattr(widget, "report_text", None)
                if view:
                    view.setPlainText(content)
                self.tabs.setCurrentWidget(widget)
                return widget

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        if source and source.suffix.lower() == ".gdc":
            action_row = QHBoxLayout()
            actions = [
                ("Decompile → .gd", lambda p=source: self.decompile_single_binary(p)),
                ("Static Debug", lambda p=source: self.backend_action("dbg", p)),
                ("Runtime Debug (--godot)", lambda p=source: self.start_legacy_debug(p, force_interrupt=False)),
                ("Break at Startup (--interrupt)", lambda p=source: self.start_legacy_debug(p, force_interrupt=True)),
                ("Compare…", lambda p=source: self.backend_action("diff", p)),
                ("Audit", lambda p=source: self.backend_action("audit", p)),
                ("Disassemble", lambda p=source: self.backend_action("disasm", p)),
                ("Constants", lambda p=source: self.backend_action("consts", p)),
                ("Hex Dump", lambda p=source: self.backend_action("hexdump", p)),
            ]
            for label, callback in actions:
                button = QPushButton(label)
                button.clicked.connect(callback)
                action_row.addWidget(button)
            action_row.addStretch(1)
            layout.addLayout(action_row)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        view.setFont(QFont(self.settings.value("font", "Consolas"), int(self.settings.value("font_size", 11))))
        view.setPlainText(content)
        layout.addWidget(view)
        container.report_source = str(source) if source else ""
        container.report_text = view
        index = self.tabs.addTab(container, title)
        if source:
            self.tabs.setTabToolTip(index, str(source))
        self.tabs.setCurrentIndex(index)
        return container

    def open_path(self, path):
        path = Path(path).expanduser().resolve()
        if path.is_dir():
            return
        if path.suffix.lower() == ".ogds":
            self.set_project(load_project(path))
            return
        if path.name.lower() == "project.godot":
            self.set_project(workspace_from_directory(path.parent))
            return
        if path in self.editors:
            self.tabs.setCurrentWidget(self.editors[path])
            return
        try:
            suffix = path.suffix.lower()
            if suffix == ".gdc":
                tab = self.show_report_tab(f"{path.name} — GDSC Info", "Inspecting GDSC header and decoded payload…\n", path)
                backend = self.ensure_backend()
                def inspect_gdc():
                    return backend.inspect("info", path)
                def show_gdc_info(report):
                    tab.report_text.setPlainText(report)
                    self.log(f"Inspected compiled GDSC on open: {path}", category="GDSC")
                self.run_background(f"Inspect GDSC {path.name}", inspect_gdc, show_gdc_info)
                return
            if looks_like_pck_or_executable(path):
                try:
                    archive = read_pck(path)
                    self.show_report_tab(f"{path.name} — PCK", pck_report(archive), path)
                    self.log(f"Inspected Godot PCK: {path}", category="ARCHIVE")
                except ArchiveError as archive_error:
                    raw = path.read_bytes()[:256]
                    self.show_report_tab(
                        f"{path.name} — Binary Info",
                        f"BINARY FILE: {path}\nSIZE: {path.stat().st_size:,} bytes\n\nNo supported embedded Godot PCK was found.\n{archive_error}\n\nFirst 256 bytes (hex):\n{raw.hex(' ')}",
                        path,
                    )
                    self.log(f"No supported PCK found in {path}: {archive_error}", category="ARCHIVE", level=logging.WARNING)
                return
            if suffix in {".zip", ".apk"}:
                report = zip_report(path)
                self.show_report_tab(f"{path.name} — Archive", report, path)
                self.log(f"Inspected ZIP archive: {path}", category="FILE")
                return

            raw = path.read_bytes()
            if b"\x00" in raw[:8192]:
                preview = raw[:256].hex(" ")
                self.show_report_tab(
                    f"{path.name} — Binary Info",
                    f"BINARY FILE: {path}\nSIZE: {len(raw):,} bytes\n\nThis file is not opened as editable UTF-8 text.\nFirst 256 bytes (hex):\n{preview}\n\nIf this is a Godot .gdc file, use OpenGDS → GDSC Info / Decompile.",
                    path,
                )
                return
            try:
                content = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                preview = raw[:256].hex(" ")
                self.show_report_tab(
                    f"{path.name} — Encoding Info",
                    f"TEXT DECODING FAILED: {path}\nSIZE: {len(raw):,} bytes\n\nThe file is not valid UTF-8. No decoding exception escaped the GUI.\nFirst 256 bytes (hex):\n{preview}\n\nChoose an encoding or use a format-specific inspector.",
                    path,
                )
                self.log(f"Refused unsafe UTF-8 text open; showed binary preview: {path}", category="FILE", level=logging.WARNING)
                return

            editor = CodeEditor(self.settings.value("theme", "dark"), int(self.settings.value("tab_width", 4)))
            editor.setFont(QFont(self.settings.value("font", "Consolas"), int(self.settings.value("font_size", 11))))
            editor.configure_features(
                auto_pairs=self.settings.value("auto_pairs", "true") == "true",
                auto_indent=self.settings.value("auto_indent", "true") == "true",
                auto_completion=self.settings.value("auto_completion", "true") == "true",
                line_numbers=self.settings.value("line_numbers", "true") == "true",
                word_wrap=self.settings.value("word_wrap", "false") == "true",
            )
            editor.setPlainText(content)
            editor.file_path = path
            editor.document().setModified(False)
            editor.textChanged.connect(lambda e=editor: self.editor_changed(e))
            editor.breakpointsChanged.connect(lambda lines, e=editor: self.on_breakpoints_changed(e, lines))
            editor.completionRequested.connect(lambda line, column, e=editor: self.request_completion(e, line, column))
            self.editors[path] = editor
            index = self.tabs.addTab(editor, path.name)
            self.tabs.setTabToolTip(index, str(path))
            self.tabs.setCurrentIndex(index)
            if suffix == ".gd":
                self.lsp.open_document(path, content)
                editor._last_lsp_text = content
            self.analysis_timer.start()
            self.statusBar().showMessage(str(path))
        except Exception as exc:
            self.error(exc)

    def open_file(self):
        start = str(self.project_root() or Path.home())
        path = QFileDialog.getOpenFileName(
            self, "Open source, compiled script or archive", start,
            "Godot/OpenGDS files (*.gd *.gdc *.godot *.ogds *.pck *.zip *.apk *.exe *.bin *.x86_64 *.linux *.linuxbsd *.macos *.dll *.so *.dylib);;Text files (*.gd *.txt *.json *.cfg *.tscn *.tres);;All files (*)"
        )[0]
        if path:
            self.open_path(path)

    def tree_open(self, index):
        path = Path(self.fs.filePath(index))
        if path.is_dir():
            # Expand on double-click. The tree's disclosure arrow can still collapse it.
            QTimer.singleShot(0, lambda idx=index: self.tree.setExpanded(idx, True))
            return
        if path.is_file():
            if path.name.lower() == "project.godot":
                try:
                    self.set_project(workspace_from_directory(path.parent))
                except Exception as exc:
                    self.error(exc)
            elif path.suffix.lower() == ".ogds":
                try:
                    self.set_project(load_project(path))
                except Exception as exc:
                    self.error(exc)
            else:
                self.open_path(path)

    def tree_context_menu(self, point):
        index = self.tree.indexAt(point)
        selected = Path(self.fs.filePath(index)) if index.isValid() else self.project_root()
        if not selected:
            return
        parent_dir = selected if selected.is_dir() else selected.parent
        menu = QMenu(self)
        new_file_action = menu.addAction("New File…")
        new_folder_action = menu.addAction("New Folder…")
        menu.addSeparator()
        open_action = menu.addAction("Open / Inspect") if selected.is_file() else None
        special_actions = {}
        if selected.is_dir():
            try:
                if next(iter_project_files(selected, ".gd"), None):
                    special_actions[menu.addAction("Compile .gd files in this folder…")] = "compile_selected_folder"
                if next(iter_project_files(selected, ".gdc", include_compiled_output=True), None):
                    special_actions[menu.addAction("Decompile .gdc files in this folder…")] = "decompile_selected_folder"
            except OSError:
                pass
            if not (selected / "file.ogds").is_file():
                special_actions[menu.addAction("Create file.ogds workspace descriptor…")] = "create_descriptor"
        if selected.is_file():
            suffix = selected.suffix.lower()
            if suffix == ".gd":
                special_actions[menu.addAction("Compile this .gd → .gdc")] = "compile_selected"
                special_actions[menu.addAction("Static Debug this GDScript")] = "debug_selected"
                special_actions[menu.addAction("Validate with Godot (--check-only)…")] = "godot_check_selected"
                special_actions[menu.addAction("Runtime Debug with Godot (--godot)…")] = "runtime_debug_selected"
                special_actions[menu.addAction("Runtime Debug + Startup Break (--interrupt)…")] = "runtime_debug_interrupt_selected"
            elif suffix == ".gdc":
                special_actions[menu.addAction("GDSC Info / Validate")] = "info_selected"
                special_actions[menu.addAction("Decompile this .gdc → .gd…")] = "decompile_selected"
                special_actions[menu.addAction("Static Debug this GDSC")] = "debug_selected"
                special_actions[menu.addAction("Runtime Debug with Godot (--godot)…")] = "runtime_debug_selected"
                special_actions[menu.addAction("Runtime Debug + Startup Break (--interrupt)…")] = "runtime_debug_interrupt_selected"
            elif suffix in {".zip", ".apk"} or looks_like_pck_or_executable(selected):
                special_actions[menu.addAction("Inspect Archive / PCK")] = "archive_info"
                special_actions[menu.addAction("Extract Archive…")] = "archive_extract"
        rename_action = menu.addAction("Rename…") if index.isValid() else None
        delete_action = menu.addAction("Delete…") if index.isValid() else None
        menu.addSeparator()
        copy_action = menu.addAction("Copy Path")
        reveal_action = menu.addAction("Reveal in File Manager")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(point))
        if chosen == new_file_action:
            name, ok = QInputDialog.getText(self, "New File", "File name:")
            if ok and name:
                path = parent_dir / name
                if path.exists():
                    self.error(f"File already exists: {path}")
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("", encoding="utf-8")
                    self.open_path(path)
        elif chosen == new_folder_action:
            name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
            if ok and name:
                target = parent_dir / name
                if target.exists():
                    self.error(f"Folder already exists: {target}")
                else:
                    target.mkdir(parents=True)
        elif open_action is not None and chosen == open_action:
            self.open_path(selected)
        elif chosen in special_actions:
            action = special_actions[chosen]
            if action == "compile_selected":
                self.compile_single_source(selected)
            elif action == "compile_selected_folder":
                self.backend_action("compile_folder", selected)
            elif action == "decompile_selected_folder":
                self.backend_action("decompile_folder", selected)
            elif action == "create_descriptor":
                self.new_workspace_descriptor(selected)
            elif action == "debug_selected":
                self.backend_action("dbg", selected)
            elif action == "godot_check_selected":
                self.validate_current_script_with_godot(selected)
            elif action == "info_selected":
                self.open_path(selected)
            elif action == "decompile_selected":
                self.decompile_single_binary(selected)
            elif action == "runtime_debug_selected":
                self.start_legacy_debug(selected, force_interrupt=False)
            elif action == "runtime_debug_interrupt_selected":
                self.start_legacy_debug(selected, force_interrupt=True)
            elif action == "archive_info":
                self.open_path(selected)
            elif action == "archive_extract":
                self.extract_archive(selected)
        elif rename_action is not None and chosen == rename_action:
            name, ok = QInputDialog.getText(self, "Rename", "New name:", text=selected.name)
            if ok and name and name != selected.name:
                target = selected.with_name(name)
                try:
                    selected_was_dir = selected.is_dir()
                    selected.rename(target)
                    for old_path in list(self.editors):
                        if old_path == selected or (selected_was_dir and selected in old_path.parents):
                            relative = old_path.relative_to(selected) if old_path != selected else Path()
                            new_path = (target / relative).resolve() if relative.parts else target.resolve()
                            editor = self.editors.pop(old_path)
                            self.lsp.close_document(old_path)
                            editor.file_path = new_path
                            self.editors[new_path] = editor
                            if new_path.suffix.lower() == ".gd":
                                self.lsp.open_document(new_path, editor.toPlainText())
                                editor._last_lsp_text = editor.toPlainText()
                            self.tabs.setTabToolTip(self.tabs.indexOf(editor), str(new_path))
                            self.mark_tab(editor)
                            self.dap.set_breakpoints(old_path, [])
                            self.dap.set_breakpoints(new_path, sorted(editor.breakpoints))
                    self.refresh_language_tools()
                except Exception as exc:
                    self.error(exc)
        elif delete_action is not None and chosen == delete_action:
            answer = QMessageBox.question(self, "Delete", f"Permanently delete {selected}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                try:
                    was_dir = selected.is_dir()
                    if was_dir:
                        shutil.rmtree(selected)
                    else:
                        selected.unlink()
                    for path in list(self.editors):
                        if path == selected or (was_dir and selected in path.parents):
                            editor = self.editors.pop(path)
                            self.lsp.close_document(path)
                            self.dap.set_breakpoints(path, [])
                            idx = self.tabs.indexOf(editor)
                            if idx >= 0:
                                self.tabs.removeTab(idx)
                            editor.deleteLater()
                    self.refresh_language_tools()
                except Exception as exc:
                    self.error(exc)
        elif chosen == copy_action:
            QApplication.clipboard().setText(str(selected))
        elif chosen == reveal_action:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(parent_dir)))

    def editor_changed(self, editor):
        self.mark_tab(editor)
        self.analysis_timer.start()

    def mark_tab(self, editor):
        index = self.tabs.indexOf(editor)
        if index >= 0:
            title = editor.file_path.name + (" •" if editor.document().isModified() else "")
            self.tabs.setTabText(index, title)

    def save_file(self):
        editor = self.current_editor()
        if not editor:
            return
        path = getattr(editor, "file_path", None)
        if not path:
            selected = QFileDialog.getSaveFileName(self, "Save file", str(self.project_root() or Path.home()), "GDScript (*.gd)")[0]
            if not selected:
                return
            path = Path(selected)
        try:
            path.write_text(editor.toPlainText(), encoding="utf-8")
            editor.file_path = path
            editor.document().setModified(False)
            self.mark_tab(editor)
            if path.suffix.lower() == ".gd":
                self.lsp.save_document(path, editor.toPlainText())
            self.statusBar().showMessage(f"Saved {path}")
            self.log(f"Saved file: {path}", category="FILE")
        except Exception as exc:
            self.error(exc)

    def autosave_modified(self):
        if self.settings.value("autosave", "true") != "true":
            return
        for editor in list(self.editors.values()):
            if editor.document().isModified() and getattr(editor, "file_path", None):
                try:
                    editor.file_path.write_text(editor.toPlainText(), encoding="utf-8")
                    editor.document().setModified(False)
                    self.mark_tab(editor)
                    if editor.file_path.suffix.lower() == ".gd":
                        self.lsp.save_document(editor.file_path, editor.toPlainText())
                except Exception as exc:
                    log_event("PYTHON", logging.ERROR, f"Autosave failed for {editor.file_path}: {exc}",
                              exc_info=(type(exc), exc, exc.__traceback__))

    def save_all(self):
        for editor in list(self.editors.values()):
            if editor.document().isModified():
                self.tabs.setCurrentWidget(editor)
                self.save_file()

    def close_tab(self, index):
        if index < 0:
            return
        widget = self.tabs.widget(index)
        if isinstance(widget, CodeEditor) and widget.document().isModified():
            answer = QMessageBox.question(self, "Unsaved changes", f"Save changes to {widget.file_path.name}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Yes:
                self.tabs.setCurrentIndex(index)
                self.save_file()
        if isinstance(widget, CodeEditor):
            path = getattr(widget, "file_path", None)
            if path:
                self.lsp.close_document(path)
                self.editors.pop(path, None)
        self.tabs.removeTab(index)
        widget.deleteLater()
        self.analysis_timer.start()

    def tab_changed(self, _):
        editor = self.current_editor()
        if editor:
            self.statusBar().showMessage(f"{editor.file_path}  |  Ln {editor.textCursor().blockNumber() + 1}, Col {editor.textCursor().positionInBlock() + 1}")
            self.analysis_timer.start()

    def find_in_editor(self):
        editor = self.current_editor()
        if not editor:
            return
        term, ok = QInputDialog.getText(self, "Find", "Find text:")
        if ok and term and not editor.find(term):
            QMessageBox.information(self, "Find", "No further matches found")

    def toggle_breakpoint(self):
        editor = self.current_editor()
        if editor:
            editor.toggle_breakpoint()
            self.right_tabs.setCurrentWidget(self.debug_tabs)
            self.debug_tabs.setCurrentWidget(self.breakpoints_view)

    def on_breakpoints_changed(self, editor, lines):
        self.update_breakpoints_view()
        if getattr(editor, "file_path", None) and editor.file_path.suffix.lower() == ".gd":
            self.dap.set_breakpoints(editor.file_path, lines)

    def update_breakpoints_view(self):
        self.breakpoints_view.clear()
        for path, editor in sorted(self.editors.items(), key=lambda row: str(row[0]).casefold()):
            for line in sorted(editor.breakpoints):
                item = QListWidgetItem(f"●  {path.name}:{line}  —  {path}")
                item.setData(Qt.ItemDataRole.UserRole, (str(path), line))
                self.breakpoints_view.addItem(item)

    def go_to_breakpoint_item(self, item):
        self._navigate_to_path_line(*item.data(Qt.ItemDataRole.UserRole))

    def go_to_outline_item(self, item):
        symbol = item.data(Qt.ItemDataRole.UserRole)
        editor = self.current_editor()
        if editor and symbol:
            self.go_to_line(editor, symbol.line, symbol.column)

    def go_to_problem_item(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self._navigate_to_path_line(*data)

    def _navigate_to_path_line(self, path, line, column=0):
        path = Path(path)
        editor = self.editors.get(path.resolve())
        if editor is None and path.exists() and path.is_file():
            self.open_path(path)
            editor = self.editors.get(path.resolve())
        if editor:
            self.tabs.setCurrentWidget(editor)
            self.go_to_line(editor, int(line), int(column))

    def go_to_line(self, editor, line, column=0):
        block = editor.document().findBlockByNumber(max(0, int(line) - 1))
        if block.isValid():
            cursor = editor.textCursor()
            cursor.setPosition(block.position() + min(max(0, int(column)), max(0, len(block.text()))))
            editor.setTextCursor(cursor)
            editor.setFocus()
            editor.centerCursor()

    def go_to_symbol(self):
        editor = self.current_editor()
        if not editor:
            return
        symbols = extract_symbols(editor.toPlainText())
        if not symbols:
            return
        labels = [f"{symbol.kind}: {symbol.detail}  —  line {symbol.line}" for symbol in symbols]
        value, ok = QInputDialog.getItem(self, "Go to Symbol", "Symbol:", labels, 0, False)
        if ok and value:
            idx = labels.index(value)
            self.go_to_line(editor, symbols[idx].line, symbols[idx].column)

    def refresh_language_tools(self):
        editor = self.current_editor()
        if not editor:
            self.outline.clear()
            self.problems.clear()
            return
        source = editor.toPlainText()
        symbols = extract_symbols(source)
        self.outline.clear()
        for symbol in symbols:
            item = QListWidgetItem(f"{symbol.kind:9} {symbol.detail}   Ln {symbol.line}")
            item.setData(Qt.ItemDataRole.UserRole, symbol)
            self.outline.addItem(item)
        if self.project_root():
            if not self.workspace_completions:
                self.workspace_completions = project_symbols(self.project_root())
        all_completions = set(self.workspace_completions)
        all_completions.update(symbol.name for symbol in symbols)
        all_completions.update(self.server_completions)
        editor.set_completions(all_completions, self.server_insertions)

        diagnostics = []
        for diag in analyze_gdscript(source):
            diagnostics.append((diag.severity, diag.line, diag.column + 1, diag.message))
        if getattr(editor, "file_path", None):
            server_rows = self.lsp_diagnostics.get(str(editor.file_path.resolve()), [])
            for row in server_rows:
                severity = {1: "Error", 2: "Warning", 3: "Info", 4: "Hint"}.get(row.get("severity", 3), "Info")
                start = row.get("range", {}).get("start", {})
                diagnostics.append((severity, int(start.get("line", 0)) + 1, int(start.get("character", 0)) + 1, row.get("message", "Godot diagnostic")))
            if editor.file_path.suffix.lower() == ".gd":
                if getattr(editor, "_last_lsp_text", None) != source:
                    self.lsp.change_document(editor.file_path, source)
                    editor._last_lsp_text = source
        self.problems.clear()
        diagnostic_path = str(getattr(editor, "file_path", "<untitled>"))
        current_diag_signatures = set()
        for severity, line, column, message in diagnostics:
            signature = (severity, line, column, message)
            current_diag_signatures.add(signature)
            if signature not in self._logged_diagnostics.get(diagnostic_path, set()):
                level = {"Error": logging.ERROR, "Warning": logging.WARNING, "Info": logging.INFO, "Hint": logging.DEBUG}.get(severity, logging.INFO)
                category = "GDSCRIPT" if getattr(editor, "file_path", None) and editor.file_path.suffix.lower() == ".gd" else "LOGIC"
                log_event(category, level, f"{diagnostic_path}:{line}:{column}: {message}")
        previous_diag_signatures = self._logged_diagnostics.get(diagnostic_path, set())
        for severity, line, column, message in previous_diag_signatures - current_diag_signatures:
            log_event("LOGIC", logging.INFO, f"Diagnostic cleared: {diagnostic_path}:{line}:{column}: {message}")
        self._logged_diagnostics[diagnostic_path] = current_diag_signatures
        for severity, line, column, message in sorted(diagnostics, key=lambda row: (row[1], row[2], row[0])):
            item = QListWidgetItem(f"{severity}: {line}:{column}  {message}")
            item.setData(Qt.ItemDataRole.UserRole, (str(editor.file_path), line, column))
            self.problems.addItem(item)
        self.statusBar().showMessage(f"{len(symbols)} symbols · {len(diagnostics)} diagnostics" + (" · Godot LSP connected" if self.lsp.ready else " · offline analysis"))

    def launch_godot_editor(self):
        root = self.project_root()
        if not root or not (root / "project.godot").exists():
            self.error("Open a Godot project folder containing project.godot first.")
            return
        godot = (self.data or {}).get("godot_executable") or self.settings.value("godot_path", "")
        if not godot or not Path(godot).exists():
            godot = QFileDialog.getOpenFileName(self, "Select Godot 4 editor executable", str(Path.home()), "Godot executable (*)")[0]
        if not godot:
            return
        lsp_port = int(self.settings.value("lsp_port", 6005))
        dap_port = int(self.settings.value("dap_port", 6006))
        args = ["--editor", "--path", str(root), "--lsp-port", str(lsp_port), "--dap-port", str(dap_port)]
        self.godot_process = QProcess(self)
        godot_proc = self.godot_process
        godot_proc.setWorkingDirectory(str(root))
        godot_proc.readyReadStandardOutput.connect(lambda p=godot_proc: self._drain_process(p, "GODOT_ENGINE", False))
        godot_proc.readyReadStandardError.connect(lambda p=godot_proc: self._drain_process(p, "GODOT_ENGINE_ERR", True))
        godot_proc.errorOccurred.connect(lambda error, p=godot_proc: self.log(f"Godot process error ({error}): {p.errorString()}", category="GODOT_ENGINE_ERR", level=logging.ERROR))
        godot_proc.finished.connect(lambda code, status, p=godot_proc: self._finish_godot_engine(p, code, status))
        godot_proc.start(godot, args)
        if not self.godot_process.waitForStarted(4000):
            self.error("Could not start Godot Editor: " + self.godot_process.errorString())
            return
        if self.data is not None:
            self.data["godot_executable"] = str(godot)
            if self.data.get("descriptor"):
                save_project(self.data)
        self.settings.setValue("godot_path", str(godot))
        self.log(f"Launched Godot Editor for {root}. LSP={lsp_port}, DAP={dap_port}.", category="GODOT_ENGINE")

    def connect_language_server(self):
        root = self.project_root()
        if not root:
            QMessageBox.information(self, "Godot Language Server", "Open a Godot project folder first.")
            return
        host = self.settings.value("lsp_host", "127.0.0.1")
        port = int(self.settings.value("lsp_port", 6005))
        self.lsp.connect_to_server(host, port, root)
        self.log(f"Connecting to Godot's GDScript LSP at {host}:{port}. Keep the Godot Editor open with this project loaded.", category="LSP")

    def on_lsp_status(self, message):
        self.statusBar().showMessage(message)
        self.log(message, category="LSP", level=logging.WARNING if "failed" in message.lower() or "error" in message.lower() else logging.INFO)

    def on_lsp_ready(self, ready):
        self.analysis_timer.start()

    def on_lsp_diagnostics(self, uri, diagnostics):
        path = Path(QUrl(uri).toLocalFile()).resolve()
        path_key = str(path)
        rows = list(diagnostics or [])
        self.lsp_diagnostics[path_key] = rows
        current = set()
        for row in rows:
            severity = {1: "Error", 2: "Warning", 3: "Info", 4: "Hint"}.get(row.get("severity", 3), "Info")
            start = row.get("range", {}).get("start", {})
            line = int(start.get("line", 0)) + 1
            column = int(start.get("character", 0)) + 1
            message = str(row.get("message", "Godot diagnostic"))
            signature = (severity, line, column, message)
            current.add(signature)
            if signature not in self._last_lsp_diagnostics.get(path_key, set()):
                level = {"Error": logging.ERROR, "Warning": logging.WARNING, "Info": logging.INFO, "Hint": logging.DEBUG}.get(severity, logging.INFO)
                log_event("GDSCRIPT", level, f"Godot LSP {path}:{line}:{column}: {message}")
        for severity, line, column, message in self._last_lsp_diagnostics.get(path_key, set()) - current:
            log_event("LOGIC", logging.INFO, f"Godot diagnostic cleared: {path}:{line}:{column}: {message}")
        self._last_lsp_diagnostics[path_key] = current
        self.analysis_timer.start()

    def on_lsp_completions(self, items):
        current = self.current_editor()
        words = []
        insertions = {}
        for item in items:
            if isinstance(item, str):
                label = item
                insert_text = item
            elif isinstance(item, dict):
                label = str(item.get("label", ""))
                insert_text = item.get("insertText") or label
                text_edit = item.get("textEdit")
                if isinstance(text_edit, dict):
                    insert_text = text_edit.get("newText", insert_text)
                # Keep snippets conservative until snippet expansion is implemented.
                insert_text = str(insert_text).replace("$0", "")
            else:
                continue
            if label:
                words.append(label)
                insertions[label] = insert_text
        self.server_completions = words
        self.server_insertions = insertions
        if current:
            combined = set(self.workspace_completions) | set(words)
            combined.update(symbol.name for symbol in extract_symbols(current.toPlainText()))
            current.set_completions(combined, insertions)
        self.statusBar().showMessage(f"Godot returned {len(words)} completion items")

    def request_completion(self, editor, line, column):
        if not self.lsp.ready:
            self.statusBar().showMessage("Connect to Godot LSP for semantic completion; local symbols remain available")
            return
        self.lsp.request_completion(editor.file_path, line, column)

    def add_watch(self):
        expression = self.watch_input.text().strip()
        if not expression:
            return
        existing = [self.watch_view.item(i).text() for i in range(self.watch_view.count())]
        if expression not in existing:
            item = QListWidgetItem(expression)
            item.setData(Qt.ItemDataRole.UserRole, expression)
            self.watch_view.addItem(item)
        self.watch_input.clear()
        if self.dap.frame_id is not None:
            self.dap.evaluate(expression)

    def remove_watch(self):
        row = self.watch_view.currentRow()
        if row >= 0:
            self.watch_view.takeItem(row)

    def evaluate_selected_watch(self, item):
        expression = item.data(Qt.ItemDataRole.UserRole) or item.text()
        self.dap.evaluate(expression)

    def evaluate_watch_expression(self):
        expression = self.console_input.text().strip()
        if not expression:
            return
        if self.legacy_debug_active and self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            # The OpenGDS runtime debugger forwards stdin to Godot's local
            # debugger prompt (continue, step, stack, locals, etc.).
            self.process.write((expression + "\n").encode("utf-8"))
            self.log(f"Sent command to Godot local debugger: {expression}", category="GODOT_DEBUG")
        elif self.dap.frame_id is not None:
            self.dap.evaluate(expression)
        else:
            self.log("No paused Godot DAP or local-debug session is active", category="DAP", level=logging.WARNING)
        self.console_input.clear()

    def on_dap_status(self, message):
        self.statusBar().showMessage(message)
        self.log(message, category="DAP", level=logging.WARNING if "failed" in message.lower() or "error" in message.lower() else logging.INFO)

    def on_debug_stopped(self, body):
        self.log(f"Paused: {body.get('reason', 'breakpoint')} — {body.get('description', '')}", category="GODOT_DEBUG")
        self.right_tabs.setCurrentWidget(self.debug_tabs)
        self.debug_tabs.setCurrentWidget(self.call_stack_view)

    def on_debug_continued(self):
        self.statusBar().showMessage("Godot execution running")
        self.log("Godot resumed execution", category="GODOT_DEBUG")

    def on_debug_terminated(self):
        self.statusBar().showMessage("Godot debug session ended")
        self.log("Godot debug session terminated", category="GODOT_DEBUG")

    def populate_stack(self, frames):
        log_event("DAP", logging.DEBUG, f"Received {len(frames)} stack frame(s)")
        self.call_stack_view.clear()
        for frame in frames:
            source = frame.get("source") or {}
            path = source.get("path", "")
            line = int(frame.get("line", 1))
            name = frame.get("name", "<anonymous>")
            item = QListWidgetItem(f"{name}  —  {Path(path).name if path else '<built-in>'}:{line}")
            if path:
                item.setData(Qt.ItemDataRole.UserRole, (path, line, 0))
            self.call_stack_view.addItem(item)
        # Refresh watch expressions against the newly selected top stack frame.
        for index in range(self.watch_view.count()):
            expression = self.watch_view.item(index).data(Qt.ItemDataRole.UserRole) or self.watch_view.item(index).text()
            self.dap.evaluate(expression)

    def populate_variables(self, variables):
        log_event("DAP", logging.DEBUG, f"Received {len(variables)} debugger variable(s)")
        self.variables_view.clear()
        for variable in variables:
            name = variable.get("name", "?")
            value = variable.get("value", "")
            kind = variable.get("type", "")
            scope = variable.get("_scope", "")
            label = (f"[{scope}] " if scope else "") + f"{name} = {value}" + (f"  ({kind})" if kind else "")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, int(variable.get("variablesReference", 0) or 0))
            self.variables_view.addItem(item)

    def expand_variable_item(self, item):
        reference = item.data(Qt.ItemDataRole.UserRole)
        if reference:
            self.dap.request_variables(reference)

    def go_to_stack_item(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self._navigate_to_path_line(*data)

    def stop_debug(self):
        self.dap.stop()
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            if os.name == "nt" and self.process.processId():
                subprocess.run(["taskkill", "/PID", str(int(self.process.processId())), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            else:
                self.process.terminate()
                if not self.process.waitForFinished(2000):
                    self.process.kill()
            self.legacy_debug_active = False

    def start_debug(self):
        root = self.project_root()
        if not root or not (root / "project.godot").exists():
            selected = QFileDialog.getExistingDirectory(self, "Choose Godot project directory (contains project.godot)", str(root or Path.home()))
            if not selected:
                return
            root = Path(selected).resolve()
            if not (root / "project.godot").exists():
                self.error("The selected folder does not contain project.godot")
                return
        breakpoints = {}
        for path, editor in self.editors.items():
            if path.suffix.lower() == ".gd" and editor.breakpoints:
                breakpoints[str(path)] = sorted(editor.breakpoints)
        cfg = (self.data or {}).get("debug", {})
        host = self.settings.value("dap_host", "127.0.0.1")
        port = int(self.settings.value("dap_port", 6006))
        remote_port = int(self.settings.value("godot_remote_port", 6007))
        self.output_dock.show()
        self.right_tabs.setCurrentWidget(self.debug_tabs)
        self.log("Starting native Godot DAP session. Godot Editor must be open with this project and Debug Adapter enabled.", category="DAP")
        self.dap.connect_to_server(host, port, root, breakpoints, scene=cfg.get("scene", ""), remote_port=remote_port)

    def start_legacy_debug(self, selected=None, force_interrupt=None):
        """Use the OpenGDS core's --godot / --interrupt runtime debugger.

        A selected .gd is first serialized to a raw GDSC cache file (no zstd
        dependency), while the --source-path continues to point at the real
        res:// script so Godot's runtime breakpoint source mapping is correct.
        """
        try:
            backend = self.ensure_backend()
            if selected is None:
                selected = QFileDialog.getOpenFileName(
                    self, "Select GDScript or compiled GDSC to debug",
                    str(self.project_root() or Path.home()),
                    "GDScript / GDSC (*.gd *.gdc);;All files (*)",
                )[0]
                if not selected:
                    return
            selected = Path(selected).expanduser().resolve()
            if selected.suffix.lower() not in {".gd", ".gdc"}:
                raise ValueError("OpenGDS runtime debug requires a .gd source or .gdc compiled script")

            project = self.project_root()
            if not project or not (project / "project.godot").is_file():
                chosen = QFileDialog.getExistingDirectory(self, "Choose Godot project folder (contains project.godot)", str(selected.parent))
                if not chosen:
                    return
                project = Path(chosen).resolve()
            if not (project / "project.godot").is_file():
                raise FileNotFoundError(f"Godot runtime debugging requires project.godot: {project}")

            cfg = (self.data or {}).get("debug", {})
            source_path = cfg.get("source_path", "").strip()
            editor_for_script = None
            if selected.suffix.lower() == ".gd":
                try:
                    relative = selected.relative_to(project).as_posix()
                except ValueError:
                    raise ValueError("The selected .gd script must be inside the selected Godot project")
                source_path = source_path or ("res://" + relative)
                editor_for_script = self.editors.get(selected)
                if editor_for_script and editor_for_script.document().isModified():
                    self.save_file()
                cache_root = project / ".opengds" / "debug-cache"
                cache_binary = cache_root / Path(relative).with_suffix(".gdc")
                cache_binary.parent.mkdir(parents=True, exist_ok=True)
                # Raw GDSC avoids depending on the native Zstandard library for
                # an internal, temporary debugger artifact.
                backend.compile(selected, cache_binary, compressed=False, overwrite=True,
                                tab_size=int((self.data or {}).get("compile", {}).get("tab_size", 4)))
                binary = cache_binary
            else:
                binary = selected
                if not source_path:
                    try:
                        relative = selected.relative_to(project).as_posix()
                        source_path = "res://" + str(Path(relative).with_suffix(".gd")).replace("\\", "/")
                    except ValueError:
                        raise ValueError("For a .gdc outside the Godot project, set Debug → Source override (res://...) in Settings")
                editor_path = project / source_path.removeprefix("res://")
                editor_for_script = self.editors.get(editor_path.resolve())

            godot = (self.data or {}).get("godot_executable") or self.settings.value("godot_path", "")
            if not godot:
                import shutil as _shutil
                godot = _shutil.which("godot") or _shutil.which("godot4") or ""
            if not godot or (Path(str(godot)).suffix and not Path(str(godot)).exists()):
                godot = QFileDialog.getOpenFileName(self, "Select Godot executable", str(Path.home()), "Godot executable (*)")[0]
            if not godot:
                return
            breakpoints = sorted(editor_for_script.breakpoints) if editor_for_script else []
            interrupt_enabled = bool(cfg.get("interrupt", False) if force_interrupt is None else force_interrupt)
            # OpenGDS's CLI requires recurring callbacks to be explicitly paired
            # with --interrupt. A stale settings checkbox must not break a normal
            # --godot runtime-debug launch.
            include_frames = interrupt_enabled and bool(cfg.get("include_frame_callbacks", False))
            args = backend.runtime_debug_command(
                binary, str(godot), str(project), breakpoints,
                interrupt=interrupt_enabled,
                scene=cfg.get("scene", ""), headless=bool(cfg.get("headless", False)),
                source_path=source_path, include_frame_callbacks=include_frames,
                extra_args=cfg.get("extra_args", []), dry_run=bool(cfg.get("dry_run", False)),
            )
            if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
                raise RuntimeError("An OpenGDS runtime-debug process is already active; stop it first")
            self.log("Starting OpenGDS core runtime debugger (--godot).\n" + subprocess.list2cmdline(args), category="GODOT_DEBUG")
            self.output_dock.show()
            core_log_path = log_directory() / "core.log"
            core_log_offset = core_log_path.stat().st_size if core_log_path.exists() else 0
            self.process = QProcess(self)
            core_proc = self.process
            core_proc.setWorkingDirectory(str(project))
            core_proc.readyReadStandardOutput.connect(lambda p=core_proc: self._drain_process(p, "GODOT_DEBUG", False))
            core_proc.readyReadStandardError.connect(lambda p=core_proc: self._drain_process(p, "GODOT_ENGINE_ERR", True))
            core_proc.errorOccurred.connect(lambda error, p=core_proc: self.log(f"OpenGDS/Godot debug process error ({error}): {p.errorString()}", category="PYTHON", level=logging.ERROR))
            core_proc.finished.connect(lambda code, status, p=core_proc, path=core_log_path, offset=core_log_offset: self._finish_legacy_debug(p, path, offset, code, status))
            core_proc.start(args[0], args[1:])
            if not core_proc.waitForStarted(5000):
                raise RuntimeError("Could not start OpenGDS runtime debugger: " + core_proc.errorString())
            self.legacy_debug_active = True
            if self.data is not None:
                self.data["godot_executable"] = str(godot)
                if self.data.get("descriptor"):
                    save_project(self.data)
            self.settings.setValue("godot_path", str(godot))
            self.statusBar().showMessage("OpenGDS --godot runtime debugger started")
        except Exception as exc:
            self.error(exc)

    def start_legacy_debug_interrupt(self, selected=None):
        self.start_legacy_debug(selected, force_interrupt=True)

    def log(self, message, category="GUI", level=logging.INFO, exc_info=None):
        """Write a categorized event to disk and to the color-coded log viewer."""
        if message is None or str(message) == "":
            return
        for line in str(message).rstrip().splitlines() or [str(message)]:
            resolved_category = category
            upper = line.upper()
            if category in {"GODOT_ENGINE", "GODOT_ENGINE_ERR", "GODOT_DEBUG"}:
                if "TRACEBACK (MOST RECENT CALL LAST)" in upper or "PYTHON EXCEPTION" in upper:
                    resolved_category = "PYTHON"
                elif any(token in upper for token in ("GDSC ERROR", "INVALID GDSC", "GDSC DECOD", ".GDC:", "TOKEN STREAM ERROR")):
                    resolved_category = "GDSC"
                elif any(token in upper for token in ("SCRIPT ERROR", "PARSE ERROR", "PARSER ERROR", "SCRIPT FAILED", ".GD:", "GDSCRIPT ERROR", "GDSCRIPT WARNING", "INVALID CALL", "INVALID GET INDEX", "UNUSED VARIABLE", "UNUSED PARAMETER")):
                    resolved_category = "GDSCRIPT"
            log_event(resolved_category, level, line, exc_info=exc_info)
        self.output_dock.show()

    def render_log_record(self, record):
        category = getattr(record, "category", "SYSTEM")
        self.log_records.append(record)
        if len(self.log_records) > 12000:
            self.log_records = self.log_records[-12000:]
        if self._log_record_matches(record, self.log_filter.currentText()):
            self._append_log_record(record)

    def _append_log_record(self, record):
        category = getattr(record, "category", "SYSTEM")
        color = CATEGORY_COLORS.get(category, CATEGORY_COLORS["SYSTEM"])
        rendered = self.log_formatter.format(record)
        safe = html.escape(rendered).replace("\n", "<br>")
        self.output.moveCursor(QTextCursor.MoveOperation.End)
        self.output.insertHtml(f'<span style="color:{color}; white-space:pre-wrap">{safe}</span><br>')
        self.output.moveCursor(QTextCursor.MoveOperation.End)

    def _log_record_matches(self, record, category):
        record_category = getattr(record, "category", "SYSTEM")
        if category != "All categories" and category != record_category:
            return False
        query = self.log_search.text().strip().casefold()
        return not query or query in record.getMessage().casefold()

    def apply_log_filter(self, category):
        self.output.clear()
        for record in self.log_records:
            if self._log_record_matches(record, category):
                self._append_log_record(record)

    def clear_log_view(self):
        self.log_records.clear()
        self.output.clear()
        log_event("GUI", logging.INFO, "Log viewer cleared; files on disk were not deleted")

    def open_logs_folder(self):
        folder = log_directory()
        folder.mkdir(parents=True, exist_ok=True)
        log_event("GUI", logging.INFO, f"Opening log directory: {folder}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _finish_godot_engine(self, process, code, status):
        self._drain_process(process, "GODOT_ENGINE", False)
        self._drain_process(process, "GODOT_ENGINE_ERR", True)
        self.log(f"Godot Editor exited with code {code} ({status})", category="GODOT_ENGINE",
                 level=logging.INFO if code == 0 else logging.WARNING)

    def _finish_legacy_debug(self, process, core_log_path, core_log_offset, code, status):
        self.legacy_debug_active = False
        if process:
            self._drain_process(process, "GODOT_DEBUG", False)
            self._drain_process(process, "GODOT_ENGINE_ERR", True)
        OpenGDSBackend._merge_core_log(core_log_path, core_log_offset)
        self.log(f"Legacy OpenGDS debugger exited with code {code} ({status})",
                 category="GODOT_DEBUG", level=logging.INFO if code == 0 else logging.ERROR)

    def _drain_process(self, process, category, is_error):
        data = process.readAllStandardError() if is_error else process.readAllStandardOutput()
        text = bytes(data).decode("utf-8", errors="replace")
        if text:
            self.log(text, category=category, level=logging.ERROR if is_error else logging.INFO)

    def qt_message_handler(self, mode, context, message):
        mode_name = str(mode).lower()
        level = logging.ERROR if "critical" in mode_name or "fatal" in mode_name else logging.WARNING if "warning" in mode_name else logging.DEBUG
        category = "GUI" if level < logging.ERROR else "PYTHON"
        log_event(category, level, f"Qt message ({mode_name}): {message} [file={getattr(context, 'file', '')}, line={getattr(context, 'line', 0)}]")

    def choose_backend_file(self, suffixes=(".gd", ".gdc"), title=None):
        start = str(self.project_root() or Path.home())
        suffixes = tuple(suffix.lower() for suffix in suffixes)
        label = "GDScript (*.gd)" if suffixes == (".gd",) else "GDSC (*.gdc)" if suffixes == (".gdc",) else "GDScript / GDSC (*.gd *.gdc)"
        path = QFileDialog.getOpenFileName(self, title or "Select file", start, label + ";;All files (*)")[0]
        return Path(path).resolve() if path else None

    def run_background(self, label, function, on_result=None):
        self.statusBar().showMessage(label + "…")
        self.log(label + " started", category="BUILD")
        worker = FunctionWorker(function, self)
        self._workers.add(worker)
        if on_result:
            worker.resultReady.connect(on_result)
        worker.errorRaised.connect(self.error)
        worker.finished.connect(lambda w=worker: self._workers.discard(w))
        worker.start()
        return worker

    def show_operation_summary(self, summary):
        report = summary.report() if hasattr(summary, "report") else str(summary)
        self.show_report_tab(getattr(summary, "mode", "Operation") + " — Results", report)
        success = len(getattr(summary, "succeeded", []))
        failed = len(getattr(summary, "failed", []))
        skipped = len(getattr(summary, "skipped", []))
        self.log(f"{getattr(summary, 'mode', 'Operation')} finished: {success} succeeded, {failed} failed, {skipped} skipped", category="BUILD", level=logging.ERROR if failed else logging.INFO)
        self.statusBar().showMessage(f"Operation complete · {success} succeeded · {failed} failed · {skipped} skipped")

    def _compile_config(self):
        cfg = (self.data or {}).get("compile", {})
        return {
            "compressed": bool(cfg.get("compressed", True)),
            "overwrite": bool(cfg.get("overwrite", False)),
            "continue_on_error": bool(cfg.get("continue_on_error", True)),
            "tab_size": int(cfg.get("tab_size", 4)),
            "validate_with_godot": bool(cfg.get("validate_with_godot", True)),
        }

    def compile_single_source(self, source=None):
        try:
            source = Path(source).resolve() if source else self.choose_backend_file((".gd",), "Compile GDScript source")
            if not source:
                return
            if source.suffix.lower() != ".gd":
                raise ValueError("Select a .gd GDScript source file to compile")
            editor = self.editors.get(source)
            if editor and editor.document().isModified():
                self.tabs.setCurrentWidget(editor)
                self.save_file()
            output = source.with_suffix(".gdc")
            cfg = self._compile_config()
            overwrite = cfg["overwrite"]
            if output.exists() and not overwrite:
                answer = QMessageBox.question(self, "Replace compiled file?", f"{output} already exists. Replace it?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return
                overwrite = True
            backend = self.ensure_backend()
            def work():
                return backend.compile(source, output, compressed=cfg["compressed"], overwrite=overwrite,
                                       tab_size=cfg["tab_size"], continue_on_error=cfg["continue_on_error"])
            def completed(result):
                self.log(result.stdout or f"Compiled {source} → {output}", category="GDSCRIPT")
                self.show_report_tab(f"Compile — {source.name}", result.stdout or f"Compiled successfully:\n{output}", source)
                self.statusBar().showMessage(f"Compiled: {output}")
            self.run_background(f"Compile {source.name} with OpenGDS", work, completed)
        except Exception as exc:
            self.error(exc)

    def decompile_single_binary(self, binary=None):
        try:
            binary = Path(binary).resolve() if binary else self.choose_backend_file((".gdc",), "Decompile GDSC binary")
            if not binary:
                return
            if binary.suffix.lower() != ".gdc":
                raise ValueError("Decompilation requires a .gdc GDSC binary")
            output = binary.with_suffix(".gd")
            if output.exists():
                selected = QFileDialog.getSaveFileName(self, "Save reconstructed GDScript", str(output), "GDScript (*.gd)")[0]
                if not selected:
                    return
                output = Path(selected).resolve()
                if output.exists():
                    answer = QMessageBox.question(self, "Overwrite source?", f"Replace {output}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                    if answer != QMessageBox.StandardButton.Yes:
                        return
            backend = self.ensure_backend()
            def work():
                source = backend.decompile(binary)
                output.parent.mkdir(parents=True, exist_ok=True)
                temp = output.with_name(output.name + ".opengds-tmp")
                try:
                    temp.write_text(source, encoding="utf-8", newline="\n")
                    os.replace(temp, output)
                finally:
                    if temp.exists():
                        temp.unlink()
                return source
            def completed(source):
                self.log(f"Decompiled {binary} → {output}", category="GDSC")
                self.open_path(output)
                self.statusBar().showMessage(f"Decompiled: {output}")
            self.run_background(f"Decompile {binary.name} with OpenGDS", work, completed)
        except Exception as exc:
            self.error(exc)

    def _choose_project_root(self):
        root = self.project_root()
        if root and root.is_dir():
            return root
        chosen = QFileDialog.getExistingDirectory(self, "Choose project folder", str(Path.home()))
        return Path(chosen).resolve() if chosen else None

    def _output_root(self, key, default_relative):
        root = self._choose_project_root()
        if not root:
            return None
        cfg = (self.data or {}).setdefault("compile", {})
        relative = cfg.get(key, default_relative)
        default_path = root / relative
        chosen = QFileDialog.getExistingDirectory(self, "Choose output folder", str(default_path.parent if default_path.exists() else root))
        if not chosen:
            return None
        return Path(chosen).resolve()

    def _start_project_compile(self, root, output_root):
        cfg = self._compile_config()
        backend = self.ensure_backend()
        def work():
            return compile_project(backend, root, output_root,
                compressed=cfg["compressed"], overwrite=cfg["overwrite"],
                tab_size=cfg["tab_size"], continue_on_error=cfg["continue_on_error"])
        def completed(summary):
            self.show_operation_summary(summary)
            if summary.succeeded and not summary.failed and cfg.get("validate_with_godot", False) and (Path(root) / "project.godot").is_file():
                godot = self.find_godot(prompt=False)
                if godot:
                    answer = QMessageBox.question(self, "Run Godot validation?",
                        "OpenGDS compilation completed. Run Godot's --check-only parser validation over the project now?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                    if answer == QMessageBox.StandardButton.Yes:
                        self.run_background("Validate compiled project sources with Godot", lambda: godot_validate_project(godot, root), self.show_operation_summary)
                else:
                    self.log("Godot validation was enabled but no Godot executable was detected; OpenGDS compile completed without engine validation.", category="SYSTEM", level=logging.WARNING)
        self.run_background("Compile entire project with OpenGDS", work, completed)

    def _start_project_decompile(self, root, output_root):
        cfg = self._compile_config()
        configured_output = (self.data or {}).get("compile", {}).get("output_directory", ".opengds/compiled")
        compiled_root = Path(configured_output).expanduser()
        if not compiled_root.is_absolute():
            compiled_root = Path(root) / compiled_root
        def work():
            return decompile_project(self.ensure_backend(), root, output_root,
                overwrite=cfg["overwrite"], continue_on_error=cfg["continue_on_error"],
                compiled_root=compiled_root)
        self.run_background("Decompile all project GDSC with OpenGDS", work, self.show_operation_summary)

    def find_godot(self, prompt=True):
        godot = (self.data or {}).get("godot_executable") or self.settings.value("godot_path", "")
        if godot and (Path(str(godot)).exists() or shutil.which(str(godot))):
            return str(godot)
        godot = shutil.which("godot") or shutil.which("godot4") or ""
        if godot:
            return godot
        if prompt:
            chosen = QFileDialog.getOpenFileName(self, "Select Godot executable", str(Path.home()), "Godot executable (*)")[0]
            if chosen:
                self.settings.setValue("godot_path", chosen)
                if self.data is not None:
                    self.data["godot_executable"] = chosen
                    if self.data.get("descriptor"):
                        save_project(self.data)
                return chosen
        return ""

    def validate_current_script_with_godot(self, selected=None):
        source = Path(selected).resolve() if selected else None
        if source is None:
            editor = self.current_editor()
            source = editor.file_path if editor and editor.file_path.suffix.lower() == ".gd" else self.choose_backend_file((".gd",), "Choose GDScript file to validate with Godot")
        if not source:
            return
        if source.suffix.lower() != ".gd":
            self.error("Godot --check-only validation accepts a .gd source file")
            return
        root = self.project_root()
        if not root or not (root / "project.godot").is_file():
            self.error("Godot script validation requires an open project containing project.godot. Open project.godot or its folder first.")
            return
        if source not in self.editors:
            self.open_path(source)
        editor = self.editors.get(source)
        if editor and editor.document().isModified():
            self.tabs.setCurrentWidget(editor)
            self.save_file()
        godot = self.find_godot()
        if not godot:
            return
        try:
            command = godot_check_command(godot, root, source)
        except Exception as exc:
            self.error(exc)
            return
        def work():
            completed = subprocess.run(command, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", timeout=120, check=False, shell=False)
            summary = OperationSummary(f"Godot --check-only validation: {source.name}")
            if completed.returncode == 0:
                summary.succeeded.append(source)
                summary.notes.append((completed.stdout or "Godot parsed the script without reporting errors.").strip())
            else:
                summary.failed.append((source, (completed.stdout or f"Godot exited with code {completed.returncode}").strip()))
            return summary
        self.run_background(f"Godot --check-only {source.name}", work, self.show_operation_summary)

    def run_custom_core_command(self):
        import shlex
        raw, ok = QInputDialog.getText(self, "Advanced OpenGDS CLI", "OpenGDS arguments (example: info \"path\\with spaces\\file.gdc\"):")
        if not ok or not raw.strip():
            return
        try:
            args = shlex.split(raw, posix=(os.name != "nt"))
            if os.name == "nt":
                args = [part.strip('"') for part in args]
            if not args:
                return
            backend = self.ensure_backend()
            def work():
                result = backend.run(*args)
                return result.stdout or f"OpenGDS command completed successfully: {args!r}"
            tab = self.show_report_tab("OpenGDS CLI — Running", "Running: " + subprocess.list2cmdline(args))
            self.run_background("Custom OpenGDS core command", work,
                lambda output: (tab.report_text.setPlainText(output), self.tabs.setTabText(self.tabs.indexOf(tab), "OpenGDS CLI — Result")))
        except Exception as exc:
            self.error(exc)

    def run_custom_godot_command(self):
        """Run arbitrary Godot CLI arguments without shell interpolation."""
        import shlex
        godot = self.find_godot()
        if not godot:
            return
        raw, ok = QInputDialog.getText(
            self, "Custom Godot CLI",
            "Godot arguments (example: --headless --import or --doctool docs/api):",
        )
        if not ok or not raw.strip():
            return
        try:
            args = shlex.split(raw, posix=(os.name != "nt"))
            if os.name == "nt":
                args = [part.strip('"') for part in args]
            root = self.project_root()
            if root and (root / "project.godot").is_file() and not any(
                arg == "--path" or arg.startswith("--path=") for arg in args
            ):
                args = ["--path", str(root), *args]
            cwd = root if root and root.is_dir() else Path.cwd()
            self._run_godot_process(godot, args, cwd, "Custom Godot CLI command")
            self.log("Custom Godot CLI: " + subprocess.list2cmdline([godot, *args]), category="GODOT_ENGINE")
        except Exception as exc:
            self.error(exc)

    def validate_project_with_godot(self):
        root = self._choose_project_root()
        if not root:
            return
        if not (root / "project.godot").is_file():
            self.error("Godot validation requires a real project.godot file. .ogds is an IDE workspace descriptor, not a replacement for Godot's project file.")
            return
        godot = self.find_godot()
        if not godot:
            return
        self.run_background("Validate project scripts with Godot --check-only", lambda: godot_validate_project(godot, root), self.show_operation_summary)

    def run_godot_project(self, debug=False):
        root = self._choose_project_root()
        if not root:
            return
        if not (root / "project.godot").is_file():
            self.error("Running a Godot project requires project.godot. Use OpenGDS compiler features for a plain source folder without it.")
            return
        godot = self.find_godot()
        if not godot:
            return
        if self.godot_process and self.godot_process.state() != QProcess.ProcessState.NotRunning:
            self.error("A Godot process is already running. Stop or close it first.")
            return
        args = ["--path", str(root)]
        if debug:
            args.insert(0, "--debug")
            # Godot's CLI accepts source::line pairs for local runtime
            # breakpoints. Preserve spaces using percent-encoding as required
            # by the engine's command-line parser.
            from urllib.parse import quote
            breakpoint_pairs = []
            for source_path, editor in self.editors.items():
                if source_path.suffix.lower() != ".gd" or not editor.breakpoints:
                    continue
                try:
                    resource_path = "res://" + source_path.relative_to(root).as_posix()
                except ValueError:
                    continue
                encoded = quote(resource_path, safe="/._-:")
                breakpoint_pairs.extend(f"{encoded}::{line}" for line in sorted(editor.breakpoints))
            if breakpoint_pairs:
                args.append("--breakpoints=" + ",".join(breakpoint_pairs))
        cfg = (self.data or {}).get("debug", {})
        if cfg.get("scene"):
            args.append(cfg["scene"])
        self.godot_process = QProcess(self)
        proc = self.godot_process
        proc.setWorkingDirectory(str(root))
        proc.readyReadStandardOutput.connect(lambda p=proc: self._drain_process(p, "GODOT_DEBUG" if debug else "GODOT_ENGINE", False))
        proc.readyReadStandardError.connect(lambda p=proc: self._drain_process(p, "GODOT_ENGINE_ERR", True))
        proc.errorOccurred.connect(lambda error, p=proc: self.log(f"Godot launch error ({error}): {p.errorString()}", category="PYTHON", level=logging.ERROR))
        proc.finished.connect(lambda code, status, p=proc: self._finish_godot_engine(p, code, status))
        proc.start(godot, args)
        if not proc.waitForStarted(5000):
            self.error("Could not start Godot: " + proc.errorString())
            return
        if self.data is not None:
            self.data["godot_executable"] = godot
            if self.data.get("descriptor"):
                save_project(self.data)
        self.log(f"Started Godot project ({'--debug' if debug else 'normal'}) at {root}", category="GODOT_ENGINE")

    def godot_import_project(self):
        root = self._choose_project_root()
        if not root:
            return
        if not (root / "project.godot").is_file():
            self.error("Godot project import requires project.godot")
            return
        godot = self.find_godot()
        if not godot:
            return
        # This invokes Godot's editor/import pipeline; it does not produce a
        # standalone .gdc file. OpenGDS remains the GDSC serializer/compiler.
        self._run_godot_process(godot, ["--headless", "--path", str(root), "--import"], root,
                                "Godot headless project import")

    def create_project_zip(self):
        root = self._choose_project_root()
        if not root:
            return
        suggested = root.parent / (root.name + "-project.zip")
        output = QFileDialog.getSaveFileName(self, "Create project ZIP snapshot", str(suggested), "ZIP archive (*.zip)")[0]
        if not output:
            return
        from archive_tools import create_project_zip
        try:
            archive = create_project_zip(root, output)
            self.show_report_tab("Project ZIP Snapshot", f"Created: {archive}\nSource: {root}\n\nExcluded IDE caches, .godot editor cache, .git, .venv and __pycache__.")
            self.log(f"Created project ZIP snapshot: {archive}", category="ARCHIVE")
        except Exception as exc:
            self.error(exc)

    def godot_export(self, mode="pack"):
        root = self._choose_project_root()
        if not root:
            return
        if not (root / "project.godot").is_file():
            self.error("Godot export requires project.godot")
            return
        presets_file = root / "export_presets.cfg"
        if not presets_file.is_file():
            self.error("No export_presets.cfg was found. Create an export preset in Godot Editor first.")
            return
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(presets_file, encoding="utf-8")
        presets = []
        for section in parser.sections():
            if section.startswith("preset."):
                name = parser.get(section, "name", fallback=section).strip().strip('"')
                presets.append((section, name))
        if not presets:
            self.error("No [preset.N] entries were found in export_presets.cfg")
            return
        labels = [name for _, name in presets]
        selected, ok = QInputDialog.getItem(self, "Choose export preset", "Godot preset:", labels, 0, False)
        if not ok:
            return
        preset_name = selected
        suffix = ".pck" if mode == "pack" else ".exe" if os.name == "nt" else ".x86_64"
        default_out = root / "build" / (root.name + (".pck" if mode == "pack" else suffix))
        output, _ = QFileDialog.getSaveFileName(self, "Export with Godot", str(default_out), "Godot PCK (*.pck);;All files (*)" if mode == "pack" else "All files (*)")
        if not output:
            return
        option = {"pack": "--export-pack", "debug": "--export-debug", "release": "--export-release"}.get(mode)
        if not option:
            self.error(f"Unknown Godot export mode: {mode}")
            return
        godot = self.find_godot()
        if not godot:
            return
        output_path = Path(output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        args = ["--headless", "--path", str(root), option, preset_name, str(output_path)]
        self._run_godot_process(godot, args, root, f"Godot {mode} export")

    def _run_godot_process(self, executable, args, cwd, label):
        if self.godot_process and self.godot_process.state() != QProcess.ProcessState.NotRunning:
            self.error("A Godot process is already running. Stop it first.")
            return
        self.godot_process = QProcess(self)
        proc = self.godot_process
        proc.setWorkingDirectory(str(cwd))
        proc.readyReadStandardOutput.connect(lambda p=proc: self._drain_process(p, "GODOT_ENGINE", False))
        proc.readyReadStandardError.connect(lambda p=proc: self._drain_process(p, "GODOT_ENGINE_ERR", True))
        proc.errorOccurred.connect(lambda error, p=proc: self.log(f"{label} process error ({error}): {p.errorString()}", category="PYTHON", level=logging.ERROR))
        proc.finished.connect(lambda code, status, p=proc: self._finish_godot_engine(p, code, status))
        proc.start(executable, args)
        if not proc.waitForStarted(5000):
            self.error(f"Could not start {label}: " + proc.errorString())
            return
        self.log(f"Started {label}: {subprocess.list2cmdline([executable, *args])}", category="GODOT_ENGINE")

    def extract_archive(self, path=None):
        if path is None:
            path = QFileDialog.getOpenFileName(self, "Select Godot PCK / executable / ZIP / APK", str(self.project_root() or Path.home()), "Archives (*.pck *.exe *.bin *.x86_64 *.linux *.linuxbsd *.macos *.dll *.so *.dylib *.zip *.apk);;All files (*)")[0]
            if not path:
                return
        path = Path(path).resolve()
        destination = QFileDialog.getExistingDirectory(self, "Choose extraction folder", str(path.parent / (path.stem + "_extracted")))
        if not destination:
            return
        try:
            if looks_like_pck_or_executable(path):
                result = extract_pck(read_pck(path), destination)
            else:
                result = extract_zip(path, destination)
            report = (f"Archive extraction\nSource: {path}\nDestination: {destination}\n"
                      f"Extracted: {result['extracted']}\nSkipped: {result['skipped']}\nErrors: {result['errors']}\nBytes: {result['bytes']:,}\n\n" + "\n".join(result.get("error_details", [])[:200]))
            self.show_report_tab(f"Extract — {path.name}", report, path)
            self.log(report, category="ARCHIVE", level=logging.WARNING if result["errors"] else logging.INFO)
        except Exception as exc:
            self.error(exc)

    def backend_action(self, mode, selected=None):
        try:
            backend = self.ensure_backend()
            cfg = self._compile_config()
            root = self.project_root()
            if mode == "compile":
                self.compile_single_source(selected)
                return
            if mode == "compile_folder":
                folder = str(selected) if selected and Path(selected).is_dir() else QFileDialog.getExistingDirectory(self, "Choose folder of .gd files", str(root or Path.home()))
                if not folder:
                    return
                outdir = QFileDialog.getExistingDirectory(self, "Choose compiled .gdc output folder", str(Path(folder) / ".opengds-compiled"))
                if not outdir:
                    return
                args = ["comp", folder, "--outdir", outdir, "--tab-size", str(cfg["tab_size"])]
                if not cfg["compressed"]: args.append("--no-compress")
                if cfg["overwrite"]: args.append("--force")
                if cfg["continue_on_error"]: args.append("--continue-on-error")
                self.run_background("Compile folder", lambda: backend.run(*args).stdout,
                                    lambda output: self.show_report_tab("Folder compilation", output))
                return
            if mode == "compile_project":
                root = self._choose_project_root()
                if not root: return
                default_output = root / (self.data or {}).get("compile", {}).get("output_directory", ".opengds/compiled")
                outdir = QFileDialog.getExistingDirectory(self, "Choose entire-project compiled output folder", str(default_output))
                if not outdir: return
                output_path = Path(outdir).resolve()
                if self.data is not None:
                    try:
                        self.data.setdefault("compile", {})["output_directory"] = output_path.relative_to(root).as_posix()
                    except ValueError:
                        self.data.setdefault("compile", {})["output_directory"] = str(output_path)
                    if self.data.get("descriptor"):
                        save_project(self.data)
                self._start_project_compile(root, output_path)
                return
            if mode == "decompile":
                self.decompile_single_binary(selected)
                return
            if mode == "decompile_folder":
                folder = str(selected) if selected and Path(selected).is_dir() else QFileDialog.getExistingDirectory(self, "Choose folder containing .gdc files", str(root or Path.home()))
                if not folder: return
                outdir = QFileDialog.getExistingDirectory(self, "Choose reconstructed .gd output folder", str(Path(folder) / ".opengds-decompiled"))
                if not outdir: return
                self.run_background("Decompile folder", lambda: backend.run("dcmp", folder, "--outdir", outdir).stdout,
                                    lambda output: self.show_report_tab("Folder decompilation", output))
                return
            if mode == "decompile_project":
                root = self._choose_project_root()
                if not root: return
                default_output = root / ".opengds" / "decompiled"
                outdir = QFileDialog.getExistingDirectory(self, "Choose entire-project decompiled output folder", str(default_output))
                if not outdir: return
                self._start_project_decompile(root, Path(outdir))
                return
            if mode.startswith("project_"):
                command = mode.removeprefix("project_")
                root = Path(selected).resolve() if selected and Path(selected).is_dir() else self._choose_project_root()
                if not root: return
                if command == "diff":
                    self.error("Project-wide diff needs exactly two individual .gdc files. Use Compare GDSC Files.")
                    return
                self.run_background(f"OpenGDS {command} on all project GDSC", lambda: backend.inspect(command, root),
                                    lambda output: self.show_report_tab(f"Project {command}", output))
                return
            if mode == "diff":
                first = selected if selected and Path(selected).suffix.lower() == ".gdc" else self.choose_backend_file((".gdc",), "Choose first GDSC file")
                if not first: return
                second = QFileDialog.getOpenFileName(self, "Choose second GDSC file", str(Path(first).parent), "GDSC (*.gdc)")[0]
                if second:
                    tab = self.show_report_tab("GDSC Diff", "Comparing GDSC files…\n")
                    self.run_background("Compare GDSC files", lambda: backend.diff(first, second),
                        lambda report: tab.report_text.setPlainText(report))
                return
            if mode == "dbg":
                source = Path(selected).resolve() if selected else None
                if source is None:
                    editor = self.current_editor()
                    source = editor.file_path if editor and editor.file_path.suffix.lower() in {".gd", ".gdc"} else self.choose_backend_file((".gd", ".gdc"), "Static-debug a GDScript or GDSC")
                if not source: return
                if source.suffix.lower() == ".gd":
                    if source not in self.editors:
                        self.open_path(source)
                    if source in self.editors and self.editors[source].document().isModified():
                        self.tabs.setCurrentWidget(self.editors[source])
                        self.save_file()
                    try:
                        relative = source.relative_to(root or source.parent)
                    except ValueError:
                        relative = Path(source.name)
                    binary = (root or source.parent) / ".opengds" / "static-debug" / relative.with_suffix(".gdc")
                elif source.suffix.lower() == ".gdc":
                    binary = source
                else:
                    raise ValueError("Static debugging needs a .gd or .gdc file")
                debug_cfg = (self.data or {}).get("debug", {})
                active_editor = self.editors.get(source)
                default_breakpoints = ", ".join(str(x) for x in sorted(active_editor.breakpoints)) if active_editor else ""
                raw, ok = QInputDialog.getText(self, "Static debugger breakpoints", "Source lines (comma-separated; editor breakpoints prefilled):", text=default_breakpoints)
                if not ok: return
                breakpoints = [int(value.strip()) for value in raw.split(",") if value.strip()]
                tab = self.show_report_tab(f"Static Debug — {source.name}", "Preparing static GDSC debug report…\n", source)
                def static_debug_work():
                    if source.suffix.lower() == ".gd":
                        binary.parent.mkdir(parents=True, exist_ok=True)
                        backend.compile(source, binary, compressed=False, overwrite=True, tab_size=cfg["tab_size"])
                    return backend.inspect("dbg", binary, context=debug_cfg.get("context", 4),
                        show_tokens=debug_cfg.get("show_tokens", False), max_tokens=debug_cfg.get("max_tokens", 200), breakpoints=breakpoints)
                self.run_background(f"Static debug {source.name}", static_debug_work,
                    lambda report: tab.report_text.setPlainText(report))
                return
            suffixes = (".gdc",) if mode in {"info", "audit", "disasm", "consts", "hexdump"} else (".gd", ".gdc")
            source = Path(selected).resolve() if selected else self.choose_backend_file(suffixes, f"OpenGDS {mode}")
            if not source: return
            tab = self.show_report_tab(f"OpenGDS {mode.upper()} — {source.name}", f"Running OpenGDS {mode}…\n", source)
            self.run_background(f"OpenGDS {mode} — {source.name}",
                lambda: backend.inspect(mode, source),
                lambda report: tab.report_text.setPlainText(report))
        except Exception as exc:
            self.error(exc)

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self.data or {}, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.apply()
            if self.data:
                if self.data.get("descriptor"):
                    save_project(self.data)
                self.backend = OpenGDSBackend(self.settings.value("backend_path", self.data.get("backend") or str(Path(__file__).with_name("OpenGDS.py"))))
                self.backend.default_timeout = int(self.settings.value("backend_timeout", 300))
                self.data["backend"] = str(self.backend.script)
            self.apply_theme()
            self.autosave_timer.setInterval(int(self.settings.value("autosave_interval", 30)) * 1000)
            fs_filter = QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot
            if self.settings.value("show_hidden_files", "false") == "true":
                fs_filter |= QDir.Filter.Hidden
            self.fs.setFilter(fs_filter)
            max_records = int(self.settings.value("max_log_records", 12000))
            self.log_records = self.log_records[-max_records:]
            self.output.document().setMaximumBlockCount(max_records)
            for editor in self.editors.values():
                editor.configure_features(
                    auto_pairs=self.settings.value("auto_pairs", "true") == "true",
                    auto_indent=self.settings.value("auto_indent", "true") == "true",
                    auto_completion=self.settings.value("auto_completion", "true") == "true",
                    line_numbers=self.settings.value("line_numbers", "true") == "true",
                    word_wrap=self.settings.value("word_wrap", "false") == "true",
                )
            self.log("Settings saved. Reconnect to Godot LSP/DAP to apply changed ports.", category="GUI")

    def update_backend(self):
        source = QFileDialog.getOpenFileName(self, "Select updated OpenGDS.py", str(Path.home()), "Python files (*.py)")[0]
        if not source:
            return
        try:
            target = Path(self.settings.value("backend_path", str(Path(__file__).with_name("OpenGDS.py"))))
            backup = OpenGDSBackend(target).install_update(source)
            self.backend = OpenGDSBackend(target)
            self.settings.setValue("backend_path", str(target))
            self.log(f"Backend updated. Backup: {backup}")
        except Exception as exc:
            self.error(exc)

    def refresh_history_menu(self):
        self.history_menu.clear()
        for entry in self.history.entries()[:15]:
            path = entry.get("path", "")
            action = QAction(path, self)
            action.triggered.connect(lambda checked=False, value=path: self.open_history_item(value))
            self.history_menu.addAction(action)
        self.history_menu.addSeparator(); self.history_menu.addAction("Manage History…", self.manage_history)

    def open_history_item(self, path):
        try:
            candidate = Path(path)
            if candidate.is_dir():
                descriptor = candidate / "file.ogds"
                if descriptor.exists():
                    self.set_project(load_project(descriptor))
                else:
                    self.set_project({"name": candidate.name, "root": str(candidate.resolve()), "descriptor": "", "backend": str(Path(__file__).with_name("OpenGDS.py")), "compile": {}, "debug": {}, "editor": {}})
            else:
                self.set_project(load_project(candidate))
        except Exception as exc:
            self.error(exc)

    def manage_history(self):
        dialog = QDialog(self); dialog.setWindowTitle("Recent projects"); dialog.resize(650, 360)
        layout = QVBoxLayout(dialog); listing = QListWidget(); layout.addWidget(listing)
        def refill():
            listing.clear()
            for entry in self.history.entries():
                listing.addItem(entry["path"])
        refill()
        row = QHBoxLayout(); remove = QPushButton("Remove selected"); clear = QPushButton("Clear history")
        row.addWidget(remove); row.addWidget(clear); layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        def remove_selected():
            if listing.currentItem():
                self.history.remove(listing.currentItem().text()); refill(); self.refresh_history_menu()
        remove.clicked.connect(remove_selected)
        clear.clicked.connect(lambda: (self.history.clear(), refill(), self.refresh_history_menu()))
        dialog.exec()

    def open_root_folder(self):
        root = self.project_root()
        if root:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))

    def about(self):
        QMessageBox.about(self, APP_NAME,
            f"{APP_NAME} {VERSION}\n"
            f"Developer: {DEVELOPER}\n\n"
            "GDScript / GDSC IDE powered by the OpenGDS v1.0.2 core.\n"
            "Includes GDSC compiler/decompiler, inspection and static audit tools, Godot LSP/DAP clients, "
            "OpenGDS --godot/--interrupt debugging, and Godot project/archive tools.")

    def error(self, error):
        if isinstance(error, BaseException):
            if isinstance(error, BackendError):
                error_category = "BUILD"
            elif isinstance(error, OSError):
                error_category = "FILE"
            else:
                error_category = "PYTHON"
            log_event(error_category, logging.ERROR, f"GUI operation raised {type(error).__name__}: {error}",
                      exc_info=(type(error), error, error.__traceback__))
        else:
            log_event("LOGIC", logging.ERROR, str(error))
        QMessageBox.critical(self, APP_NAME, str(error))

    def closeEvent(self, event):
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index)
            if isinstance(widget, CodeEditor) and widget.document().isModified():
                self.tabs.setCurrentIndex(index)
                answer = QMessageBox.question(self, "Unsaved changes", f"Save {widget.file_path.name}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
                if answer == QMessageBox.StandardButton.Cancel:
                    event.ignore(); return
                if answer == QMessageBox.StandardButton.Yes:
                    self.save_file()
        self.settings.setValue("geometry", self.saveGeometry())
        self.log("Application closing", category="GUI")
        self.lsp.disconnect_from_server()
        self.dap.disconnect_from_server()
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.terminate()
        qInstallMessageHandler(None)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("OpenGDS")
    icon_file = Path(__file__).with_name("assets") / "opengds-ide.ico"
    if icon_file.is_file():
        app.setWindowIcon(QIcon(str(icon_file)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
