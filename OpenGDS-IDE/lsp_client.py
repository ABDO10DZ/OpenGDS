"""Qt TCP client for Godot's built-in GDScript Language Server (LSP)."""
from __future__ import annotations

from app_info import VERSION
import os
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtNetwork import QTcpSocket, QAbstractSocket
from protocol import FrameBuffer, encode_message
from logging_system import log_event


class GodotLanguageClient(QObject):
    statusChanged = Signal(str)
    diagnosticsReceived = Signal(str, object)
    completionReceived = Signal(object)
    hoverReceived = Signal(object)
    readyChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.socket = QTcpSocket(self)
        self.frames = FrameBuffer()
        self.next_id = 1
        self.pending: dict[int, str] = {}
        self.documents: dict[str, dict] = {}
        self.root_uri = ""
        self.ready = False
        self.socket.connected.connect(self._on_connected)
        self.socket.disconnected.connect(self._on_disconnected)
        self.socket.readyRead.connect(self._on_ready_read)
        self.socket.errorOccurred.connect(self._on_error)

    @staticmethod
    def uri_for_path(path: str | Path) -> str:
        return QUrl.fromLocalFile(str(Path(path).resolve())).toString()

    def connect_to_server(self, host: str, port: int, root: str | Path):
        self.disconnect_from_server()
        self.frames = FrameBuffer()
        self.root_uri = QUrl.fromLocalFile(str(Path(root).resolve())).toString()
        log_event("LSP", 20, f"Connecting to Godot language server {host}:{port}; project={root}")
        self.statusChanged.emit(f"Connecting to Godot LSP at {host}:{port}…")
        self.socket.connectToHost(host, int(port))

    def disconnect_from_server(self):
        self.ready = False
        self.readyChanged.emit(False)
        if self.socket.state() != QAbstractSocket.SocketState.UnconnectedState:
            self.socket.abort()

    def _on_connected(self):
        params = {
            "processId": os.getpid(),
            "clientInfo": {"name": "OpenGDS - IDE", "version": VERSION},
            "rootUri": self.root_uri,
            "capabilities": {
                "textDocument": {
                    "synchronization": {"dynamicRegistration": False, "willSave": False, "didSave": True},
                    "completion": {"completionItem": {"snippetSupport": False, "documentationFormat": ["markdown", "plaintext"]}},
                    "hover": {"contentFormat": ["markdown", "plaintext"]},
                    "publishDiagnostics": {"relatedInformation": True},
                },
                "workspace": {"workspaceFolders": True, "symbol": {"dynamicRegistration": False}},
            },
            "workspaceFolders": [{"uri": self.root_uri, "name": Path(QUrl(self.root_uri).toLocalFile()).name}],
        }
        self._request("initialize", params)

    def _send(self, message: dict):
        if self.socket.state() == QAbstractSocket.SocketState.ConnectedState:
            self.socket.write(encode_message(message))

    def _request(self, method: str, params: dict, *, tag: str | None = None) -> int:
        request_id = self.next_id
        self.next_id += 1
        self.pending[request_id] = tag or method
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return request_id

    def _notify(self, method: str, params: dict):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _on_ready_read(self):
        try:
            messages = self.frames.feed(bytes(self.socket.readAll()))
        except Exception:
            log_event("LSP", 40, "Invalid or malformed language-server protocol frame", exc_info=True)
            self.statusChanged.emit("Godot LSP: malformed protocol frame (see logs)")
            return
        for message in messages:
            if "id" in message and ("result" in message or "error" in message):
                tag = self.pending.pop(int(message["id"]), "")
                if "error" in message:
                    log_event("LSP", 30, f"LSP request {tag or 'request'} failed: {message['error']}")
                    self.statusChanged.emit(f"Godot LSP {tag or 'request'} failed: {message['error']}")
                    continue
                result = message.get("result")
                if tag == "initialize":
                    self._notify("initialized", {})
                    self.ready = True
                    self.readyChanged.emit(True)
                    log_event("LSP", 20, "Godot GDScript language server initialized successfully")
                    self.statusChanged.emit("Godot GDScript language server connected")
                    for uri, doc in list(self.documents.items()):
                        self._notify("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": "gdscript", "version": doc["version"], "text": doc["text"]}})
                elif tag == "completion":
                    items = result.get("items", []) if isinstance(result, dict) else result or []
                    self.completionReceived.emit(items)
                elif tag == "hover":
                    self.hoverReceived.emit(result)
            elif message.get("method") == "textDocument/publishDiagnostics":
                params = message.get("params", {})
                self.diagnosticsReceived.emit(params.get("uri", ""), params.get("diagnostics", []))

    def _on_disconnected(self):
        was_ready = self.ready
        self.ready = False
        self.readyChanged.emit(False)
        self.statusChanged.emit("Godot language server disconnected")
        if was_ready:
            self.pending.clear()

    def _on_error(self, _error):
        if self.socket.error() != QAbstractSocket.SocketError.RemoteHostClosedError:
            log_event("LSP", 30, "Language-server socket error: " + self.socket.errorString())
            self.statusChanged.emit("Godot LSP: " + self.socket.errorString())

    def open_document(self, path: str | Path, text: str):
        uri = self.uri_for_path(path)
        self.documents[uri] = {"text": text, "version": 1}
        if self.ready:
            self._notify("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": "gdscript", "version": 1, "text": text}})

    def change_document(self, path: str | Path, text: str):
        uri = self.uri_for_path(path)
        doc = self.documents.setdefault(uri, {"version": 0, "text": ""})
        doc["version"] += 1
        doc["text"] = text
        if self.ready:
            self._notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": doc["version"]}, "contentChanges": [{"text": text}]})

    def save_document(self, path: str | Path, text: str):
        uri = self.uri_for_path(path)
        if uri in self.documents:
            self.documents[uri]["text"] = text
        if self.ready:
            self._notify("textDocument/didSave", {"textDocument": {"uri": uri}, "text": text})

    def close_document(self, path: str | Path):
        uri = self.uri_for_path(path)
        self.documents.pop(uri, None)
        if self.ready:
            self._notify("textDocument/didClose", {"textDocument": {"uri": uri}})

    def request_completion(self, path: str | Path, line: int, character: int):
        if self.ready:
            self._request("textDocument/completion", {"textDocument": {"uri": self.uri_for_path(path)}, "position": {"line": line, "character": character}, "context": {"triggerKind": 1}}, tag="completion")

    def request_hover(self, path: str | Path, line: int, character: int):
        if self.ready:
            self._request("textDocument/hover", {"textDocument": {"uri": self.uri_for_path(path)}, "position": {"line": line, "character": character}}, tag="hover")
