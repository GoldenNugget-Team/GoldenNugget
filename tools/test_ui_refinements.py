"""Offline regressions for confirmation, search, result, and support widgets."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymobiledevice3.services.mobilebackup2 import (
    NP_LOCAL_AUTH_DISMISSED,
    NP_LOCAL_AUTH_PRESENTED,
    Mobilebackup2Service,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QPushButton,
    QWidget,
)

from src.gui.dialogs.confirmation import ConfirmationDialog
from src.gui.dialogs.reset_dialog import ResetDialog
from src.gui.ios.components import IOSSearchField, IOSSummaryDialog, LiquidSwitch
from src.gui.ios.operation_result import OperationResultCard
from src.gui.ios.settings import IOSSettingsPage
from src.gui.ios.support_panel import CommunityLinks, SupportPanel
from src.gui.theme import ColorThemeManager
from src.restore.protective import ProtectiveBackupService


class UIRefinementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_profile_resources_work_without_optional_image_plugins(self):
        from PySide6.QtCore import QCoreApplication, QFile, QIODevice, QResource
        from PySide6.QtGui import QPixmap
        original_paths = QCoreApplication.libraryPaths()
        try:
            QCoreApplication.setLibraryPaths([])
            for name in ('awesomenull', 'windows11aero', 'kik4311', 'LeminLimez'):
                path = f':/credits/{name}.png'
                resource = QResource(path)
                self.assertTrue(resource.isValid(), path)
                self.assertNotEqual(resource.compressionAlgorithm(),
                                    QResource.Compression.ZstdCompression, path)
                file = QFile(path)
                self.assertTrue(file.open(QIODevice.ReadOnly), f'{path}: {file.errorString()}')
                self.assertGreater(len(file.readAll()), 0, path)
                self.assertFalse(QPixmap(path).isNull(), path)
        finally:
            QCoreApplication.setLibraryPaths(original_paths)

    def test_confirmation_actions_and_escape(self):
        for action, expected in (("cancel", QDialog.Rejected), ("confirm", QDialog.Accepted),
                                 ("escape", QDialog.Rejected)):
            dialog = ConfirmationDialog(None, "Download Icon Pack", "Example pack", "Download")
            self.assertEqual(dialog.confirm_btn.height(), 48)
            self.assertFalse(dialog.icon_label.pixmap().isNull())
            if action == "escape":
                QTimer.singleShot(0, lambda: QTest.keyClick(dialog, Qt.Key_Escape))
            else:
                button = dialog.cancel_btn if action == "cancel" else dialog.confirm_btn
                QTimer.singleShot(0, button.click)
            self.assertEqual(dialog.exec(), expected)
            dialog.deleteLater()

    def test_search_icon_survives_theme_refresh_and_resize(self):
        field = IOSSearchField()
        field.show()
        field.setText("example")
        for width in (240, 420, 600):
            field.resize(width, 44)
            self.app.processEvents()
            ColorThemeManager.instance().theme_changed.emit()
            self.assertFalse(field._search_icon.pixmap().isNull())
            self.assertEqual(field._search_icon.y(), (field.height() - 20) // 2)
            self.assertEqual(field.text(), "example")
        field.close()
        field.deleteLater()

    def test_hidden_widgets_refresh_theme_on_next_show(self):
        field = IOSSearchField()
        field._retheme = Mock(wraps=field._retheme)
        ColorThemeManager.instance().theme_changed.emit()
        field._retheme.assert_not_called()
        field.show()
        self.app.processEvents()
        field._retheme.assert_called_once()
        field.close()
        field.deleteLater()

    def test_apply_summary_keeps_details_callback_and_extra_result(self):
        details = Mock()
        dialog = IOSSummaryDialog("Apply Tweaks", ["One setting"], extra_button="Update Cache",
                                  details_callback=details)
        self.assertFalse(dialog._summary_icon.pixmap().isNull())
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        buttons["View changes"].click()
        details.assert_called_once_with(dialog)
        buttons["Update Cache"].click()
        self.assertEqual(dialog.result(), 2)
        dialog.deleteLater()

    def test_reset_selection_preserves_callback(self):
        page = Mock()
        page.getPageName.return_value = "Tweaks"
        restore = Mock()
        with patch("src.gui.dialogs.reset_dialog.get_resettable_pages", return_value=[page]):
            dialog = ResetDialog(Mock(), restore)
        confirm = dialog.buttonBox.button(QDialogButtonBox.Ok)
        self.assertFalse(confirm.isEnabled())
        row = dialog.findChild(QPushButton, "resetSelection")
        row.click()
        self.assertEqual(dialog.selected_pages, [page])
        self.assertTrue(confirm.isEnabled())
        row.click()
        self.assertFalse(confirm.isEnabled())
        row.click()
        confirm.click()
        restore.assert_called_once_with([page])
        dialog.deleteLater()

    def test_result_details_start_collapsed_and_reset_between_operations(self):
        card = OperationResultCard(Mock(), Mock())
        card.show_result(True, "Completed settings")
        self.assertTrue(card.details.isHidden())
        self.assertTrue(card.log_details.isHidden())
        with patch("src.controllers.nugget_logger.get_log_tail", return_value="Example log"):
            card.expand_btn.click()
        self.assertFalse(card.details.isHidden())
        self.assertEqual(card.log_details.toPlainText(), "Example log")
        card.show_result(False, "Stopped")
        self.assertTrue(card.details.isHidden())
        self.assertFalse(card.expand_btn.isChecked())
        card.close()
        card.deleteLater()

    def test_support_links_open_only_when_clicked(self):
        with patch("src.gui.ios.support_panel.QDesktopServices.openUrl") as open_url:
            panel = SupportPanel()
            open_url.assert_not_called()
            panel.discord.click()
            self.assertEqual(open_url.call_args.args[0].toString(), "https://discord.gg/F7ssrHjdgK")
            panel.github.click()
            self.assertEqual(open_url.call_args.args[0].toString(),
                             "https://github.com/GoldenNugget-Team/GoldenNugget")
        panel.deleteLater()

    def test_home_support_panel_reuses_existing_link_cards(self):
        links = CommunityLinks()
        panel = SupportPanel(links=links)
        self.assertIs(panel.discord, links.discord)
        self.assertIs(panel.github, links.github)
        self.assertFalse(panel.isAncestorOf(links))
        panel.deleteLater()
        links.deleteLater()

    def test_setup_dependencies_keep_saved_choices(self):
        preferences = SimpleNamespace(skip_setup=False, supervised=True)
        supervision_card = QWidget()
        page = SimpleNamespace(
            window=SimpleNamespace(device_manager=SimpleNamespace(pref_manager=preferences)),
            supervision_switch=LiquidSwitch(True, supervision_card), organization_card=QWidget())
        for skip_setup, supervised in ((False, True), (True, False), (True, True)):
            preferences.skip_setup = skip_setup
            preferences.supervised = supervised
            IOSSettingsPage._sync_setting_dependencies(page)
            self.assertEqual(page.supervision_switch.isEnabled(), skip_setup)
            self.assertEqual(page.organization_card.isEnabled(), skip_setup and supervised)
            self.assertEqual(preferences.supervised, supervised)
        page.supervision_switch.parentWidget().deleteLater()
        page.organization_card.deleteLater()

    def test_authentication_status_uses_only_explicit_device_notifications(self):
        service = ProtectiveBackupService.__new__(ProtectiveBackupService)
        service.authentication_callback = Mock()
        with patch.object(Mobilebackup2Service, "_log_backup_notification"):
            service._log_backup_notification({"Name": "unrelated"})
            service.authentication_callback.assert_not_called()
            service._log_backup_notification({"Name": NP_LOCAL_AUTH_PRESENTED})
            service.authentication_callback.assert_called_with(True)
            service._log_backup_notification({"Name": NP_LOCAL_AUTH_DISMISSED})
            service.authentication_callback.assert_called_with(False)


if __name__ == "__main__":
    unittest.main()
