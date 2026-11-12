import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from language_service import extract_symbols, analyze_gdscript, project_symbols

class LanguageServiceTests(unittest.TestCase):
    def test_extracts_outline_symbols(self):
        source = "class_name Player\n signal damaged\nconst SPEED = 10\nvar health = 100\nfunc move(delta):\n    pass\n"
        symbols = extract_symbols(source)
        self.assertEqual([s.name for s in symbols], ["Player", "damaged", "SPEED", "health", "move"])
        self.assertEqual(symbols[-1].line, 5)
        self.assertEqual(symbols[-1].detail, "move(delta)")

    def test_conservative_diagnostics_find_unclosed_tokens_and_whitespace(self):
        diagnostics = analyze_gdscript('func f():  \n    var x = (1\n')
        messages = [d.message for d in diagnostics]
        self.assertIn("Trailing whitespace", messages)
        self.assertTrue(any("Unclosed delimiter" in m for m in messages))

    def test_project_symbol_index(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "main.gd").write_text("func start_game():\n    pass\n", encoding="utf-8")
            (root / ".godot").mkdir()
            (root / ".godot" / "cache.gd").write_text("func should_not_appear():\n    pass\n", encoding="utf-8")
            self.assertIn("start_game", project_symbols(root))
            self.assertNotIn("should_not_appear", project_symbols(root))

if __name__ == "__main__":
    unittest.main()
