"""Safe, allow-listed control bridge from the AI worker to the Qt IDE.

Calls originating in the agent worker are marshalled onto the GUI thread.
Only navigation and view operations are exposed; file writes and shell commands
remain in AgentEngine's explicit approval workflow.
"""
from __future__ import annotations

import threading
from pathlib import Path, PureWindowsPath

from PySide6.QtCore import QObject, QThread, Signal


class IDEControlBridge(QObject):
    _request = Signal(str, dict, object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._request.connect(self._dispatch)

    def call(self, name: str, args: dict | None = None) -> dict:
        args = dict(args or {})
        if QThread.currentThread() == self.thread():
            return self._execute(name, args)
        result = {"event": threading.Event(), "value": None, "error": None}
        self._request.emit(str(name), args, result)
        if not result["event"].wait(15):
            raise TimeoutError("The IDE did not respond to the control request.")
        if result["error"]:
            raise RuntimeError(result["error"])
        return result["value"]

    def _dispatch(self, name: str, args: dict, result: dict) -> None:
        try:
            result["value"] = self._execute(name, args)
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            result["event"].set()

    def _workspace(self) -> Path:
        root = self.window.project_root()
        if not root:
            raise RuntimeError("Open a project before using IDE controls.")
        return Path(root).resolve()

    def _relative_file(self, value: str) -> Path:
        root = self._workspace()
        raw = str(value or "").strip().replace("\\", "/")
        candidate = Path(raw)
        windows = PureWindowsPath(raw)
        if not raw or candidate.is_absolute() or windows.is_absolute() or windows.drive or ".." in candidate.parts:
            raise ValueError("IDE file navigation accepts workspace-relative paths only.")
        if any(part.startswith(".env") or part.lower() in {
            "secrets.json", "credentials.json", "credentials.db", "token.json",
            "id_rsa", "id_ed25519", "authorized_keys",
        } or Path(part).suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".keystore", ".cer", ".crt"}
               for part in candidate.parts):
            raise PermissionError("Sensitive files cannot be opened through AI controls.")
        path = (root / candidate).resolve()
        if path != root and root not in path.parents:
            raise PermissionError("File is outside the active workspace.")
        current = root
        for part in candidate.parts:
            current = current / part
            if current.is_symlink():
                raise PermissionError("Symbolic links are not followed by AI IDE controls.")
        if not path.is_file():
            raise FileNotFoundError("Workspace file does not exist.")
        return path

    def _execute(self, name: str, args: dict) -> dict:
        window = self.window
        if name == "ide_get_state":
            root = self._workspace()
            editor = window.current_editor()
            active = getattr(editor, "file_path", None) if editor else None
            opened = []
            for index in range(window.tabs.count()):
                widget = window.tabs.widget(index)
                path = getattr(widget, "file_path", None)
                if path:
                    try:
                        opened.append(Path(path).resolve().relative_to(root).as_posix())
                    except ValueError:
                        continue
            cursor = editor.textCursor() if editor else None
            return {
                "workspace": root.name,
                "active_file": Path(active).resolve().relative_to(root).as_posix() if active else None,
                "line": cursor.blockNumber() + 1 if cursor else None,
                "column": cursor.positionInBlock() + 1 if cursor else None,
                "open_files": opened[:100],
            }
        if name == "ide_open_file":
            path = self._relative_file(args.get("path", ""))
            window.open_path(path)
            return {"opened": path.relative_to(self._workspace()).as_posix()}
        if name == "ide_go_to_line":
            editor = window.current_editor()
            if not editor:
                raise RuntimeError("No source editor is active.")
            line = int(args.get("line", 0))
            column = max(0, int(args.get("column", 0)))
            if line < 1 or line > editor.blockCount():
                raise ValueError("Line is outside the active editor.")
            window.go_to_line(editor, line, column)
            return {"file": str(getattr(editor, "file_path", "")), "line": line, "column": column}
        if name == "ide_focus_panel":
            panels = {
                "explorer": window.explorer_dock,
                "source_control": window.source_control_dock,
                "code_insight": window.code_insight_dock,
                "ai_assistant": window.ai_dock_widget,
                "output": window.output_dock,
            }
            panel = str(args.get("panel", "")).lower()
            if panel not in panels:
                raise ValueError("Unknown IDE panel.")
            window.set_dock_visible(panels[panel], True)
            return {"focused_panel": panel}
        raise ValueError(f"Unsupported IDE control: {name}")
