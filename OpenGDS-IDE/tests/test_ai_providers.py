import unittest

from ai_models import describe_model, register_model_capabilities
from ai_providers import AnthropicAdapter, OpenAICompatibleAdapter, get_provider_adapter


class ProviderAdapterTests(unittest.TestCase):
    def test_openai_compatible_endpoint_and_auth_headers(self):
        adapter = get_provider_adapter("openai")
        self.assertIsInstance(adapter, OpenAICompatibleAdapter)
        self.assertEqual(adapter.chat_endpoint("https://api.example/v1/"), "https://api.example/v1/chat/completions")
        self.assertEqual(adapter.chat_endpoint("https://api.example/v1/chat/completions"), "https://api.example/v1/chat/completions")
        self.assertEqual(adapter.headers("secret")["Authorization"], "Bearer secret")

    def test_openrouter_headers_are_provider_specific(self):
        headers = get_provider_adapter("openai").headers("key", "OpenRouter Free")
        self.assertEqual(headers["HTTP-Referer"], "https://github.com/ABDO10DZ/OpenGDS")
        self.assertEqual(headers["X-Title"], "OpenGDS-IDE")

    def test_anthropic_endpoint_and_headers(self):
        adapter = get_provider_adapter("anthropic")
        self.assertIsInstance(adapter, AnthropicAdapter)
        self.assertEqual(adapter.chat_endpoint("https://api.anthropic.com/v1"), "https://api.anthropic.com/v1/messages")
        self.assertEqual(adapter.headers("secret")["x-api-key"], "secret")
        self.assertNotIn("Authorization", adapter.headers("secret"))

    def test_unknown_protocol_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported AI provider protocol"):
            get_provider_adapter("unknown")

    def test_model_capabilities_remain_unknown_until_verified(self):
        model = describe_model("Custom", "model-x", "openai")
        self.assertIsNone(model.tool_calling)
        self.assertIsNone(model.context_window)

    def test_verified_model_capabilities_can_be_registered(self):
        register_model_capabilities("TestProvider", "model-y", streaming=True,
                                   tool_calling=True, vision=False, context_window=32768)
        model = describe_model("testprovider", "model-y", "openai")
        self.assertTrue(model.streaming)
        self.assertTrue(model.tool_calling)
        self.assertFalse(model.vision)
        self.assertEqual(model.context_window, 32768)


if __name__ == "__main__":
    unittest.main()
