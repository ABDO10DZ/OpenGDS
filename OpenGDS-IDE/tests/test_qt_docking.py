"""Real PySide6 docking interaction tests for the IDE tool windows.

Run with the IDE environment:
    .venv\\Scripts\\python.exe -m unittest tests.test_qt_docking -v
"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt, QSettings, QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDockWidget, QPushButton, QToolButton
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, "PySide6 is not installed; run with the IDE's Windows venv")
class NativeWorkspaceDockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._settings_dir = tempfile.TemporaryDirectory(prefix="opengds-dock-settings-")
        cls._log_dir = tempfile.TemporaryDirectory(prefix="opengds-dock-logs-")
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, cls._settings_dir.name)
        os.environ["OPENGDS_LOG_DIR"] = cls._log_dir.name
        cls.app = QApplication.instance() or QApplication([])
        import main as main_module
        cls.main_module = main_module
        cls.window = main_module.MainWindow()
        cls.window.resize(1600, 1000)
        cls.window.show()
        cls.app.processEvents()
        QTest.qWait(150)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.window.close()
            cls.app.processEvents()
        finally:
            cls._settings_dir.cleanup()
            cls._log_dir.cleanup()

    def setUp(self):
        self.window.restore_default_dock_layout(show_message=False)
        self.app.processEvents()
        QTest.qWait(40)
        self.docks = self.window._all_tool_panels

    def test_gdc_report_actions_leave_dock_dividers_room_to_move(self):
        source = Path(self._settings_dir.name) / "sample.gdc"
        source.write_bytes(b"GDSC")
        source_code = source.with_suffix(".gd")
        source_code.write_text("extends Node\n" + "# long source line " * 100, encoding="utf-8")

        class StubBackend:
            def inspect(self, mode, path):
                return f"{mode}: {path}"

        original_backend = self.window.backend
        original_runner = self.window.run_background
        original_decompiler = self.window.decompile_single_binary
        original_action = self.window.backend_action
        self.addCleanup(setattr, self.window, "backend", original_backend)
        self.addCleanup(setattr, self.window, "run_background", original_runner)
        self.addCleanup(setattr, self.window, "decompile_single_binary", original_decompiler)
        self.addCleanup(setattr, self.window, "backend_action", original_action)
        self.window.backend = StubBackend()
        self.window.run_background = lambda _name, worker, on_success: on_success(worker())
        self.window.open_path(source_code)
        self.app.processEvents()
        self.assertLess(self.window.minimumWidth(), 1600)

        self.window.open_path(source)
        report = self.window.tabs.currentWidget()
        self.app.processEvents()

        self.window.resize(1400, 900)
        self.app.processEvents()
        self.assertLess(self.window.minimumWidth(), 1600)
        self.assertLess(self.window.minimumHeight(), 713)
        self.assertLessEqual(report.minimumSizeHint().width(), 700)
        self.assertLess(self.window.output_dock.minimumSizeHint().width(), 400)

        previous_width = self.window.explorer_dock.width()
        self.window.resizeDocks(
            [self.window.explorer_dock], [previous_width + 80], Qt.Orientation.Horizontal
        )
        self.app.processEvents()
        self.assertGreater(self.window.explorer_dock.width(), previous_width + 20)

        more = report.findChild(QToolButton, "gdscMoreActions")
        self.assertIsNotNone(more)
        menu_actions = {action.text() for action in more.menu().actions()}
        self.assertTrue({"Compare…", "Audit", "Disassemble", "Constants", "Hex Dump"} <= menu_actions)

        calls = []
        self.window.decompile_single_binary = lambda path: calls.append(("decompile", path))
        self.window.backend_action = lambda mode, path: calls.append((mode, path))
        decompile = next(button for button in report.findChildren(QPushButton) if button.text() == "Decompile to .gd")
        decompile.click()
        self.assertEqual(calls.pop(), ("decompile", source))
        compare = next(action for action in more.menu().actions() if action.text() == "Compare…")
        compare.trigger()
        self.assertEqual(calls.pop(), ("diff", source))

    def test_all_five_panels_are_native_closable_movable_floatable_docks(self):
        self.assertEqual(len(self.docks), 5)
        for dock in self.docks:
            self.assertIsInstance(dock, QDockWidget)
            features = dock.features()
            self.assertTrue(features & QDockWidget.DockWidgetFeature.DockWidgetClosable)
            self.assertTrue(features & QDockWidget.DockWidgetFeature.DockWidgetMovable)
            self.assertTrue(features & QDockWidget.DockWidgetFeature.DockWidgetFloatable)
            self.assertIsNotNone(dock.widget())

    def test_close_and_view_action_reopen_the_same_panel_instance(self):
        dock = self.window.explorer_dock
        original_content = dock.widget()
        dock.close()
        self.app.processEvents()
        self.assertFalse(dock.isVisible())
        self.assertFalse(dock.toggleViewAction().isChecked())
        dock.toggleViewAction().trigger()
        self.app.processEvents()
        self.assertTrue(dock.isVisible())
        self.assertIs(dock.widget(), original_content)

    def test_panel_can_float_into_an_independent_window_and_dock_back(self):
        dock = self.window.ai_dock_widget
        self.window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.app.processEvents()
        self.window.float_panel(dock)
        self.app.processEvents()
        self.assertTrue(dock.isFloating())
        self.assertTrue(dock.isWindow())
        self.assertTrue(dock.isVisible())
        self.window.dock_panel(dock)
        self.app.processEvents()
        self.assertFalse(dock.isFloating())
        self.assertEqual(self.window.dockWidgetArea(dock), Qt.DockWidgetArea.LeftDockWidgetArea)

    def test_view_menu_float_and_dock_back_actions_keep_the_selected_panel(self):
        dock = self.window.explorer_dock
        self.window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.window._float_panel_actions[dock].trigger()
        self.app.processEvents()
        self.assertTrue(dock.isFloating())
        back_action = self.window._dock_back_panel_actions[dock]
        self.assertTrue(back_action.isEnabled())
        back_action.trigger()
        self.app.processEvents()
        self.assertFalse(dock.isFloating())
        self.assertEqual(self.window.dockWidgetArea(dock), Qt.DockWidgetArea.RightDockWidgetArea)

    def test_tree_context_menu_lists_project_files_without_iterator_assumptions(self):
        from unittest.mock import patch

        class Action:
            def __init__(self, text):
                self._text = text

            def text(self):
                return self._text

        class Menu:
            def __init__(self, *_args):
                self.items = []

            def addAction(self, text):
                action = Action(text)
                self.items.append(action)
                return action

            def addSeparator(self):
                pass

            def addMenu(self, text):
                menu = Menu(text)
                self.items.append(Action(text))
                return menu

            def exec(self, *_args):
                return None

        with tempfile.TemporaryDirectory(dir=self._settings_dir.name) as temp:
            root = Path(temp)
            (root / "script.gd").write_text("extends Node\n", encoding="utf-8")
            (root / "script.gdc").write_bytes(b"GDSC")
            old_root = self.window.root
            self.window.root = root
            self.addCleanup(setattr, self.window, "root", old_root)
            menus = []
            with patch.object(self.main_module, "QMenu", side_effect=lambda *args: menus.append(Menu(*args)) or menus[-1]):
                self.window.tree_context_menu(QPoint(0, 0))
            self.assertEqual(len(menus), 1)
            labels = {action.text() for action in menus[0].items}
            self.assertIn("Compile .gd files in this folder…", labels)
            self.assertIn("Decompile .gdc files in this folder…", labels)

    def test_native_dock_can_move_between_left_and_right_areas(self):
        dock = self.window.explorer_dock
        self.window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.app.processEvents()
        self.assertEqual(self.window.dockWidgetArea(dock), Qt.DockWidgetArea.RightDockWidgetArea)
        self.window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self.app.processEvents()
        self.assertEqual(self.window.dockWidgetArea(dock), Qt.DockWidgetArea.LeftDockWidgetArea)

    def test_default_layout_restores_all_panels_and_original_areas(self):
        self.window.float_panel(self.window.output_dock)
        self.window.source_control_dock.hide()
        self.window.restore_default_dock_layout(show_message=False)
        self.app.processEvents()
        self.assertTrue(all(dock.isVisible() for dock in self.docks))
        self.assertFalse(self.window.output_dock.isFloating())
        self.assertEqual(self.window.dockWidgetArea(self.window.explorer_dock), Qt.DockWidgetArea.LeftDockWidgetArea)
        self.assertEqual(self.window.dockWidgetArea(self.window.code_insight_dock), Qt.DockWidgetArea.RightDockWidgetArea)
        self.assertEqual(self.window.dockWidgetArea(self.window.output_dock), Qt.DockWidgetArea.BottomDockWidgetArea)


    def test_custom_titlebar_controls_float_restore_and_close(self):
        dock = self.window.explorer_dock
        titlebar = dock.titleBarWidget()
        self.assertIsInstance(titlebar, self.main_module.DockTitleBar)
        self.assertEqual(titlebar.close_button.text(), "×")
        self.assertTrue(titlebar.float_button.text())

        titlebar.float_button.click()
        self.app.processEvents()
        self.assertTrue(dock.isFloating())
        self.assertEqual(titlebar.float_button.text(), "↙")

        titlebar.float_button.click()
        self.app.processEvents()
        self.assertFalse(dock.isFloating())
        self.assertEqual(titlebar.float_button.text(), "↗")

        titlebar.close_button.click()
        self.app.processEvents()
        self.assertFalse(dock.isVisible())
        dock.toggleViewAction().trigger()
        self.app.processEvents()
        self.assertTrue(dock.isVisible())

    def test_dock_state_round_trip_preserves_layout(self):
        self.window.float_panel(self.window.ai_dock_widget)
        self.app.processEvents()
        state = self.window.saveState(5)
        self.assertTrue(state)
        self.window.dock_panel(self.window.ai_dock_widget)
        self.assertTrue(self.window.restoreState(state, 5))
        self.app.processEvents()
        self.assertTrue(self.window.ai_dock_widget.isFloating())


if __name__ == "__main__":
    unittest.main()
