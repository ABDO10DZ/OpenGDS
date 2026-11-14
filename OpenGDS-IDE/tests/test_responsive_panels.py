from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ResponsivePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ai = (ROOT / "ai_panel.py").read_text(encoding="utf-8")
        cls.git = (ROOT / "git_panel.py").read_text(encoding="utf-8")
        cls.main = (ROOT / "main.py").read_text(encoding="utf-8")

    def test_source_control_content_is_scrollable_when_panel_is_reduced(self):
        self.assertIn("self.content_scroll = QScrollArea(self)", self.git)
        self.assertIn("self.content_scroll.setWidgetResizable(True)", self.git)
        self.assertIn("def resizeEvent(self, event):", self.git)
        self.assertIn("self.hint.setVisible(not very_compact)", self.git)

    def test_ai_composer_has_bounded_scrollable_viewport(self):
        self.assertIn("self.composer_scroll = QScrollArea(self)", self.ai)
        self.assertIn("self.composer_scroll.setWidgetResizable(True)", self.ai)
        self.assertIn("root.addWidget(self.composer_scroll, 0)", self.ai)

    def test_ai_chat_changes_and_composer_keep_visible_vertical_scrollbars(self):
        self.assertIn("self.chat.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)", self.ai)
        self.assertIn("self.pending_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)", self.ai)
        self.assertIn("self.composer_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)", self.ai)
        self.assertIn('setObjectName("assistantChatScrollBar")', self.ai)
        self.assertIn('setObjectName("assistantChangesScrollBar")', self.ai)
        self.assertIn('setObjectName("assistantComposerScrollBar")', self.ai)

    def test_ai_prompt_wraps_without_horizontal_scrollbar(self):
        self.assertIn("self.prompt.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)", self.ai)
        self.assertIn("self.prompt.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)", self.ai)

    def test_ai_scrollbar_theme_styles_are_visible_in_both_themes(self):
        self.assertGreaterEqual(self.main.count("QScrollBar#assistantChatScrollBar"), 2)
        self.assertIn("width:12px", self.main)
        self.assertIn("min-height:34px", self.main)

    def test_ai_compact_mode_reflows_controls_without_removing_selection_option(self):
        self.assertIn("def _apply_responsive_layout(self):", self.ai)
        self.assertIn("self.include_selection.setVisible(not narrow)", self.ai)
        self.assertIn('context_menu.addAction("Include editor selection")', self.ai)
        self.assertIn("self.mode_hint.setVisible(not compact)", self.ai)

    def test_very_compact_ai_mode_still_has_a_scrollable_prompt_viewport(self):
        self.assertIn("ultra_compact = height < 285", self.ai)
        self.assertIn("self.composer_scroll.setMinimumHeight(68 if ultra_compact", self.ai)
        self.assertIn("self.prompt.setMinimumHeight(38 if ultra_compact", self.ai)
        self.assertIn("self.provider_label.setVisible(not ultra_compact)", self.ai)

    def test_compact_panel_minimums_allow_docks_to_shrink(self):
        self.assertIn('create_dock("Source Control", "dock.sourceControl", self.git_dock, 220, 150)', self.main)
        self.assertIn('create_dock("AI Assistant", "dock.aiAssistant", self.ai_dock, 280, 160)', self.main)
        self.assertIn("self.changes.setMinimumHeight(72 if very_compact", self.git)

    def test_dock_layout_supports_adaptive_movement_and_floating(self):
        self.assertIn("self.setDockNestingEnabled(True)", self.main)
        self.assertIn("QMainWindow.DockOption.AllowNestedDocks", self.main)
        self.assertIn("QMainWindow.DockOption.AllowTabbedDocks", self.main)
        self.assertIn("QDockWidget.DockWidgetFeature.DockWidgetFloatable", self.main)
        self.assertIn("self.resizeDocks(", self.main)

    def test_edited_modules_parse(self):
        for filename in ("main.py", "ai_panel.py", "git_panel.py"):
            ast.parse((ROOT / filename).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
