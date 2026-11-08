"""Offline integration regressions for the awesomeUI migration."""
import ast
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from settings_sandbox import SettingsSandbox

from awesomeui import Sidebar
from src.gui.theme import ColorThemeManager
from src.gui.widgets import NavigationSidebar

APP = QApplication.instance() or QApplication([])


class AwesomeUIIntegration(unittest.TestCase):
    def test_library_is_standalone_and_manifest_matches(self):
        # Vendored-hash pinning (awesomeui/upstream.json) was superseded by the
        # gitlink on the submodule; what still matters is that the library is
        # standalone and never imports the host's src.* modules — except the
        # deliberate guarded host imports (try/except ImportError fallbacks).
        for path in (ROOT / 'awesomeui').rglob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            guarded = set()
            # Any host import is only allowed inside a guarded fallback block
            # (ImportError or broad Exception — e.g. the optional resources_rc).
            for node in ast.walk(tree):
                if isinstance(node, ast.Try):
                    guarded.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('src.'):
                    self.assertTrue(node.lineno in guarded, path.name)
                elif isinstance(node, ast.Import) and any(
                    n.name.startswith('src.') for n in node.names
                ):
                    self.assertTrue(node.lineno in guarded, path.name)

    def test_main_window_navigation_gating_and_live_theme(self):
        from src.devicemanagement.device_manager import DeviceManager
        from src.gui.main_window import MainWindow
        from src.gui.translator import Translator
        with tempfile.TemporaryDirectory() as directory, \
                SettingsSandbox(Path(directory)) as make_settings:
            settings = make_settings('settings')
            previous = ColorThemeManager._inst
            ColorThemeManager._inst = ColorThemeManager()
            manager = DeviceManager()
            manager.pref_manager.settings = settings
            try:
                with patch.object(MainWindow, 'refresh_devices'), \
                     patch.object(MainWindow, '_load_last_preset'), \
                     patch.object(MainWindow, '_register_tweak_autosave'), \
                     patch('src.gui.main_window.DeviceMonitorThread.start'), \
                     patch('PySide6.QtCore.QStandardPaths.writableLocation', return_value=directory):
                    window = MainWindow(manager, Translator(APP, settings))
                try:
                    self.assertIsInstance(window.ui.sidebar, Sidebar)
                    window.show()
                    APP.processEvents()
                    self.assertTrue(window.ui.sidebar.isHidden())
                    window.set_ios_page(4, animate=False)
                    self.assertEqual(window.ios_pages.currentIndex(), 4)
                    for index, name in ((0, 'homePageBtn'), (4, 'settingsPageBtn'),
                                        (12, 'presetsPageBtn'), (6, 'applyPageBtn'),
                                        (14, 'templatesPageBtn'), (2, 'posterboardPageBtn')):
                        getattr(window.ui, name).click()
                        APP.processEvents()
                        self.assertEqual(window.ios_pages.currentIndex(), index)
                        self.assertEqual(window.ui.sidebar.current_item_id(), name)
                        self.assertIs(getattr(window.ui, name), window.ui.sidebar.item(name))
                    self.assertIs(window.ios_pages.widget(14), window.ios_templates)
                    self.assertEqual(window.ios_posterboard.tab_stack.count(), 3)
                    window.ios_posterboard.video_tab_btn.click()
                    self.assertIs(window.ios_posterboard.tab_stack.currentWidget(),
                                  window.ios_posterboard.video_page)
                    self.assertFalse(hasattr(window.ios_posterboard, 'templates_tab_btn'))
                    # The feature grid is 6 tiles wide (7th entry became the
                    # compact GoldenNugget Mobile row + Catalog row).
                    self.assertEqual(len(window.ios_home._tiles), 6)
                    # Templates has no home card any more; PosterBoard's does.
                    for card, index in ((window.ios_home.posterboard_card, 2),):
                        card.mousePressEvent(None)
                        APP.processEvents()
                        self.assertEqual(window.ios_pages.currentIndex(), index)
                    self.assertEqual(window.ios_nav.title_lbl.text(), 'PosterBoard')
                    import_action = window.ios_nav._right_btn
                    with patch.object(window.ios_templates, 'show_add_templates_dialog') as import_templates:
                        window._nav_right_actions[14] = ('+ Import Templates', import_templates)
                        window._update_shared_nav(14)
                        self.assertTrue(import_action.isHidden())
                        window.ios_nav._right_btn.click()
                        import_templates.assert_called_once_with()
                    window._nav_right_actions[14] = ('+ Import Templates',
                                                     window.ios_templates.show_add_templates_dialog)
                    with patch('src.gui.main_window_mixins._hidden_feature_names',
                               return_value={'PosterBoard', 'Daemons'}):
                        window._apply_hidden_feature_gating()
                    self.assertTrue(window.ui.posterboardPageBtn.isHidden())
                    self.assertTrue(window.ui.daemonsPageBtn.isHidden())
                    self.assertFalse(window.ui.templatesPageBtn.isHidden())
                    self.assertTrue(window.ios_home.posterboard_card.isHidden())
                    with patch('src.gui.main_window_mixins._hidden_feature_names',
                               return_value={'Templates'}):
                        window._apply_hidden_feature_gating()
                    self.assertTrue(window.ui.templatesPageBtn.isHidden())
                    # Hidden sidebars must catch up when they become visible.
                    ColorThemeManager.instance().set_accent('purple')
                    window.ui.sidebar.show()
                    APP.processEvents()
                    self.assertEqual(window.ui.sidebar.theme().active_indicator,
                                     ColorThemeManager.instance().accent_hex())
                    self.assertIn(ColorThemeManager.instance().colors.bg_secondary,
                                  window.ui.sidebar.styleSheet())
                    self.assertEqual(len(window.ui.sidebar._items), len(NavigationSidebar.ITEM_NAMES))
                    window.ui.sidebar.hide()
                    APP.processEvents()
                    # Construction already saved ui/theme. The first-run
                    # interface picker is gone with the sidebar mode: the
                    # prompt is consumed without asking anything.
                    settings.setValue('home_widget', 'presets')
                    settings.setValue('backup_prompt_done', True)
                    settings.remove('ui/interface_choice_done')
                    with patch.object(sys, 'argv', ['GoldenNugget', '--test-mode']):
                        window.run_first_launch_prompts()
                    self.assertTrue(settings.value('ui/interface_choice_done', False, type=bool))
                    self.assertTrue(window.ui.sidebar.isHidden())
                    self.assertFalse(window.ios_home.apply_btn.isHidden())
                    if os.environ.get('GOLDENNUGGET_UI_SCREENSHOT'):
                        path = Path(os.environ['GOLDENNUGGET_UI_SCREENSHOT'])
                        with patch('src.gui.main_window_mixins._hidden_feature_names', return_value=set()):
                            window._apply_hidden_feature_gating()
                        window.resize(1200, 850)
                        for index, suffix in ((0, ''), (14, '-templates'), (2, '-posterboard')):
                            window.set_ios_page(index, animate=False)
                            APP.processEvents()
                            window.grab().save(str(path.with_stem(path.stem + suffix)))
                finally:
                    window.close()
                    window.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            finally:
                ColorThemeManager._inst = previous


if __name__ == '__main__':
    unittest.main()
