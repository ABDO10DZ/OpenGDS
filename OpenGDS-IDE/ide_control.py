"""Safe, allow-listed control bridge from the AI worker to the Qt IDE.

Calls originating in the agent worker are marshalled onto the GUI thread.
Only navigation and view operations are exposed; file writes and shell commands
remain in AgentEngine's explicit approval workflow.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path, PureWindowsPath

from PySide6.QtCore import QObject, QThread, Signal, Qt


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
        if any(part.lower() in {".ssh", ".aws", ".azure", ".gnupg", ".secrets"}
               or part.startswith(".env") or part.lower() in {
            "secrets.json", "credentials.json", "credentials.db", "token.json",
            "id_rsa", "id_ed25519", "authorized_keys", ".npmrc", ".pypirc",
            ".netrc", ".git-credentials", "auth.json", "service-account.json",
            "access_token", "refresh_token", ".dockerconfigjson",
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
            active_relative = None
            if active:
                try:
                    active_relative = Path(active).resolve().relative_to(root).as_posix()
                except ValueError:
                    active_relative = None
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
                "active_file": active_relative,
                "line": cursor.blockNumber() + 1 if cursor else None,
                "column": cursor.positionInBlock() + 1 if cursor else None,
                "open_files": opened[:100],
            }
        if name == "ide_get_diagnostics":
            root = self._workspace()
            problems = getattr(window, "problems", None)
            if problems is None:
                return {"workspace": root.name, "diagnostics": [], "count": 0}
            rows = []
            blocked_dirs = {".git", ".ssh", ".aws", ".azure", ".gnupg", ".secrets", ".godot", ".opengds", ".opengds-ide"}
            blocked_names = {"secrets.json", "credentials.json", "credentials.db", "token.json", "auth.json",
                             ".npmrc", ".pypirc", ".netrc", ".git-credentials", "service-account.json"}
            blocked_suffixes = {".pem", ".key", ".p12", ".pfx", ".keystore", ".cer", ".crt"}
            for index in range(min(int(problems.count()), 100)):
                item = problems.item(index)
                data = item.data(Qt.ItemDataRole.UserRole)
                if not isinstance(data, (tuple, list)) or len(data) < 2:
                    continue
                raw_path, raw_line = data[0], data[1]
                raw_column = data[2] if len(data) > 2 else 0
                try:
                    candidate = Path(str(raw_path)).expanduser().resolve(strict=False)
                    relative = candidate.relative_to(root).as_posix()
                    parts = [part.lower() for part in Path(relative).parts]
                    if any(part in blocked_dirs or part.startswith(".env") or part in blocked_names
                           or Path(part).suffix.lower() in blocked_suffixes for part in parts):
                        continue
                    current = root
                    for part in Path(relative).parts:
                        current = current / part
                        if current.is_symlink():
                            raise PermissionError("Symlink diagnostic path")
                    if not candidate.is_file():
                        continue
                    line = max(1, int(raw_line))
                    column = max(0, int(raw_column or 0))
                except (OSError, ValueError, TypeError):
                    continue
                message = str(item.text() or "")[:1000]
                message = re.sub(r"(?i)(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|secret)\\s*[:=]\\s*[^\\s,;]+",
                                 r"\\1=[REDACTED]", message)
                message = re.sub(r"(?i)bearer\\s+[A-Za-z0-9._~+/=-]{8,}", "Bearer [REDACTED]", message)
                rows.append({"path": relative, "line": line, "column": column, "message": message})
            return {"workspace": root.name, "diagnostics": rows, "count": len(rows),
                    "truncated": int(problems.count()) > 100,
                    "source": "IDE Problems panel; structured diagnostics only, not raw logs"}
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
