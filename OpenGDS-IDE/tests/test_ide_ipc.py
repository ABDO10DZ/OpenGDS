import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ide_ipc import (
    IDEControlIPCClient,
    IDEControlIPCServer,
    IDE_CONTROL_ACTIONS,
    KEYRING_SERVICE,
    workspace_identity,
)


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def get_keyring(self):
        return SimpleNamespace(priority=1)

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def get_password(self, service, username):
        return self.values.get((service, username))

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


class FakeBridge:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.calls = []

    def call(self, name, args):
        self.calls.append((name, dict(args)))
        if name == "ide_get_state":
            return {
                "workspace": self.workspace.name,
                "workspace_id": workspace_identity(self.workspace),
                "active_file": "main.gd",
            }
        if name == "ide_open_file":
            return {"opened": args["path"]}
        if name == "ide_focus_panel":
            return {"focused_panel": args["panel"]}
        return {"action": name}


class IDEControlIPCTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        self.registry = Path(self.temp.name) / "private-registry"
        self.keyring = FakeKeyring()
        self.bridge = FakeBridge(self.root)
        self.server = IDEControlIPCServer(
            self.bridge,
            registry_directory=self.registry,
            keyring_api=self.keyring,
        )
        self.endpoint = self.server.start()
        self.client = IDEControlIPCClient(
            self.root,
            registry_directory=self.registry,
            keyring_api=self.keyring,
        )

    def tearDown(self):
        self.server.stop()
        self.temp.cleanup()

    def test_authenticated_client_reads_state_and_navigates(self):
        self.assertEqual(self.endpoint["host"], "127.0.0.1")
        state = self.client.call("ide_get_state")
        self.assertEqual(state["workspace"], "workspace")
        self.assertEqual(state["workspace_id"], workspace_identity(self.root))
        opened = self.client.call("ide_open_file", {"path": "scripts/player.gd"})
        self.assertEqual(opened["opened"], "scripts/player.gd")
        self.assertIn(("ide_open_file", {"path": "scripts/player.gd"}), self.bridge.calls)

    def test_discovery_file_contains_no_secret_and_stop_revokes_token(self):
        entries = self.client._registries()
        self.assertEqual(len(entries), 1)
        registry = entries[0]
        path = next(self.registry.glob("*.json"))
        raw = path.read_text(encoding="utf-8")
        self.assertNotIn(self.server.token, raw)
        self.assertNotIn("token", registry)
        key_id = registry["key_id"]
        self.assertEqual(self.keyring.get_password(KEYRING_SERVICE, key_id), self.server.token)
        self.server.stop()
        self.assertFalse(path.exists())
        self.assertIsNone(self.keyring.get_password(KEYRING_SERVICE, key_id))

    def test_client_cannot_control_a_different_workspace(self):
        other = IDEControlIPCClient(
            self.root.parent / "different",
            registry_directory=self.registry,
            keyring_api=self.keyring,
        )
        with self.assertRaisesRegex(RuntimeError, "No enabled OpenGDS-IDE"):
            other.call("ide_get_state")

    def test_client_and_server_reject_non_allowlisted_actions(self):
        self.assertEqual(len(IDE_CONTROL_ACTIONS), 6)
        with self.assertRaises(ValueError):
            self.client.call("ide_delete_file", {"path": "main.gd"})

        registry = self.client._registries()[0]
        token = self.keyring.get_password(KEYRING_SERVICE, registry["key_id"])
        with self.assertRaisesRegex(RuntimeError, "not allow-listed"):
            IDEControlIPCClient._request(registry, token, "ide_delete_file", {"path": "main.gd"})

    def test_server_rejects_invalid_token(self):
        registry = self.client._registries()[0]
        payload = json.dumps({
            "token": "wrong-token",
            "name": "ide_get_state",
            "args": {},
        }).encode("utf-8") + b"\n"
        with socket.create_connection((registry["host"], registry["port"]), timeout=2) as sock:
            sock.sendall(payload)
            result = json.loads(sock.makefile("rb").readline().decode("utf-8"))
        self.assertFalse(result["ok"])
        self.assertIn("Unauthorized", result["error"])

    def test_registry_rejects_non_loopback_and_invalid_metadata(self):
        entries = self.client._registries()
        path = next(self.registry.glob("*.json"))
        registry = json.loads(path.read_text(encoding="utf-8"))
        registry["host"] = "0.0.0.0"
        path.write_text(json.dumps(registry), encoding="utf-8")
        self.assertEqual(self.client._registries(), [])

    def test_server_requires_a_secure_keyring(self):
        class UnavailableKeyring:
            def get_keyring(self):
                return SimpleNamespace(priority=0)

        server = IDEControlIPCServer(
            self.bridge,
            registry_directory=self.registry.parent / "unavailable",
            keyring_api=UnavailableKeyring(),
        )
        with self.assertRaisesRegex(RuntimeError, "operating-system keyring"):
            server.start()

    def test_server_does_not_expose_workspace_path(self):
        state = self.client.call("ide_get_state")
        self.assertNotIn(str(self.root), str(state))
        self.assertEqual(state["workspace_id"], workspace_identity(self.root))


if __name__ == "__main__":
    unittest.main()
