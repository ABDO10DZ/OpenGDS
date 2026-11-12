"""Minimal Godot Debug Adapter Protocol client for runtime debugging."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QTcpSocket, QAbstractSocket
from protocol import FrameBuffer, encode_message
from logging_system import log_event


class GodotDebugClient(QObject):
    statusChanged = Signal(str)
    outputReceived = Signal(str)
    stopped = Signal(object)
    continued = Signal()
    terminated = Signal()
    stackChanged = Signal(object)
    variablesChanged = Signal(object)
    breakpointResult = Signal(object)
    initialized = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.socket = QTcpSocket(self)
        self.frames = FrameBuffer()
        self.seq = 1
        self.pending: dict[int, str] = {}
        self.variable_request_scopes: dict[int, str] = {}
        self.root = Path.cwd()
        self.breakpoints: dict[str, list[int]] = {}
        self.scene = ""
        self.remote_address = "127.0.0.1"
        self.remote_port = 6007
        self.thread_id = 1
        self.frame_id: int | None = None
        self._launch_requested = False
        self._configuration_sent = False
        self._awaiting_configuration = False
        self._setup_breakpoint_requests: set[int] = set()
        self._scope_requests = 0
        self._variables_accumulator: list[dict] = []
        self.socket.connected.connect(self._on_connected)
        self.socket.disconnected.connect(self._on_disconnected)
        self.socket.readyRead.connect(self._on_ready_read)
        self.socket.errorOccurred.connect(self._on_error)

    def connect_to_server(self, host: str, port: int, project: str | Path,
                          breakpoints: dict[str, list[int]] | None = None,
                          scene: str = "", remote_address: str = "127.0.0.1", remote_port: int = 6007):
        self.disconnect_from_server()
        self.frames = FrameBuffer()
        self.root = Path(project).resolve()
        self.breakpoints = {str(Path(k).resolve()): sorted(set(int(x) for x in v)) for k, v in (breakpoints or {}).items()}
        self.scene = scene
        self.remote_address = remote_address
        self.remote_port = int(remote_port)
        self._launch_requested = False
        self._configuration_sent = False
        self._awaiting_configuration = False
        self._setup_breakpoint_requests.clear()
        self.pending.clear()
        self.frame_id = None
        self.thread_id = 1
        self.variable_request_scopes.clear()
        self._variables_accumulator.clear()
        log_event("DAP", 20, f"Connecting to Godot debugger adapter {host}:{port}; project={self.root}")
        self.statusChanged.emit(f"Connecting to Godot debugger at {host}:{port}…")
        self.socket.connectToHost(host, int(port))

    def disconnect_from_server(self):
        if self.socket.state() != QAbstractSocket.SocketState.UnconnectedState:
            self.socket.abort()

    def _send_request(self, command: str, arguments: dict | None = None) -> int:
        log_event("DAP", 10, f"DAP request: {command}; args={arguments or {}}")
        seq = self.seq
        self.seq += 1
        self.pending[seq] = command
        message = {"seq": seq, "type": "request", "command": command}
        if arguments is not None:
            message["arguments"] = arguments
        self._send(message)
        return seq

    def _send_event(self, event: str, body: dict | None = None):
        self._send({"seq": self.seq, "type": "event", "event": event, "body": body or {}})
        self.seq += 1

    def _send(self, message: dict):
        if self.socket.state() == QAbstractSocket.SocketState.ConnectedState:
            self.socket.write(encode_message(message))

    def _on_connected(self):
        self._send_request("initialize", {
            "clientID": "opengds-ide", "clientName": "OpenGDS - IDE",
            "adapterID": "godot", "locale": "en", "linesStartAt1": True,
            "columnsStartAt1": True, "pathFormat": "path",
            "supportsVariableType": True, "supportsVariablePaging": True,
            "supportsRunInTerminalRequest": False,
        })

    def _on_ready_read(self):
        try:
            messages = self.frames.feed(bytes(self.socket.readAll()))
        except Exception:
            log_event("DAP", 40, "Invalid or malformed Debug Adapter Protocol frame", exc_info=True)
            self.statusChanged.emit("Godot DAP: malformed protocol frame (see logs)")
            return
        for message in messages:
            mtype = message.get("type")
            if mtype == "response":
                self._handle_response(message)
            elif mtype == "event":
                self._handle_event(message)
            elif mtype == "request":
                self._handle_server_request(message)

    def _handle_response(self, message: dict):
        request_seq = int(message.get("request_seq", -1))
        command = self.pending.pop(request_seq, "")
        if not message.get("success", False):
            log_event("DAP", 30, f"DAP request {command or 'request'} failed: {message.get('message', 'unknown error')}")
            self.statusChanged.emit(f"Godot debugger {command or 'request'} failed: {message.get('message', 'unknown error')}")
            if command == "setBreakpoints" and request_seq in self._setup_breakpoint_requests:
                self._setup_breakpoint_requests.discard(request_seq)
                if self._awaiting_configuration and not self._setup_breakpoint_requests:
                    self._finish_configuration()
            return
        body = message.get("body") or {}
        if command == "initialize":
            self.statusChanged.emit("Godot DAP connected; starting debug session…")
            self._start_launch()
        elif command == "stackTrace":
            frames = body.get("stackFrames", [])
            self.stackChanged.emit(frames)
            self.frame_id = frames[0].get("id") if frames else None
            if self.frame_id is not None:
                self._send_request("scopes", {"frameId": self.frame_id})
            else:
                self.variablesChanged.emit([])
        elif command == "scopes":
            scopes = body.get("scopes", [])
            self._scope_requests += len(scopes)
            self._variables_accumulator = []
            if not scopes:
                self.variablesChanged.emit([])
            for scope in scopes:
                ref = int(scope.get("variablesReference", 0))
                if ref:
                    request_id = self._send_request("variables", {"variablesReference": ref})
                    self.variable_request_scopes[request_id] = str(scope.get("name", ""))
        elif command == "variables":
            scope_name = self.variable_request_scopes.pop(request_seq, "")
            rows = body.get("variables", [])
            for row in rows:
                row["_scope"] = scope_name
            self._variables_accumulator.extend(rows)
            self.variablesChanged.emit(list(self._variables_accumulator))
        elif command == "terminate":
            self._send_request("disconnect", {"restart": False, "terminateDebuggee": True})
        elif command == "disconnect":
            self.socket.disconnectFromHost()
        elif command == "threads":
            threads = body.get("threads", [])
            if threads:
                self.thread_id = int(threads[0].get("id", 1))
                self._send_request("stackTrace", {"threadId": self.thread_id, "startFrame": 0, "levels": 50})
        elif command == "setBreakpoints":
            self.breakpointResult.emit(body.get("breakpoints", []))
            if request_seq in self._setup_breakpoint_requests:
                self._setup_breakpoint_requests.discard(request_seq)
                if self._awaiting_configuration and not self._setup_breakpoint_requests:
                    self._finish_configuration()
        elif command == "evaluate":
            self.outputReceived.emit(f"[watch] {body.get('result', '')}")
        elif command in {"continue", "next", "stepIn", "stepOut"}:
            self.frame_id = None
            self.continued.emit()
        elif command in {"launch", "configurationDone"}:
            self.statusChanged.emit("Godot debug session is starting")

    def _start_launch(self):
        if self._launch_requested:
            return
        self._launch_requested = True
        args = {
            "project": str(self.root),
            "address": self.remote_address,
            "port": self.remote_port,
        }
        if self.scene:
            args["scene"] = self.scene
        self._send_request("launch", args)

    def _configure_session(self):
        if self._configuration_sent:
            return
        self._configuration_sent = True
        self._awaiting_configuration = True
        for source_path, lines in self.breakpoints.items():
            request_id = self._send_request("setBreakpoints", {
                "source": {"name": Path(source_path).name, "path": source_path},
                "breakpoints": [{"line": int(line)} for line in lines],
                "sourceModified": False,
            })
            self._setup_breakpoint_requests.add(request_id)
        if not self._setup_breakpoint_requests:
            self._finish_configuration()

    def _finish_configuration(self):
        if not self._awaiting_configuration:
            return
        self._awaiting_configuration = False
        self._send_request("configurationDone", {})
        self.initialized.emit()

    def _handle_event(self, message: dict):
        event = message.get("event")
        body = message.get("body") or {}
        if event == "initialized":
            self._configure_session()
        elif event == "output":
            self.outputReceived.emit(body.get("output", ""))
        elif event == "stopped":
            self.thread_id = int(body.get("threadId", self.thread_id or 1))
            self.stopped.emit(body)
            self._send_request("threads", {})
        elif event == "continued":
            self.frame_id = None
            self.continued.emit()
        elif event in {"terminated", "exited"}:
            self.statusChanged.emit("Godot debug session ended")
            self.terminated.emit()
        elif event == "breakpoint":
            self.outputReceived.emit(f"[breakpoint] {body}")

    def _handle_server_request(self, message: dict):
        log_event("DAP", 30, f"Godot sent unsupported reverse request: {message.get('command', '')}")
        # Godot currently does not need client-side reverse requests for basic debugging.
        seq = self.seq
        self.seq += 1
        self._send({"seq": seq, "type": "response", "request_seq": message.get("seq"),
                    "success": False, "command": message.get("command", ""),
                    "message": "OpenGDS - IDE does not implement this reverse request."})

    def _on_disconnected(self):
        self.statusChanged.emit("Godot debugger disconnected")
        self.terminated.emit()
        self.pending.clear()

    def _on_error(self, _error):
        if self.socket.error() != QAbstractSocket.SocketError.RemoteHostClosedError:
            log_event("DAP", 30, "Debugger socket error: " + self.socket.errorString())
            self.statusChanged.emit("Godot DAP: " + self.socket.errorString())

    def _command(self, name: str, args: dict | None = None):
        if self.socket.state() == QAbstractSocket.SocketState.ConnectedState:
            self._send_request(name, args or {})

    def continue_execution(self): self._command("continue", {"threadId": self.thread_id})
    def pause(self): self._command("pause", {"threadId": self.thread_id})
    def step_over(self): self._command("next", {"threadId": self.thread_id})
    def step_into(self): self._command("stepIn", {"threadId": self.thread_id})
    def step_out(self): self._command("stepOut", {"threadId": self.thread_id})
    def stop(self):
        self._command("terminate", {})

    def request_variables(self, variables_reference: int):
        if int(variables_reference) > 0:
            self._send_request("variables", {"variablesReference": int(variables_reference)})

    def set_breakpoints(self, source_path: str | Path, lines: list[int]):
        path = str(Path(source_path).resolve())
        self.breakpoints[path] = sorted(set(int(line) for line in lines))
        if self.socket.state() == QAbstractSocket.SocketState.ConnectedState and self._configuration_sent:
            self._send_request("setBreakpoints", {
                "source": {"name": Path(path).name, "path": path},
                "breakpoints": [{"line": line} for line in self.breakpoints[path]],
                "sourceModified": False,
            })

    def evaluate(self, expression: str):
        if self.frame_id is not None and expression.strip():
            self._send_request("evaluate", {"expression": expression, "frameId": self.frame_id, "context": "watch"})
