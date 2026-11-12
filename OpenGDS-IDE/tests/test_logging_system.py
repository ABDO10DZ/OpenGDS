import logging
import os
import tempfile
import unittest
from pathlib import Path

from logging_system import CATEGORY_COLORS, configure_logging, log_event
from backend import OpenGDSBackend


class LoggingSystemTests(unittest.TestCase):
    def test_categories_have_distinct_colors(self):
        self.assertIn("CORE", CATEGORY_COLORS)
        self.assertIn("GDSCRIPT", CATEGORY_COLORS)
        self.assertIn("GDSC", CATEGORY_COLORS)
        self.assertIn("PYTHON", CATEGORY_COLORS)
        self.assertIn("LOGIC", CATEGORY_COLORS)
        self.assertIn("GODOT_ENGINE", CATEGORY_COLORS)
        self.assertNotEqual(CATEGORY_COLORS["GDSCRIPT"], CATEGORY_COLORS["GDSC"])
        self.assertNotEqual(CATEGORY_COLORS["PYTHON"], CATEGORY_COLORS["LOGIC"])

    def test_child_core_log_records_are_merged_into_studio_log(self):
        original_dir = os.environ.get("OPENGDS_LOG_DIR")
        try:
            with tempfile.TemporaryDirectory() as td:
                studio = Path(td) / "studio.log"
                core = Path(td) / "core.log"
                configure_logging(studio)
                core.write_text(
                    "2026-11-12 10:00:00.000 ERROR [GDSC] opengds: GDSC payload invalid\n"
                    "Traceback (most recent call last):\n  ValueError: bad payload\n",
                    encoding="utf-8",
                )
                OpenGDSBackend._merge_core_log(core, 0)
                for handler in logging.getLogger("opengds").handlers:
                    handler.flush()
                content = studio.read_text(encoding="utf-8")
                self.assertIn("[GDSC]", content)
                self.assertIn("GDSC payload invalid", content)
                self.assertIn("ValueError: bad payload", content)
        finally:
            logger = logging.getLogger("opengds")
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()
            if original_dir is None:
                os.environ.pop("OPENGDS_LOG_DIR", None)
            else:
                os.environ["OPENGDS_LOG_DIR"] = original_dir

    def test_file_log_persists_category_level_and_multiline_traceback(self):
        original_dir = os.environ.get("OPENGDS_LOG_DIR")
        try:
            with tempfile.TemporaryDirectory() as td:
                target = Path(td) / "studio.log"
                configure_logging(target)
                log_event("GDSCRIPT", logging.ERROR, "sample.gd:4: parser error")
                try:
                    raise ValueError("sample python failure")
                except ValueError:
                    log_event("PYTHON", logging.ERROR, "test exception", exc_info=True)
                # Flush the dedicated app logger before checking the persisted file.
                for handler in logging.getLogger("opengds").handlers:
                    handler.flush()
                content = target.read_text(encoding="utf-8")
                self.assertIn("[GDSCRIPT]", content)
                self.assertIn("parser error", content)
                self.assertIn("[PYTHON]", content)
                self.assertIn("ValueError: sample python failure", content)
        finally:
            logger = logging.getLogger("opengds")
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()
            if original_dir is None:
                os.environ.pop("OPENGDS_LOG_DIR", None)
            else:
                os.environ["OPENGDS_LOG_DIR"] = original_dir


if __name__ == "__main__":
    unittest.main()
