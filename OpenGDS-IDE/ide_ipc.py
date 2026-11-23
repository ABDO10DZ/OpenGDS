"""Authenticated loopback IPC for optional, view-only external MCP IDE navigation.

The IDE must explicitly enable this bridge for the current session. The endpoint
is bound to loopback, its one-time token is stored only in the OS keyring, and
the discovery file contains no secret. The bridge delegates to IDEControlBridge,
which marshals every UI action onto the Qt thread.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import socketserver
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any


KEYRING_SERVICE = "OpenGDS-IDE"
MAX_REQUEST_BYTES = 32_768
MAX_RESPONSE_BYTES = 64_000
MAX_REGISTRY_BYTES = 4_096
MAX_REGISTRIES = 20
IDE_CONTROL_ACTIONS = frozenset({
    "ide_get_state",
    "ide_get_diagnostics",
    "ide_get_debug_state",
    "ide_open_file",
    "ide_go_to_line",
    "ide_focus_panel",
})
_KEY_ID_RE = re.compile(r"^ide-control-\d+-[0-9a-f]{32}$")
_SESSION_RE = re.compile(r"^[0-9a-f]{32}$")


def workspace_identity(workspace: str | Path) -> str:
    """Return a stable, non-reversible identifier for a resolved workspace path."""
    resolved = os.path.normcase(str(Path(workspace).expanduser().resolve()))
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()


def default_registry_directory() -> Path:
    """Return a per-user cache location for non-secret endpoint metadata."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "OpenGDS-IDE" / "ide-control"


def _secure_directory(path: Path, *, create: bool) -> Path:
    path = Path(path).expanduser()
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(path, 0o700)
        except OSError:
            if os.name != "nt":
                raise
    if path.is_symlink() or not path.is_dir():
        raise PermissionError("The local IDE-control registry directory is not a safe directory.")
    if os.name != "nt":
        st = path.stat()
        if st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise PermissionError("The local IDE-control registry directory must be owned by this user with mode 0700.")
    return path


def _load_keyring(keyring_api=None):
    if keyring_api is None:
        try:
            import keyring as keyring_api
        except ImportError as exc:
            raise RuntimeError("Secure OS keyring support is required for external IDE navigation.") from exc
    try:
        backend = keyring_api.get_keyring()
        if getattr(backend, "priority", 0) <= 0:
            raise RuntimeError("No secure operating-system keyring is available.")
    except Exception as exc:
        raise RuntimeError("Unlock or configure the operating-system keyring to enable external IDE navigation.") from exc
    return keyring_api


class _IDEWorkspaceMismatch(RuntimeError):
    """Raised when an IDE instance changed projects before executing an IPC action."""


class _IDEAuthenticationError(RuntimeError):
    """Raised when a registry entry no longer authenticates to its local server."""


def _send_json(stream, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_RESPONSE_BYTES:
        raw = json.dumps({
            "ok": False,
            "error": "The IDE response exceeds the 64 KB IPC limit.",
        }).encode("utf-8")
    stream.write(raw + b"\n")
    stream.flush()


class _IDEControlRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.request.settimeout(16)
        raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        if not raw or len(raw) > MAX_REQUEST_BYTES or not raw.endswith(b"\n"):
            _send_json(self.wfile, {"ok": False, "error": "Invalid or oversized IPC request."})
            return
        try:
            request = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _send_json(self.wfile, {"ok": False, "error": "Invalid IPC request encoding."})
            return
        if not isinstance(request, dict) or set(request) != {"token", "workspace_id", "name", "args"}:
            _send_json(self.wfile, {"ok": False, "error": "Invalid IPC request shape."})
            return
        workspace_id = request.get("workspace_id")
        if not isinstance(workspace_id, str) or not re.fullmatch(r"[0-9a-f]{64}", workspace_id):
            _send_json(self.wfile, {"ok": False, "error": "Invalid requested workspace identity."})
            return
        supplied = request.get("token")
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied, self.server.token):
            _send_json(self.wfile, {"ok": False, "code": "unauthorized", "error": "Unauthorized local IDE-control request."})
            return
        name = request.get("name")
        args = request.get("args")
        action_fields = {
            "ide_get_state": set(),
            "ide_get_diagnostics": set(),
            "ide_get_debug_state": set(),
            "ide_open_file": {"path"},
            "ide_go_to_line": {"line", "column"},
            "ide_focus_panel": {"panel"},
        }
        if not isinstance(name, str) or name not in IDE_CONTROL_ACTIONS or not isinstance(args, dict):
            _send_json(self.wfile, {"ok": False, "error": "IDE action is not allow-listed."})
            return
        required = {
            "ide_open_file": {"path"},
            "ide_go_to_line": {"line"},
            "ide_focus_panel": {"panel"},
        }.get(name, set())
        if not required.issubset(args) or not set(args).issubset(action_fields[name]):
            _send_json(self.wfile, {"ok": False, "error": "Invalid IDE action arguments."})
            return
        if name == "ide_open_file" and (not isinstance(args.get("path"), str) or len(args["path"]) > 4096):
            _send_json(self.wfile, {"ok": False, "error": "Invalid IDE file path."})
            return
        if name == "ide_go_to_line":
            if type(args.get("line")) is not int or args["line"] < 1:
                _send_json(self.wfile, {"ok": False, "error": "Invalid IDE line number."})
                return
            if "column" in args and (type(args["column"]) is not int or not 0 <= args["column"] <= 1_000_000):
                _send_json(self.wfile, {"ok": False, "error": "Invalid IDE editor column."})
                return
        if name == "ide_focus_panel" and (not isinstance(args.get("panel"), str) or len(args["panel"]) > 64):
            _send_json(self.wfile, {"ok": False, "error": "Invalid IDE panel name."})
            return
        try:
            bridge_args = dict(args)
            bridge_args["_expected_workspace_id"] = workspace_id
            result = self.server.bridge.call(name, bridge_args)
            if not isinstance(result, dict):
                raise TypeError("IDE control returned an unsupported response.")
            _send_json(self.wfile, {"ok": True, "result": result})
        except Exception as exc:
            message = str(exc)[:1000]
            code = "workspace_mismatch" if message.startswith("Workspace identity mismatch") else "action_failed"
            _send_json(self.wfile, {"ok": False, "code": code, "error": message})


class _ThreadedIDEControlServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True
    block_on_close = False

    def __init__(self, address, bridge, token):
        self.bridge = bridge
        self.token = token
        super().__init__(address, _IDEControlRequestHandler)


class IDEControlIPCServer:
    """Expose only the IDEControlBridge allow-list over authenticated loopback IPC."""

    def __init__(self, bridge, *, registry_directory: str | Path | None = None, keyring_api=None):
        self.bridge = bridge
        self.registry_directory = Path(registry_directory) if registry_directory else default_registry_directory()
        self.keyring_api = keyring_api
        self.server = None
        self.thread = None
        self.token = None
        self.key_id = None
        self.session = uuid.uuid4().hex
        self.registry_file = None
        self._started = False

    def start(self) -> dict[str, Any]:
        if self.server is not None:
            return {"enabled": True, "host": "127.0.0.1", "port": self.server.server_address[1]}
        keyring_api = _load_keyring(self.keyring_api)
        self.registry_directory = _secure_directory(self.registry_directory, create=True)
        self.token = secrets.token_urlsafe(48)
        self.key_id = f"ide-control-{os.getpid()}-{self.session}"
        self.registry_file = self.registry_directory / f"{os.getpid()}-{self.session}.json"
        server = None
        stored = False
        try:
            keyring_api.set_password(KEYRING_SERVICE, self.key_id, self.token)
            stored = True
            server = _ThreadedIDEControlServer(("127.0.0.1", 0), self.bridge, self.token)
            registry = {
                "host": "127.0.0.1",
                "port": int(server.server_address[1]),
                "pid": os.getpid(),
                "key_id": self.key_id,
                "session": self.session,
                "protocol": 1,
            }
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.registry_directory,
                    prefix=".ide-control-", suffix=".tmp", delete=False,
                ) as stream:
                    temp_path = Path(stream.name)
                    json.dump(registry, stream, separators=(",", ":"))
                    stream.flush()
                    os.fsync(stream.fileno())
                if os.name != "nt":
                    os.chmod(temp_path, 0o600)
                os.replace(temp_path, self.registry_file)
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
            self.server = server
            self.thread = threading.Thread(
                target=server.serve_forever, name="OpenGDS-IDE-IPC", daemon=True
            )
            self.thread.start()
            self._started = True
            return {"enabled": True, "host": "127.0.0.1", "port": int(server.server_address[1])}
        except Exception:
            if server is not None:
                server.server_close()
            if stored:
                try:
                    keyring_api.delete_password(KEYRING_SERVICE, self.key_id)
                except Exception:
                    pass
            if self.registry_file is not None:
                self.registry_file.unlink(missing_ok=True)
            self.token = None
            self.key_id = None
            self.registry_file = None
            raise

    def stop(self) -> None:
        server, thread = self.server, self.thread
        self.server = None
        self.thread = None
        if server is not None:
            if self._started:
                server.shutdown()
            server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        self._started = False

        if self.registry_file is not None and self.registry_file.is_file():
            try:
                registry = json.loads(self.registry_file.read_text(encoding="utf-8"))
                if registry.get("session") == self.session:
                    self.registry_file.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass
        if self.key_id and self.token:
            try:
                keyring_api = _load_keyring(self.keyring_api)
                current = keyring_api.get_password(KEYRING_SERVICE, self.key_id)
                if isinstance(current, str) and hmac.compare_digest(current, self.token):
                    keyring_api.delete_password(KEYRING_SERVICE, self.key_id)
            except Exception:
                pass
        self.token = None
        self.key_id = None
        self.registry_file = None


class IDEControlIPCClient:
    """Find the enabled IDE instance for one workspace and invoke an allow-listed action."""

    def __init__(self, workspace: str | Path, *,
                 registry_directory: str | Path | None = None, keyring_api=None):
        self.workspace = Path(workspace).expanduser().resolve()
        self.registry_directory = Path(registry_directory) if registry_directory else default_registry_directory()
        self.keyring_api = keyring_api

    def _registries(self) -> list[dict[str, Any]]:
        directory = _secure_directory(self.registry_directory, create=False)
        rows = []
        for path in sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:MAX_REGISTRIES]:
            try:
                if path.is_symlink() or path.stat().st_size > MAX_REGISTRY_BYTES:
                    continue
                st = path.stat()
                if os.name != "nt" and (st.st_uid != os.getuid() or st.st_mode & 0o077):
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or set(data) != {"host", "port", "pid", "key_id", "session", "protocol"}:
                    continue
                if (data["host"] != "127.0.0.1" or type(data["port"]) is not int
                        or not 1 <= data["port"] <= 65535 or type(data["pid"]) is not int
                        or data["pid"] < 1 or data["protocol"] != 1
                        or not isinstance(data["key_id"], str) or not _KEY_ID_RE.fullmatch(data["key_id"])
                        or not isinstance(data["session"], str) or not _SESSION_RE.fullmatch(data["session"])):
                    continue
                rows.append(data)
            except (OSError, ValueError, TypeError, KeyError):
                continue
        return rows

    @staticmethod
    def _request(registry: dict[str, Any], token: str, workspace_id: str,
                 name: str, args: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(
            {"token": token, "workspace_id": workspace_id, "name": name, "args": args},
            ensure_ascii=True, separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        if len(payload) > MAX_REQUEST_BYTES:
            raise ValueError("IDE-control request exceeds the 32 KB IPC limit.")
        with socket.create_connection((registry["host"], registry["port"]), timeout=3) as sock:
            sock.settimeout(16)
            sock.sendall(payload)
            chunks = bytearray()
            while len(chunks) <= MAX_RESPONSE_BYTES:
                part = sock.recv(min(4096, MAX_RESPONSE_BYTES + 1 - len(chunks)))
                if not part:
                    break
                chunks.extend(part)
                if b"\n" in part:
                    break
        if len(chunks) > MAX_RESPONSE_BYTES or b"\n" not in chunks:
            raise RuntimeError("The local IDE returned an invalid or oversized IPC response.")
        try:
            response = json.loads(bytes(chunks).split(b"\n", 1)[0].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("The local IDE returned an invalid IPC response.") from None
        if isinstance(response, dict) and response.get("code") == "workspace_mismatch":
            raise _IDEWorkspaceMismatch(str(response.get("error", "Workspace identity mismatch."))[:1000])
        if isinstance(response, dict) and response.get("code") == "unauthorized":
            raise _IDEAuthenticationError(str(response.get("error", "The local IDE rejected authentication."))[:1000])
        if not isinstance(response, dict) or response.get("ok") is not True or not isinstance(response.get("result"), dict):
            message = response.get("error", "The local IDE rejected the request.") if isinstance(response, dict) else "Invalid local IDE response."
            raise RuntimeError(str(message)[:1000])
        return response["result"]

    def call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(name, str) or name not in IDE_CONTROL_ACTIONS:
            raise ValueError("IDE action is not allow-listed.")
        if args is not None and not isinstance(args, dict):
            raise TypeError("IDE action arguments must be an object.")
        args = dict(args or {})
        keyring_api = _load_keyring(self.keyring_api)
        expected_workspace = workspace_identity(self.workspace)
        try:
            registries = self._registries()
        except (OSError, PermissionError):
            registries = []
        for registry in registries:
            try:
                token = keyring_api.get_password(KEYRING_SERVICE, registry["key_id"])
                if not isinstance(token, str) or not token:
                    continue
                return self._request(registry, token, expected_workspace, name, args)
            except (_IDEWorkspaceMismatch, _IDEAuthenticationError):
                continue
            except (OSError, TimeoutError):
                continue
        raise RuntimeError(
            "No enabled OpenGDS-IDE instance has this workspace open. In the IDE, enable "
            "Tools → Allow external MCP IDE navigation for the current session."
        )
