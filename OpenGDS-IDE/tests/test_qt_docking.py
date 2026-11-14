"""Real PySide6 docking interaction tests for the IDE tool windows.

Run with the IDE environment:
    .venv\\Scripts\\python.exe -m unittest tests.test_qt_docking -v
"""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt, QSettings
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDockWidget
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
