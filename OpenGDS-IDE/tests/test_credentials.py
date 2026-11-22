"""Cross-platform credential storage tests using a mocked OS keyring."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ai_agent import CredentialStore


class CredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = CredentialStore(self.temp.name)
        self.backend = Mock()
        self.backend.priority = 1
        self.keyring = types.SimpleNamespace(
            get_keyring=Mock(return_value=self.backend),
            set_password=Mock(),
            get_password=Mock(return_value=None),
            delete_password=Mock(),
        )
        self.modules = patch.dict(sys.modules, {"keyring": self.keyring})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def tearDown(self):
        self.temp.cleanup()

    def test_set_uses_os_keyring_and_never_creates_plaintext_file(self):
        self.store.set("OpenAI", "sk-test-secret")
        self.keyring.set_password.assert_called_once_with(
            "OpenGDS-IDE", "OpenAI", "sk-test-secret"
        )
        self.assertEqual(list(Path(self.temp.name).glob("*")), [])

    def test_get_reads_from_os_keyring(self):
        self.keyring.get_password.return_value = "sk-from-keychain"
        self.assertEqual(self.store.get("OpenAI"), "sk-from-keychain")
        self.keyring.get_password.assert_called_once_with("OpenGDS-IDE", "OpenAI")

    def test_empty_key_deletes_keyring_entry(self):
        self.store.set("OpenAI", "")
        self.keyring.delete_password.assert_called_once_with("OpenGDS-IDE", "OpenAI")

    def test_environment_fallback_is_session_only(self):
        with patch.dict(os.environ, {"OPENGDS_AI_API_KEY": "temporary-key"}):
            self.assertEqual(self.store.get("OpenAI"), "temporary-key")
        self.assertEqual(list(Path(self.temp.name).glob("*")), [])

    def test_refuses_insecure_or_missing_keyring_backend(self):
        self.backend.priority = 0
        with self.assertRaisesRegex(RuntimeError, "secure system keyring"):
            self.store.set("OpenAI", "sk-test-secret")

    def test_legacy_dpapi_file_is_not_silently_used_on_non_windows(self):
        legacy = self.store._path("OpenAI")
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(b"legacy-encrypted-data")
        with patch("ai_agent.os.name", "posix"):
            with self.assertRaisesRegex(RuntimeError, "Windows DPAPI"):
                self.store.get("OpenAI")


if __name__ == "__main__":
    unittest.main()
