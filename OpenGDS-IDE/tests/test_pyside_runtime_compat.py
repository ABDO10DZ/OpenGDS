"""Regression guard for the PySide6 6.12.0 CPython bool refcount bug."""
from __future__ import annotations

import importlib.metadata
import re
import sys
import unittest

from PySide6.QtCore import QObject, Signal


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3])


class PySideRuntimeCompatibilityTests(unittest.TestCase):
    def test_bad_pyside_release_is_not_used_on_pre_312_python(self):
        if sys.version_info >= (3, 12):
            self.skipTest("The upstream bool_dealloc defect affects CPython 3.10/3.11.")
        version = _version_tuple(importlib.metadata.version("PySide6"))
        self.assertNotEqual(
            version[:3],
            (6, 12, 0),
            "PySide6 6.12.0 decrements the Py_True reference count on every Signal.emit().",
        )
        self.assertLess(version, (6, 12, 0))

    @unittest.skipUnless(sys.version_info < (3, 12), "CPython 3.12+ uses immortal bool singletons.")
    def test_signal_emit_preserves_true_reference_count(self):
        class Emitter(QObject):
            fired = Signal()

        emitter = Emitter()
        before = sys.getrefcount(True)
        for _ in range(100):
            emitter.fired.emit()
        after = sys.getrefcount(True)
        self.assertEqual(
            after,
            before,
            "A Qt signal emission changed the singleton True reference count.",
        )


if __name__ == "__main__":
    unittest.main()
