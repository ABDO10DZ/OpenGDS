import tempfile
import unittest
from pathlib import Path

from ai_agent import AgentCancelled, AgentConfig, AgentEngine, OPENAI_TOOLS, PROVIDERS
from types import SimpleNamespace


class AgentEngineTests(unittest.TestCase):

    def test_openai_stream_forwards_text_and_reassembles_tool_call_fragments(self):
        import json
        from unittest.mock import patch
        class Headers:
            def get(self, key, default=""):
                return "text/event-stream" if key.lower() == "content-type" else default
        class Response:
            headers = Headers()
            def __init__(self, rows):
                self.rows = [("data: " + json.dumps(row) + "\n\n").encode() for row in rows]
                self.closed = False
            def __iter__(self):
                return iter(self.rows)
            def close(self):
                self.closed = True
        rows = [
            {"choices": [{"delta": {"content": "Hello "}}]},
            {"choices": [{"delta": {"content": "OpenGDS"}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call-1", "function": {"name": "read_", "arguments": "{\"path\":"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "file", "arguments": "\"README.md\"}"}}]}, "finish_reason": "tool_calls"}]},
        ]
        response = Response(rows)
        with tempfile.TemporaryDirectory() as td:
            engine = AgentEngine(td, AgentConfig())
            streamed = []
            with patch("ai_agent.urllib.request.urlopen", return_value=response):
                result = engine._post_stream("https://example.invalid/chat", {}, {"stream": True}, 10, on_delta=streamed.append)
        message = result["choices"][0]["message"]
        self.assertEqual("".join(streamed), "Hello OpenGDS")
        self.assertEqual(message["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(json.loads(message["tool_calls"][0]["function"]["arguments"]), {"path": "README.md"})
        self.assertTrue(response.closed)

    def test_opengds_native_tools_are_available_only_in_opengds_focus(self):
        with tempfile.TemporaryDirectory() as td:
            gd = AgentEngine(td, AgentConfig(scope="gdscript", agent_mode="agent"))
            names = [item["function"]["name"] for item in gd.available_tools()]
            self.assertNotIn("opengds_inspect", names)
            core = AgentEngine(td, AgentConfig(scope="opengds", agent_mode="agent"))
            names = [item["function"]["name"] for item in core.available_tools()]
            self.assertIn("opengds_inspect", names)
            self.assertIn("opengds_decompile", names)
            self.assertIn("opengds_compile", names)
            ask = AgentEngine(td, AgentConfig(scope="opengds", agent_mode="ask"))
            names = [item["function"]["name"] for item in ask.available_tools()]
            self.assertIn("opengds_inspect", names)
            self.assertNotIn("opengds_decompile", names)
            self.assertNotIn("opengds_compile", names)

    def test_opengds_inspection_uses_internal_backend_api(self):
        class FakeBackend:
            def inspect(self, mode, path, **kwargs):
                return f"{mode}: {Path(path).name} inspected"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sample.gdc").write_bytes(b"GDSC")
            engine = AgentEngine(root, AgentConfig(scope="opengds", agent_mode="ask"), backend=FakeBackend())
            result = engine._execute_tool("opengds_inspect", {"mode": "info", "path": "sample.gdc"})
            self.assertIn("info: sample.gdc inspected", result["report"])

    def test_cancelled_native_open_gds_operation_propagates_cancellation(self):
        class FakeBackend:
            def inspect(self, mode, path, cancel_event=None):
                cancel_event.set()
                raise RuntimeError("process interrupted")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sample.gdc").write_bytes(b"GDSC")
            engine = AgentEngine(root, AgentConfig(scope="opengds", agent_mode="ask"), backend=FakeBackend())
            import threading
            cancellation = threading.Event()
            engine._request_cancel_event = cancellation
            with self.assertRaises(AgentCancelled):
                engine._execute_tool("opengds_inspect", {"mode": "info", "path": "sample.gdc"})

    def test_opengds_decompile_is_queued_and_only_written_after_approval(self):
        class FakeBackend:
            def decompile(self, path, **kwargs):
                return "extends Node\nfunc _ready():\n    pass\n"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sample.gdc").write_bytes(b"GDSC")
            engine = AgentEngine(root, AgentConfig(scope="opengds"), backend=FakeBackend())
            result = engine._execute_tool("opengds_decompile", {"path": "sample.gdc", "reason": "Recover source"})
            target = root / "sample.gd"
            self.assertTrue(result["queued_for_approval"])
            self.assertFalse(target.exists())
            self.assertIn("_ready", engine.preview(result["action_id"]))
            engine.approve(result["action_id"])
            self.assertIn("_ready", target.read_text(encoding="utf-8"))

    def test_opengds_compile_is_queued_and_runs_internal_backend_after_approval(self):
        class FakeBackend:
            def __init__(self):
                self.calls = []
            def compile(self, source, output, **kwargs):
                self.calls.append((Path(source), Path(output), kwargs))
                Path(output).write_bytes(b"COMPILED-GDSC")
                return SimpleNamespace(stdout="compiled")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sample.gd").write_text("extends Node\n", encoding="utf-8")
            backend = FakeBackend()
            engine = AgentEngine(root, AgentConfig(scope="opengds"), backend=backend)
            result = engine._execute_tool("opengds_compile", {"path": "sample.gd", "reason": "Build bytecode"})
            target = root / "sample.gdc"
            self.assertTrue(result["queued_for_approval"])
            self.assertFalse(target.exists())
            self.assertIn("OPEN GDSC COMPILE OPERATION", engine.preview(result["action_id"]))
            message = engine.approve(result["action_id"])
            self.assertTrue(target.is_file())
            self.assertIn("compiled", message)
            self.assertEqual(len(backend.calls), 1)

    def test_opengds_compile_rejects_stale_source_before_running_backend(self):
        class FakeBackend:
            called = False
            def compile(self, source, output, **kwargs):
                self.called = True
                Path(output).write_bytes(b"compiled")
                return SimpleNamespace(stdout="compiled")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "sample.gd"
            source.write_text("original\n", encoding="utf-8")
            backend = FakeBackend()
            engine = AgentEngine(root, AgentConfig(scope="opengds"), backend=backend)
            result = engine._execute_tool("opengds_compile", {"path": "sample.gd", "reason": "Build"})
            source.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "source conflict"):
                engine.approve(result["action_id"])
            self.assertFalse(backend.called)

    def test_ask_mode_exposes_only_read_only_tools(self):
        with tempfile.TemporaryDirectory() as td:
            engine = AgentEngine(td, AgentConfig(agent_mode="ask"))
            names = [item["function"]["name"] for item in engine.available_tools()]
            self.assertEqual(names, ["list_files", "read_file", "search_text"])
            self.assertNotIn("propose_change", names)
            self.assertNotIn("propose_command", names)

    def test_agent_mode_exposes_approval_gated_change_tools(self):
        with tempfile.TemporaryDirectory() as td:
            engine = AgentEngine(td, AgentConfig(agent_mode="agent"))
            names = [item["function"]["name"] for item in engine.available_tools()]
            self.assertIn("propose_change", names)
            self.assertIn("propose_command", names)

    def test_free_provider_presets_are_available_by_default(self):
        self.assertEqual(AgentConfig().provider, "OpenRouter Free")
        self.assertEqual(AgentConfig().model, "openrouter/free")
        self.assertTrue(PROVIDERS["OpenRouter Free"]["requires_api_key"])
        self.assertFalse(PROVIDERS["Ollama Local"]["requires_api_key"])
        self.assertTrue(PROVIDERS["Gemini Free Tier"]["requires_api_key"])
        self.assertTrue(PROVIDERS["Groq Free Tier"]["requires_api_key"])

    def test_gdscript_focus_filters_context_and_blocks_unrelated_file_reads(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "player.gd").write_text("extends Node\n", encoding="utf-8")
            (root / "tool.py").write_text("print('not in GDScript focus')\n", encoding="utf-8")
            engine = AgentEngine(root, AgentConfig(scope="gdscript"))
            self.assertIn("player.gd", engine._project_files())
            self.assertNotIn("tool.py", engine._project_files())
            result = engine._execute_tool("read_file", {"path": "tool.py"})
            self.assertIn("error", result)

    def test_opengds_focus_allows_core_sources_and_blocks_game_scripts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "backend.py").write_text("class Backend: pass\n", encoding="utf-8")
            (root / "player.gd").write_text("extends Node\n", encoding="utf-8")
            (root / "scene.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")
            engine = AgentEngine(root, AgentConfig(scope="opengds"))
            self.assertIn("backend.py", engine._project_files())
            self.assertIn("player.gd", engine._project_files())
            self.assertNotIn("scene.tscn", engine._project_files())
            result = engine._execute_tool("propose_change", {
                "operation": "write", "path": "scene.tscn", "content": "[gd_scene format=3]\n", "reason": "test"
            })
            self.assertIn("error", result)

    def test_semantic_embeddings_use_openai_compatible_endpoint_and_cache_workspace_vectors(self):
        import json
        from unittest.mock import patch

        class Response:
            def __init__(self, body):
                self.body = body
            def read(self, _limit=-1):
                return self.body
            def close(self):
                pass

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "player.gd").write_text("extends Node\nfunc move_player():\n    velocity = Vector2.ZERO\n", encoding="utf-8")
            config = AgentConfig(provider="OpenAI", model="chat-model", base_url="https://api.openai.com/v1",
                                 api_key="test-key", use_embeddings=True, embedding_model="text-embedding-test")
            engine = AgentEngine(root, config)
            calls = []
            def fake_urlopen(request, timeout=0):
                payload = json.loads(request.data.decode("utf-8"))
                calls.append((request.full_url, payload, request.headers.get("Authorization")))
                vectors = [[1.0, 0.0] if index == 0 else [0.9, 0.1] for index, _ in enumerate(payload["input"])]
                return Response(json.dumps({"data": [{"index": index, "embedding": vector}
                                                  for index, vector in enumerate(vectors)]}).encode())
            with patch("ai_agent.urllib.request.urlopen", side_effect=fake_urlopen):
                context = engine._semantic_workspace_context("How is the player moved?")
                self.assertIn("player.gd", context)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][0], "https://api.openai.com/v1/embeddings")
                self.assertEqual(calls[0][1]["model"], "text-embedding-test")
                # The next query asks only for a query vector; the cached file vector is reused.
                engine._semantic_workspace_context("How do I move the player?")
                self.assertEqual(len(calls), 2)
                self.assertEqual(len(calls[1][1]["input"]), 1)

    def test_explicit_change_request_forces_tools_and_warns_when_no_proposal_is_returned(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            engine = AgentEngine(td, AgentConfig(api_key="test", agent_mode="agent"))
            response = {"choices": [{"message": {"content": "Approve the change when ready."}}]}
            with patch.object(engine, "_post_stream", return_value=response) as post:
                answer = engine._openai_chat("Please fix the broken GDScript file.", "")
            payload = post.call_args.args[2]
            self.assertEqual(payload["tool_choice"], "required")
            self.assertIn("No reviewable code change was prepared", answer)
            self.assertEqual(engine.pending_actions(), [])

    def test_semantic_embeddings_support_a_separate_custom_endpoint(self):
        import json
        from unittest.mock import patch

        class Response:
            def read(self, _limit=-1):
                return json.dumps({"data": [{"index": 0, "embedding": [1.0, 0.0]}]}).encode()
            def close(self):
                pass

        with tempfile.TemporaryDirectory() as td:
            engine = AgentEngine(td, AgentConfig(
                provider="OpenRouter Free", base_url="https://openrouter.ai/api/v1",
                api_key="test", embedding_model="custom-embedding-model",
                embeddings_url="https://embeddings.example/v1/embeddings"))
            with patch("ai_agent.urllib.request.urlopen", return_value=Response()) as request:
                vectors = engine._request_embeddings(["source context"])
            self.assertEqual(vectors, [[1.0, 0.0]])
            self.assertEqual(request.call_args.args[0].full_url,
                             "https://embeddings.example/v1/embeddings")

    def test_semantic_embeddings_reject_insecure_non_local_custom_endpoint(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            engine = AgentEngine(td, AgentConfig(
                provider="OpenAI", api_key="test", embedding_model="test-model",
                embeddings_url="http://embeddings.example/v1/embeddings"))
            with patch("ai_agent.urllib.request.urlopen") as request:
                with self.assertRaisesRegex(ValueError, "HTTPS URL"):
                    engine._request_embeddings(["source context"])
                request.assert_not_called()

    def test_claude_chat_can_use_a_separate_embeddings_endpoint(self):
        import json
        from unittest.mock import patch

        class Response:
            def read(self, _limit=-1):
                return json.dumps({"data": [{"index": 0, "embedding": [0.25, 0.75]}]}).encode()
            def close(self):
                pass

        with tempfile.TemporaryDirectory() as td:
            engine = AgentEngine(td, AgentConfig(
                provider="Claude", base_url="https://api.anthropic.com/v1", api_key="test",
                embedding_model="vector-model", embeddings_url="https://vectors.example/v1/embeddings"))
            with patch("ai_agent.urllib.request.urlopen", return_value=Response()) as request:
                self.assertEqual(engine._request_embeddings(["sample"]), [[0.25, 0.75]])
            self.assertEqual(request.call_args.args[0].full_url,
                             "https://vectors.example/v1/embeddings")

    def test_semantic_embeddings_reject_anthropic_native_endpoint(self):
        with tempfile.TemporaryDirectory() as td:
            engine = AgentEngine(td, AgentConfig(provider="Claude", model="claude-test",
                                  base_url="https://api.anthropic.com/v1", api_key="test",
                                  use_embeddings=True, embedding_model="embedding-model"))
            with self.assertRaisesRegex(RuntimeError, "does not expose"):
                engine._request_embeddings(["text"])

    def test_workspace_read_and_list_tools(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "scripts").mkdir()
            (root / "scripts" / "player.gd").write_text("extends Node\n", encoding="utf-8")
            engine = AgentEngine(root, AgentConfig())
            listing = engine._execute_tool("list_files", {"limit": 50})
            self.assertIn("scripts/player.gd", listing["files"])
            result = engine._execute_tool("read_file", {"path": "scripts/player.gd"})
            self.assertIn("extends Node", result["content"])

    def test_proposed_file_change_is_not_applied_until_approved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "scripts" / "player.gd"
            target.parent.mkdir()
            target.write_text("extends Node\n", encoding="utf-8")
            engine = AgentEngine(root, AgentConfig())
            result = engine._execute_tool("propose_change", {
                "operation": "write", "path": "scripts/player.gd",
                "content": "extends Node\nfunc _ready():\n    pass\n", "reason": "Add ready callback"
            })
            self.assertTrue(result["queued_for_approval"])
            self.assertEqual(target.read_text(encoding="utf-8"), "extends Node\n")
            self.assertIn("func _ready", engine.preview(result["action_id"]))
            engine.approve(result["action_id"])
            self.assertIn("func _ready", target.read_text(encoding="utf-8"))

    def test_stale_proposal_is_rejected_without_overwriting_newer_edits(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "file.gd"
            target.write_text("original\n", encoding="utf-8")
            engine = AgentEngine(root, AgentConfig())
            result = engine._execute_tool("propose_change", {
                "operation": "write", "path": "file.gd", "content": "agent edit\n", "reason": "test"
            })
            target.write_text("user edit\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "overlapping lines"):
                engine.approve(result["action_id"])
            self.assertEqual(target.read_text(encoding="utf-8"), "user edit\n")

    def test_stale_proposal_merges_non_overlapping_user_edits(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "file.gd"
            base = "extends Node\nvar first = 1\nvar second = 2\n"
            target.write_text(base, encoding="utf-8")
            engine = AgentEngine(root, AgentConfig())
            result = engine._execute_tool("propose_change", {
                "operation": "write", "path": "file.gd",
                "content": "extends Node\nvar first = 10\nvar second = 2\n", "reason": "Change first value"
            })
            target.write_text("extends Node\nvar first = 1\nvar second = 20\n", encoding="utf-8")
            message = engine.approve(result["action_id"])
            self.assertIn("merging non-overlapping", message)
            self.assertEqual(target.read_text(encoding="utf-8"),
                             "extends Node\nvar first = 10\nvar second = 20\n")

    def test_crlf_files_merge_lf_ai_proposals_without_false_conflicts_and_keep_crlf(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "file.gd"
            base = "extends Node\r\nvar first = 1\r\nvar second = 2\r\n"
            target.write_bytes(base.encode("utf-8"))
            engine = AgentEngine(root, AgentConfig())
            first = engine._execute_tool("propose_change", {
                "operation": "write", "path": "file.gd",
                "content": "extends Node\nvar first = 10\nvar second = 2\n",
                "reason": "Change first value"
            })
            self.assertIn("action_id", first, first)
            target.write_bytes("extends Node\r\nvar first = 1\r\nvar second = 20\r\n".encode("utf-8"))
            message = engine.approve(first["action_id"])
            self.assertIn("merging non-overlapping", message)
            raw = target.read_bytes()
            self.assertEqual(raw, b"extends Node\r\nvar first = 10\r\nvar second = 20\r\n")

    def test_multiple_crlf_file_proposals_keep_action_ids_and_merge(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "file.gd"
            target.write_bytes(b"extends Node\r\nvar first = 1\r\nvar second = 2\r\n")
            engine = AgentEngine(root, AgentConfig())
            first = engine._execute_tool("propose_change", {
                "operation": "write", "path": "file.gd",
                "content": "extends Node\nvar first = 10\nvar second = 2\n", "reason": "First edit"
            })
            second = engine._execute_tool("propose_change", {
                "operation": "write", "path": "file.gd",
                "content": "extends Node\nvar first = 1\nvar second = 20\n", "reason": "Second edit"
            })
            self.assertIn("action_id", first, first)
            self.assertIn("action_id", second, second)
            self.assertEqual(len(engine.pending_actions()), 1)
            engine.approve(second["action_id"])
            self.assertEqual(target.read_bytes(), b"extends Node\r\nvar first = 10\r\nvar second = 20\r\n")

    def test_multiple_proposals_for_same_file_are_combined_or_rejected_safely(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "file.gd"
            base = "extends Node\nvar first = 1\nvar second = 2\n"
            target.write_text(base, encoding="utf-8")
            engine = AgentEngine(root, AgentConfig())
            first = engine._execute_tool("propose_change", {
                "operation": "write", "path": "file.gd",
                "content": "extends Node\nvar first = 10\nvar second = 2\n", "reason": "First edit"
            })
            second = engine._execute_tool("propose_change", {
                "operation": "write", "path": "file.gd",
                "content": "extends Node\nvar first = 1\nvar second = 20\n", "reason": "Second edit"
            })
            pending = engine.pending_actions()
            self.assertEqual(len(pending), 1)
            self.assertNotEqual(first["action_id"], second["action_id"])
            engine.approve(second["action_id"])
            self.assertEqual(target.read_text(encoding="utf-8"),
                             "extends Node\nvar first = 10\nvar second = 20\n")

    def test_multiple_file_proposals_rebase_across_user_updated_snapshots(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "file.gd"
            base = "extends Node\nvar first = 1\nvar second = 2\nvar third = 3\n"
            target.write_text(base, encoding="utf-8")
            engine = AgentEngine(root, AgentConfig())
            first = engine._execute_tool("propose_change", {
                "operation": "write", "path": "file.gd",
                "content": "extends Node\nvar first = 10\nvar second = 2\nvar third = 3\n",
                "reason": "Change first value"
            })
            latest_disk = "extends Node\nvar first = 1\nvar second = 2\nvar third = 30\n"
            target.write_text(latest_disk, encoding="utf-8")
            second = engine._execute_tool("propose_change", {
                "operation": "write", "path": "file.gd",
                "content": "extends Node\nvar first = 1\nvar second = 20\nvar third = 30\n",
                "reason": "Change second value"
            })
            pending = engine.pending_actions()
            self.assertEqual(len(pending), 1)
            engine.approve(second["action_id"])
            self.assertEqual(target.read_text(encoding="utf-8"),
                             "extends Node\nvar first = 10\nvar second = 20\nvar third = 30\n")

    def test_overlapping_multiple_proposals_are_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "file.gd"
            target.write_text("var count = 1\n", encoding="utf-8")
            engine = AgentEngine(root, AgentConfig())
            first = engine._execute_tool("propose_change", {
                "operation": "write", "path": "file.gd", "content": "var count = 2\n", "reason": "First"
            })
            second = engine._execute_tool("propose_change", {
                "operation": "write", "path": "file.gd", "content": "var count = 3\n", "reason": "Second"
            })
            self.assertIn("error", second)
            self.assertEqual(len(engine.pending_actions()), 1)
            self.assertEqual(engine.pending_actions()[0].action_id, first["action_id"])
            self.assertEqual(target.read_text(encoding="utf-8"), "var count = 1\n")

    def test_path_traversal_and_secret_reads_are_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".env").write_text("SECRET=value", encoding="utf-8")
            engine = AgentEngine(root, AgentConfig())
            self.assertIn("error", engine._execute_tool("read_file", {"path": "../outside.txt"}))
            self.assertIn("error", engine._execute_tool("read_file", {"path": ".env"}))
            self.assertIn("error", engine._execute_tool("read_file", {"path": "private.pfx"}))

    def test_all_env_variants_and_windows_absolute_paths_are_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".env.production.local").write_text("SECRET=value", encoding="utf-8")
            (root / ".env.d").mkdir()
            (root / ".env.d" / "credentials.txt").write_text("SECRET=value", encoding="utf-8")
            engine = AgentEngine(root, AgentConfig())
            result = engine._execute_tool("read_file", {"path": ".env.production.local"})
            self.assertIn("error", result)
            nested = engine._execute_tool("read_file", {"path": ".env.d/credentials.txt"})
            self.assertIn("error", nested)
            self.assertNotIn(".env.production.local", engine._execute_tool("list_files", {})["files"])
            with self.assertRaises(ValueError):
                engine._safe_path(r"C:\Users\Public\outside.txt")

    def test_external_plain_http_provider_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            config = AgentConfig(provider="Custom OpenAI-compatible", model="test-model",
                                 api_key="not-a-real-key", base_url="http://example.com/v1")
            engine = AgentEngine(td, config)
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                engine.ask("hello")

    def test_localhost_http_provider_url_is_allowed_by_url_policy(self):
        with tempfile.TemporaryDirectory() as td:
            config = AgentConfig(provider="Custom OpenAI-compatible", model="test-model",
                                 api_key="not-a-real-key", base_url="http://127.0.0.1:1234/v1")
            engine = AgentEngine(td, config)
            # The URL passes policy and proceeds to the network call, which fails
            # because the test intentionally does not run a local model server.
            with self.assertRaises(Exception) as caught:
                engine.ask("hello")
            self.assertNotIn("HTTPS", str(caught.exception))

    def test_command_is_queued_and_not_executed_until_approved(self):
        import sys
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            marker = root / "executed.txt"
            engine = AgentEngine(root, AgentConfig())
            result = engine._execute_tool("propose_command", {
                "argv": [sys.executable, "-c", f"from pathlib import Path; Path(r'{marker}').write_text('yes')"],
                "reason": "Create test marker"
            })
            self.assertTrue(result["queued_for_approval"])
            self.assertEqual(result["cwd"], ".")
            self.assertFalse(marker.exists())
            engine.approve(result["action_id"])
            self.assertEqual(marker.read_text(encoding="utf-8"), "yes")


if __name__ == "__main__":
    unittest.main()
