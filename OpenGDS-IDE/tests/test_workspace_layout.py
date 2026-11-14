from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "main.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_workspace_uses_native_pyside_qdockwidgets(self):
        self.assertIn("from PySide6.QtWidgets", self.source)
        self.assertIn("QDockWidget", self.source)
        self.assertIn("self.setCentralWidget(self.tabs)", self.source)
        self.assertIn("self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.explorer_dock)", self.source)
        self.assertIn("self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.code_insight_dock)", self.source)
        self.assertIn("self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.output_dock)", self.source)
        self.assertIn("self.setDockNestingEnabled(True)", self.source)
        self.assertIn("QMainWindow.DockOption.AllowNestedDocks", self.source)
        self.assertIn("QMainWindow.DockOption.AllowTabbedDocks", self.source)

    def test_every_panel_is_closable_movable_and_floatable(self):
        self.assertIn("QDockWidget.DockWidgetFeature.DockWidgetClosable", self.source)
        self.assertIn("QDockWidget.DockWidgetFeature.DockWidgetMovable", self.source)
        self.assertIn("QDockWidget.DockWidgetFeature.DockWidgetFloatable", self.source)
        for object_name in (
            "dock.explorer", "dock.sourceControl", "dock.codeInsight",
            "dock.aiAssistant", "dock.output",
        ):
            self.assertIn(object_name, self.source)

    def test_view_menu_has_show_hide_float_and_dock_back_actions(self):
        self.assertIn("dock.toggleViewAction()", self.source)
        self.assertIn('view.addMenu("Panels")', self.source)
        self.assertIn('view.addMenu("Move Panel to Separate Window")', self.source)
        self.assertIn('view.addMenu("Dock Panel Back")', self.source)
        self.assertIn("def float_panel(self, dock)", self.source)
        self.assertIn("dock.setFloating(True)", self.source)
        self.assertIn("def dock_panel(self, dock)", self.source)
        self.assertIn("dock.setFloating(False)", self.source)

    def test_close_reopen_does_not_destroy_panel(self):
        self.assertIn("QDockWidget.DockWidgetFeature.DockWidgetClosable", self.source)
        self.assertIn("dock.toggleViewAction()", self.source)
        self.assertIn("dock.hide()", self.source)
        self.assertIn("dock.show()", self.source)
        self.assertIn("dock.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)", self.source)

    def test_panel_layout_persists_visibility_floating_and_positions(self):
        self.assertIn('self.settings.value("dock_layout_version", 2)', self.source)
        self.assertIn('self.restoreState(state, 5)', self.source)
        self.assertIn('self.settings.setValue("dock_state", self.saveState(5))', self.source)
        self.assertIn('self.settings.setValue("dock_layout_version", 2)', self.source)

    def test_default_layout_restores_all_five_tool_panels(self):
        self.assertIn("def restore_default_dock_layout", self.source)
        self.assertIn("for dock in self._all_tool_panels:", self.source)
        self.assertIn("dock.show()", self.source)
        self.assertIn("self._dock_last_areas = dict(self._dock_default_areas)", self.source)

    def test_dock_back_uses_last_known_area(self):
        self.assertIn("self._dock_last_areas.get(dock, self._dock_default_areas[dock])", self.source)
        self.assertIn("self.addDockWidget(fallback_area, dock)", self.source)
        self.assertIn("restored_area = self.dockWidgetArea(dock)", self.source)
        self.assertIn("def _sync_dock_areas(self)", self.source)

    def test_existing_ai_git_components_remain_the_dock_contents(self):
        ai_source = (ROOT / "ai_panel.py").read_text(encoding="utf-8")
        git_source = (ROOT / "git_panel.py").read_text(encoding="utf-8")
        self.assertIn("class AIAgentDock(QWidget):", ai_source)
        self.assertIn("class GitDock(QWidget):", git_source)
        self.assertIn('create_dock("AI Assistant", "dock.aiAssistant", self.ai_dock', self.source)
        self.assertIn('create_dock("Source Control", "dock.sourceControl", self.git_dock', self.source)

    def test_open_gds_core_update_supports_python_and_standalone_cli(self):
        self.assertIn("Update OpenGDS Core…", self.source)
        self.assertIn("OpenGDS.py opengds-cli.exe *.py *.exe", self.source)
        self.assertIn("Standalone OpenGDS CLI configured successfully", self.source)
        backend = (ROOT / "backend.py").read_text(encoding="utf-8")
        self.assertIn("self.standalone_executable", backend)
        self.assertIn("find_python_command", backend)


    def test_docked_workspace_resize_separators_are_visible_in_both_themes(self):
        for selector in (
            "QMainWindow::separator",
            "QMainWindow::separator:horizontal",
            "QMainWindow::separator:vertical",
        ):
            self.assertIn(selector, self.source)
        self.assertGreaterEqual(self.source.count("min-height:9px"), 2)
        self.assertGreaterEqual(self.source.count("min-width:9px"), 2)
        self.assertIn("QMainWindow::separator:hover", self.source)
        self.assertIn("QMainWindow::separator:pressed", self.source)

    def test_dock_titlebar_has_explicit_float_and_close_controls(self):
        self.assertIn("class DockTitleBar(QWidget):", self.source)
        self.assertIn('self.float_button.setObjectName("dockFloatButton")', self.source)
        self.assertIn('self.close_button.setObjectName("dockCloseButton")', self.source)
        self.assertIn("self.float_button.clicked.connect(self._toggle_floating)", self.source)
        self.assertIn("self.close_button.clicked.connect(dock.close)", self.source)
        self.assertIn("dock.setTitleBarWidget(DockTitleBar(dock))", self.source)
        # Drag events must propagate to QDockWidget so native detach/redock remains available.
        self.assertIn("def mousePressEvent(self, event):", self.source)
        self.assertIn("def mouseMoveEvent(self, event):", self.source)
        self.assertIn("def mouseDoubleClickEvent(self, event):", self.source)
        self.assertIn("event.ignore()", self.source)

    def test_dock_layout_schema_migrates_to_visible_grip_layout(self):
        self.assertIn('self.settings.value("dock_layout_version", 2)', self.source)
        self.assertIn('state = self.settings.value("dock_state") if version == 2 else None', self.source)
        self.assertIn('self.settings.setValue("dock_layout_version", 2)', self.source)

    def test_application_uses_only_pyside6_bindings_not_pyqt_or_qtpy(self):
        for path in ROOT.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("from PyQt", text, path.name)
            self.assertNotIn("import PyQt", text, path.name)
            self.assertNotIn("import qtpy", text, path.name)
            self.assertNotIn("from qtpy", text, path.name)
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("PySide6", requirements)
        self.assertNotIn("PyQt", requirements)
        self.assertNotIn("qtpy", requirements)

    def test_main_module_is_valid_python(self):
        compile(self.tree, str(ROOT / "main.py"), "exec")


if __name__ == "__main__":
    unittest.main()
