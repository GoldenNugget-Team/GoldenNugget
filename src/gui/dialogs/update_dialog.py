"""Update download dialog opened from the version notice."""
from PySide6.QtCore import QCoreApplication, Qt, QUrl
from PySide6.QtGui import QDesktopServices

from src.gui.dialogs.confirmation import ConfirmationDialog


class UpdateDialog(ConfirmationDialog):
    def __init__(self, parent=None, *, required=False, rule=None):
        self._required = required
        tr = lambda text: QCoreApplication.translate("UpdateDialog", text)
        from src.controllers.web_request_handler import (
            last_fetched_version,
            update_download_url,
        )
        from src.version import App_Version
        self._download_url = update_download_url()
        message = tr('You have GoldenNugget {0}.').format(App_Version)
        version = (rule or {}).get('version') or last_fetched_version
        if version:
            message += '\n' + tr('Version {0} is available.').format(version)
        if required:
            message += '\n\n' + tr('You must update GoldenNugget before continuing. Install the update, then restart the app.')
            reason = (rule or {}).get('reason')
            if reason:
                message += '\n\n' + str(reason)
        instructions = (tr('Download and extract the source archive, then follow its installation instructions.')
                        if '/archive/' in self._download_url else
                        tr('Download the update, then open the downloaded package to install it.'))
        message += '\n\n' + instructions
        super().__init__(parent, tr('Update GoldenNugget'), message, tr('Download update'),
                         icon=':/icon/arrow-clockwise.svg')
        self.cancel_btn.setText(tr('Later'))
        if required:
            self.setWindowModality(Qt.ApplicationModal)
            self.setWindowFlag(Qt.WindowCloseButtonHint, False)
            self.cancel_btn.hide()
            self.cancel_btn.setDefault(False)
            self.confirm_btn.setDefault(True)
            self.confirm_btn.setFocus()
        self.resize(560, self.height())

    def accept(self):
        # The release fetch may finish after a cached HotLoad rule opens us.
        from src.controllers.web_request_handler import update_download_url
        self._download_url = update_download_url()
        if QDesktopServices.openUrl(QUrl(self._download_url)):
            if not self._required:
                super().accept()

    def done(self, result):
        if not self._required:
            super().done(result)

    def reject(self):
        if not self._required:
            super().reject()

    def closeEvent(self, event):
        if self._required:
            event.ignore()
        else:
            super().closeEvent(event)
