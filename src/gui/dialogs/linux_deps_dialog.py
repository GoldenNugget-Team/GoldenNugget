"""Ask to install usbmuxd / libimobiledevice on Linux, then do it.

The password is collected by the system (polkit's own dialog via ``pkexec``),
so GoldenNugget never sees it. Only when polkit is missing does this fall back
to asking for the password itself and piping it to ``sudo -S``; it is held in
memory just long enough to start the process and is never logged.
"""
import logging

from PySide6.QtCore import QCoreApplication, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
)

from src.devicemanagement import linux_deps

log = logging.getLogger("GoldenNugget.linux_deps")
DISMISSED_KEY = "linux_deps_prompt_dismissed"


class _InstallThread(QThread):
    line = Signal(str)
    finished_with = Signal(object)

    def __init__(self, status, password, parent=None):
        super().__init__(parent)
        self._status = status
        self._password = password

    def run(self):
        try:
            result = linux_deps.run_install(
                self._status, password=self._password, on_output=self.line.emit)
        except Exception as error:  # surface in the dialog instead of crashing the thread
            log.exception("dependency install failed to start")
            result = linux_deps.InstallResult(ok=False, output=str(error))
        finally:
            self._password = None
        self.finished_with.emit(result)


class _ProgressDialog(QDialog):
    """Busy bar plus the package manager's output; closable once it finishes."""

    def __init__(self, status, password, parent=None):
        super().__init__(parent)
        self.result_value = None
        self.setWindowTitle(QCoreApplication.translate("LinuxDeps", "Installing dependencies"))
        self.setModal(True)
        self.resize(560, 360)
        layout = QVBoxLayout(self)
        self._label = QLabel(QCoreApplication.translate("LinuxDeps", "Installing {0}…").format(linux_deps.package_summary(status)))
        self._label.setWordWrap(True)
        layout.addWidget(self._label)
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        layout.addWidget(self._bar)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        layout.addWidget(self._log, 1)
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._buttons.rejected.connect(self.reject)
        self._buttons.setEnabled(False)
        layout.addWidget(self._buttons)
        self._thread = _InstallThread(status, password, self)
        self._thread.line.connect(self._log.appendPlainText)
        self._thread.finished_with.connect(self._done)
        self._thread.start()

    def _done(self, result):
        self.result_value = result
        self._bar.setRange(0, 1)
        self._bar.setValue(1 if result.ok else 0)
        self._buttons.setEnabled(True)
        self.accept()

    def reject(self):
        if self._thread.isRunning():
            return  # never close mid-install: the package manager keeps running
        super().reject()

    def done(self, code):
        if self._thread.isRunning():
            self._thread.wait()
        super().done(code)


def _ask_password(parent) -> str | None:
    text, ok = QInputDialog.getText(
        parent, QCoreApplication.translate("LinuxDeps", "Administrator password"),
        QCoreApplication.translate("LinuxDeps", "polkit is not available, so GoldenNugget has to ask for your password. "
            "It is passed to sudo once and not stored or logged.\n\nPassword:"),
        QLineEdit.EchoMode.Password)
    return text if ok and text else None


def prompt_and_install(window, from_startup: bool = False) -> bool:
    """Offer to fix the USB stack. Returns True when something was installed."""
    status = linux_deps.check()
    if status.ok:
        return False
    settings = getattr(window, "settings", None)

    if not status.can_fix:
        QMessageBox.information(
            window, QCoreApplication.translate("LinuxDeps", "Install USB dependencies"),
            QCoreApplication.translate("LinuxDeps", "GoldenNugget could not recognise this Linux distribution. Install usbmuxd "
                "and libimobiledevice with your package manager, make sure usbmuxd is running, "
                "then check the connection again."))
        return False

    box = QMessageBox(window)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(QCoreApplication.translate("LinuxDeps", "Install USB dependencies"))
    if status.missing_packages:
        box.setText(QCoreApplication.translate("LinuxDeps", 
            "GoldenNugget needs {0} to talk to an iPhone over USB, and they are not installed. "
            "Install them now? The system will ask for your administrator password.").format(
                linux_deps.package_summary(status)))
    else:
        box.setText(QCoreApplication.translate("LinuxDeps", 
            "The usbmuxd service is not running, so no iPhone can be detected. Start it now? "
            "The system will ask for your administrator password."))
    install = box.addButton(QCoreApplication.translate("LinuxDeps", "Install"), QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QCoreApplication.translate("LinuxDeps", "Not now"), QMessageBox.ButtonRole.RejectRole)
    remember = None
    if from_startup:
        remember = QCheckBox(QCoreApplication.translate("LinuxDeps", "Don't ask again"))
        box.setCheckBox(remember)
    box.exec()
    if remember is not None and remember.isChecked() and settings is not None:
        settings.setValue(DISMISSED_KEY, True)
    if box.clickedButton() is not install:
        return False

    for _ in range(3):
        password = None
        _argv, needs_password = linux_deps.privileged_command("true")
        if needs_password:
            password = _ask_password(window)
            if password is None:
                return False
        progress = _ProgressDialog(status, password, window)
        password = None
        progress.exec()
        result = progress.result_value
        if result is None:
            return False
        if result.ok:
            QMessageBox.information(
                window, QCoreApplication.translate("LinuxDeps", "Install USB dependencies"),
                QCoreApplication.translate("LinuxDeps", "Done. GoldenNugget will look for your device again. If it does not appear, "
                    "reconnect the cable."))
            try:
                window.refresh_devices()
            except Exception:
                log.exception("refresh after install failed")
            return True
        if result.cancelled:
            return False
        if result.wrong_password:
            QMessageBox.warning(window, QCoreApplication.translate("LinuxDeps", "Install USB dependencies"), QCoreApplication.translate("LinuxDeps", "Wrong password. Try again."))
            continue
        failure = QMessageBox(window)
        failure.setIcon(QMessageBox.Icon.Warning)
        failure.setWindowTitle(QCoreApplication.translate("LinuxDeps", "Install USB dependencies"))
        failure.setText(QCoreApplication.translate("LinuxDeps", "The installation failed. Install usbmuxd and libimobiledevice manually, "
                            "or open the details to see what the package manager said."))
        failure.setDetailedText(result.output or "")
        failure.exec()
        return False
    return False


def should_prompt_on_startup(window) -> bool:
    """Only prompt when packages are missing (a stopped daemon is normal until a device is plugged in)."""
    if not linux_deps.is_linux():
        return False
    settings = getattr(window, "settings", None)
    if settings is not None and settings.value(DISMISSED_KEY, False, type=bool):
        return False
    return bool(linux_deps.check().missing_packages)
