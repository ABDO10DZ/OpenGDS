import logging
import os
import tempfile
import unittest
from pathlib import Path

from logging_system import CATEGORY_COLORS, configure_logging, close_logging, log_event
from backend import OpenGDSBackend


class LoggingSystemTests(unittest.TestCase):
    def test_categories_have_distinct_colors(self):
        self.assertIn("CORE", CATEGORY_COLORS)
        self.assertIn("GDSCRIPT", CATEGORY_COLORS)
        self.assertIn("GDSC", CATEGORY_COLORS)
        self.assertIn("PYTHON", CATEGORY_COLORS)
        self.assertIn("LOGIC", CATEGORY_COLORS)
        self.assertIn("GODOT_ENGINE", CATEGORY_COLORS)
        self.assertIn("AI", CATEGORY_COLORS)
        self.assertIn("GIT", CATEGORY_COLORS)
        self.assertNotEqual(CATEGORY_COLORS["GDSCRIPT"], CATEGORY_COLORS["GDSC"])
        self.assertNotEqual(CATEGORY_COLORS["PYTHON"], CATEGORY_COLORS["LOGIC"])

    def test_close_logging_detaches_and_closes_file_stream(self):
        original_dir = os.environ.get("OPENGDS_LOG_DIR")
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "opengds-ide.log"
            try:
                configure_logging(target)
                logger = logging.getLogger("opengds")
                handlers = list(logger.handlers)
                self.assertTrue(handlers)
                log_event("SYSTEM", logging.INFO, "close test")
                close_logging()
                self.assertEqual(logger.handlers, [])
                for handler in handlers:
                    self.assertIsNone(getattr(handler, "stream", None))
            finally:
                close_logging()
                if original_dir is None:
                    os.environ.pop("OPENGDS_LOG_DIR", None)
                else:
                    os.environ["OPENGDS_LOG_DIR"] = original_dir

    def test_child_core_log_records_are_merged_into_opengds_ide_log(self):
        original_dir = os.environ.get("OPENGDS_LOG_DIR")
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "opengds-ide.log"
            core = Path(td) / "core.log"
            try:
                configure_logging(target)
                core.write_text(
                    "2026-11-12 10:00:00.000 ERROR [GDSC] opengds: GDSC payload invalid\n"
                    "Traceback (most recent call last):\n  ValueError: bad payload\n",
                    encoding="utf-8",
                )
                OpenGDSBackend._merge_core_log(core, 0)
                for handler in logging.getLogger("opengds").handlers:
                    handler.flush()
                content = target.read_text(encoding="utf-8")
                self.assertIn("[GDSC]", content)
                self.assertIn("GDSC payload invalid", content)
                self.assertIn("ValueError: bad payload", content)
            finally:
                # The logger must release the Windows file handle before the
                # TemporaryDirectory context manager removes its contents.
                close_logging()
                if original_dir is None:
                    os.environ.pop("OPENGDS_LOG_DIR", None)
                else:
                    os.environ["OPENGDS_LOG_DIR"] = original_dir

    def test_file_log_persists_category_level_and_multiline_traceback(self):
        original_dir = os.environ.get("OPENGDS_LOG_DIR")
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "opengds-ide.log"
            try:
                configure_logging(target)
                log_event("GDSCRIPT", logging.ERROR, "sample.gd:4: parser error")
                try:
                    raise ValueError("sample python failure")
                except ValueError:
                    log_event("PYTHON", logging.ERROR, "test exception", exc_info=True)
                for handler in logging.getLogger("opengds").handlers:
                    handler.flush()
                content = target.read_text(encoding="utf-8")
                self.assertIn("[GDSCRIPT]", content)
                self.assertIn("parser error", content)
                self.assertIn("[PYTHON]", content)
                self.assertIn("ValueError: sample python failure", content)
            finally:
                # Close before TemporaryDirectory cleanup on Windows.
                close_logging()
                if original_dir is None:
                    os.environ.pop("OPENGDS_LOG_DIR", None)
                else:
                    os.environ["OPENGDS_LOG_DIR"] = original_dir


if __name__ == "__main__":
    unittest.main()
