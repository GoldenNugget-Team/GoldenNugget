"""GoldenNugget Mobile helper — Apple ID sideload, install and pairing delivery.

The dialog drives the steps the mobile app needs from a desktop host (the
device is already paired with GoldenNugget, which is exactly the record
``com.awesomenull.goldennugget``'s minimuxer wants):

  1. **Sign in with Apple ID && Sideload** — the recommended path. Behind it
     runs the ``gn-sideload`` engine (``tools/sideload-engine`` in this repo,
     built on the Rust crate `isideload` from nab138/iloader, MIT): GrandSlam
     Apple-ID login (2FA, team and certificate choices are relayed through
     dialogs; the password lives in memory only and is sent to Apple and
     nobody else), the free-provisioning Developer Services dance (device
     registration, certificate, profile), re-signing of the freshly
     downloaded ``GoldenNuggetMobile.ipa`` and the actual install. After a
     successful install the pairing file is pushed automatically.
  2. **Pairing file** — mailed into the app's
     ``Documents/pairingfile.mobiledevicepairing`` over house_arrest, or saved
     to disk for a manual AirDrop.

Direct InstallationProxy installs (``Download && Install``, ``Install from
.ipa``) remain for **already-signed** packages; without an Apple ID session
they are the only option, and a dev-signed install on iOS 16+ still needs
Developer Mode enabled on the device.

Device I/O rides background QThreads (one at a time); the IPA download and the
engine subprocess ride Qt event-loop objects (QNetworkAccessManager /
QProcess), with a line protocol on the engine's stdout (see the engine's
doc comment). The mobile app reads the pairing file **at launch** — send it
while the app is closed, then reopen it.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt, QProcess, QThread, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QInputDialog, QMessageBox, QProgressDialog, QGridLayout,
)

from src.devicemanagement import mobile_helper as mh
from src.exceptions.nugget_exception import NuggetException
from src.gui.dialogs.confirmation import ask_confirmation
from src.gui.theme import ColorThemeManager, t


class _MobileHelperThread(QThread):
    """One device action per thread: ``install``, ``send`` or ``save``.

    The pattern lives on from FetchAppsThread: a fresh asyncio loop per run,
    all lockdown work through ``lockdown_session``, signals back to the dialog.
    """

    progress = Signal(float)    # 0.0 – 100.0, install percentage
    done = Signal(object)       # an info dict describing the outcome
    failed = Signal(str)

    def __init__(self, udid: str, action: str, payload: dict, parent=None):
        super().__init__(parent)
        self.udid = udid
        self.action = action
        self.payload = payload

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(self._run())
            self.done.emit(result)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _run(self) -> dict:
        if self.action == "install":
            ipa_path = self.payload["ipa_path"]
            await mh.install_ipa(
                self.udid, ipa_path, progress=lambda p, *_: self.progress.emit(float(p)))
            return {"action": "install", "ipa": os.path.basename(ipa_path)}

        if self.action == "send":
            xml = mh.pairing_record_xml(await mh.read_pairing_record(self.udid))
            try:
                installed = await mh.is_mobile_app_installed(self.udid)
                if installed is None:
                    return {"action": "send", "sent": False, "xml": xml}
                await mh.send_pairing_to_app(self.udid, xml, bundle_id=installed["bundle_id"])
            except NuggetException as e:
                if "not installed" in str(e).lower():
                    return {"action": "send", "sent": False, "xml": xml}
                raise
            return {"action": "send", "sent": True, "xml": xml,
                    "app": installed["display_name"], "version": installed["version"]}

        if self.action == "save":
            await mh.export_pairing_file(self.udid, self.payload["dest_path"])
            return {"action": "save", "path": self.payload["dest_path"]}

        raise NuggetException(f"Unknown GoldenNugget Mobile action: {self.action}")


class _AppleLoginDialog(QDialog):
    """Apple ID + password entry. Nothing is written to disk here."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(QCoreApplication.translate("Nugget", "Sign in with Apple ID"))
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        info = QLabel(QCoreApplication.translate(
            "Nugget",
            "Your Apple ID and password (or a 2FA code, asked separately) go "
            "to Apple and nowhere else. They are NOT saved — enter them again "
            "next time. Consider using a secondary Apple ID; install limits: "
            "3 active apps, profiles expire in 7 days."), self)
        info.setWordWrap(True)
        layout.addWidget(info)

        self.username_edit = QLineEdit(self)
        self.username_edit.setPlaceholderText(QCoreApplication.translate(
            "Nugget", "Apple ID (email)"))
        layout.addWidget(self.username_edit)

        self.password_edit = QLineEdit(self)
        self.password_edit.setPlaceholderText(QCoreApplication.translate(
            "Nugget", "Password"))
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.password_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._retheme()
        self.username_edit.setFocus()

    def credentials(self) -> tuple[str, str] | None:
        return self.username_edit.text().strip(), self.password_edit.text()

    def _retheme(self):
        self.setStyleSheet(t("mobile_helper_dialog"))


class MobileHelperDialog(QDialog):
    """Sideloading (Apple ID via gn-sideload) + pairing delivery."""

    _PROGRESS_RE = re.compile(r"PROGRESS (\d{1,3})")
    _STAGE_RE = re.compile(r"STAGE (\w+)")

    def __init__(self, window, parent=None):
        super().__init__(parent)
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self.window = window
        self.setWindowTitle(QCoreApplication.translate("Nugget", "GoldenNugget Mobile Helper"))
        self.setModal(True)
        self.resize(560, 480)

        self._thread = None
        self._nam = QNetworkAccessManager(self)
        self._release_reply = None
        self._ipa_reply = None
        self._ipa_file = None
        self._ipa_response_size = 0
        self._pending_ipa_path = None
        self._download_progress = None
        self._install_progress = None
        self._download_intent = "direct"    # what happens when the download lands
        self._eng_proc = None
        self._eng_mode = None               # install | build
        self._eng_out = ""
        self._eng_buf = ""                  # not-yet-consumed protocol bytes
        self._eng_password = None           # in memory only, never persisted
        self._eng_prompt_active = False     # a modal prompt is open over the stream
        self._eng_result_error = None       # text from the last RESULT ERROR line

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(QCoreApplication.translate("Nugget", "GoldenNugget Mobile Helper"), self)
        title.setObjectName("mhTitle")
        layout.addWidget(title)

        intro = QLabel(QCoreApplication.translate(
            "Nugget",
            "Install GoldenNugget Mobile on the connected iPhone and export "
            "the pairing file into it. Connect and unlock the iPhone first — "
            "the first run may show the Trust dialog on the phone."), self)
        intro.setObjectName("mhIntro")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # --- App ---
        layout.addWidget(QLabel(QCoreApplication.translate(
            "Nugget", "1. App — sideload"), self))
        self.sideload_btn = QPushButton(
            QCoreApplication.translate("Nugget", "Sign in with Apple ID && Sideload"), self)
        self.sideload_btn.setObjectName("mhPrimary")
        self.sideload_btn.clicked.connect(self._start_sideload)
        layout.addWidget(self.sideload_btn)

        app_grid = QGridLayout()
        app_grid.setSpacing(8)
        self.install_download_btn = QPushButton(
            QCoreApplication.translate("Nugget", "Download && Install (no signing)"), self)
        self.install_download_btn.setObjectName("mhSecondary")
        self.install_download_btn.clicked.connect(self._download_direct)
        app_grid.addWidget(self.install_download_btn, 0, 0)
        self.install_ipa_btn = QPushButton(
            QCoreApplication.translate("Nugget", "Install from .ipa File…"), self)
        self.install_ipa_btn.setObjectName("mhSecondary")
        self.install_ipa_btn.clicked.connect(self._install_from_file)
        app_grid.addWidget(self.install_ipa_btn, 0, 1)
        layout.addLayout(app_grid)

        # engine availability row (hidden while the engine is found)
        self.engine_hint = QLabel("", self)
        self.engine_hint.setObjectName("mhHint")
        self.engine_hint.setWordWrap(True)
        self.engine_hint.hide()
        layout.addWidget(self.engine_hint)
        engine_row = QGridLayout()
        engine_row.setSpacing(8)
        self.build_engine_btn = QPushButton(
            QCoreApplication.translate("Nugget", "Build Engine (cargo)"), self)
        self.build_engine_btn.setObjectName("mhSecondary")
        self.build_engine_btn.clicked.connect(self._build_engine)
        engine_row.addWidget(self.build_engine_btn, 0, 0)
        self.locate_engine_btn = QPushButton(
            QCoreApplication.translate("Nugget", "Locate engine binary…"), self)
        self.locate_engine_btn.setObjectName("mhSecondary")
        self.locate_engine_btn.clicked.connect(self._locate_engine)
        engine_row.addWidget(self.locate_engine_btn, 0, 1)
        self._engine_row = engine_row
        layout.addLayout(engine_row)

        # --- Pairing file ---
        layout.addWidget(QLabel(QCoreApplication.translate("Nugget", "2. Pairing file"), self))
        pairing_grid = QGridLayout()
        pairing_grid.setSpacing(8)
        self.send_pairing_btn = QPushButton(
            QCoreApplication.translate("Nugget", "Export && Send to the App"), self)
        self.send_pairing_btn.setObjectName("mhPrimary")
        self.send_pairing_btn.clicked.connect(self._send_pairing)
        pairing_grid.addWidget(self.send_pairing_btn, 0, 0)
        self.save_pairing_btn = QPushButton(
            QCoreApplication.translate("Nugget", "Save Pairing File to Disk…"), self)
        self.save_pairing_btn.setObjectName("mhSecondary")
        self.save_pairing_btn.clicked.connect(self._save_pairing)
        pairing_grid.addWidget(self.save_pairing_btn, 0, 1)
        layout.addLayout(pairing_grid)

        hint = QLabel(QCoreApplication.translate(
            "Nugget",
            "GoldenNugget Mobile reads the pairing file at launch — send it "
            "while the app is closed, then reopen it."), self)
        hint.setObjectName("mhHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.status_lbl = QLabel("", self)
        self.status_lbl.setObjectName("mhStatus")
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl, 1)

        close_btn = QPushButton(QCoreApplication.translate("Nugget", "Close"), self)
        close_btn.setObjectName("mhClose")
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)

        self._retheme()
        self._refresh_engine_state(report=False)

    # --- helpers ---

    def _report(self, text: str):
        self.status_lbl.setText(text)

    def _udid(self) -> str | None:
        try:
            return self.window.device_manager.get_current_device_udid()
        except Exception:
            return None

    def _require_device(self) -> str | None:
        udid = self._udid()
        if not udid:
            self._report(QCoreApplication.translate(
                "Nugget", "No iPhone connected. Connect and unlock the device, "
                "then try again."))
            return None
        return udid

    def _set_busy(self, busy: bool):
        for btn in (self.install_download_btn, self.install_ipa_btn,
                    self.send_pairing_btn, self.save_pairing_btn,
                    self.sideload_btn, self.locate_engine_btn,
                    self.build_engine_btn):
            btn.setEnabled(not busy)

    def _start_thread(self, action: str, payload: dict):
        udid = self._require_device()
        if udid is None:
            return
        if self._thread is not None and self._thread.isRunning():
            return
        self._thread = _MobileHelperThread(udid, action, payload, parent=QCoreApplication.instance())
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.progress.connect(self._on_install_progress)
        self._thread.done.connect(self._on_thread_done)
        self._thread.failed.connect(self._on_thread_failed)
        self._set_busy(True)
        self._thread.start()

    def _on_thread_finished(self):
        self._thread = None
        if self._eng_proc is None:
            # an engine run may be underway; only release the UI here then
            self._set_busy(False)
        self._install_progress = self._dismiss(self._install_progress)
        if self._pending_ipa_path is not None:
            # The direct-install pass has read its bytes; the temp IPA can go.
            self._cleanup_download(self._pending_ipa_path)
            self._pending_ipa_path = None

    # --- engine availability ---

    def _engine_override(self) -> str | None:
        try:
            return self.window.settings.value("mobile_helper/engine_path", "", type=str) or None
        except Exception:
            return None

    def _refresh_engine_state(self, report: bool = True):
        path = mh.find_engine(self._engine_override())
        self._engine_path = path
        found = path is not None
        self.engine_hint.setVisible(not found)
        self.build_engine_btn.setVisible(not found)
        self.locate_engine_btn.setVisible(not found)
        if found and report:
            self._report(QCoreApplication.translate(
                "Nugget", "Sideload engine ready: {0}").format(path))
        if not found:
            self.engine_hint.setText(QCoreApplication.translate(
                "Nugget",
                "The gn-sideload signing engine was not found. Build it from "
                "this repository with cargo (Rust), or locate the binary "
                "manually. Signing an unsigned IPA requires it."))
        return found

    def _ensure_engine(self) -> bool:
        found = self._refresh_engine_state()
        if not found:
            self._report(QCoreApplication.translate(
                "Nugget",
                "Build the engine first (see below), then tap Sign in again."))
        return found

    def _engine_repo_dir(self) -> Path:
        return Path(mh.__file__).resolve().parents[2] / "tools" / "sideload-engine"

    def _locate_engine(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            QCoreApplication.translate("Nugget", "Choose the gn-sideload binary"),
            os.path.expanduser("~"))
        if not path:
            return
        # The override is a *path*, not the tool's identity — verify it is the
        # engine (a --version probe exits 0 fast) before saving the setting.
        probe = QProcess(self)
        probe.setProgram(path)
        probe.setArguments(["--version"])
        probe.finished.connect(lambda code, _s: self._on_engine_probe(code))
        self._engine_probe_path = path
        probe.start()

    def _on_engine_probe(self, code: int):
        path = getattr(self, "_engine_probe_path", None)
        if code == 0 and path:
            try:
                self.window.settings.setValue("mobile_helper/engine_path", path)
                self.window.settings.sync()
            except Exception:
                pass
            self._refresh_engine_state()
        else:
            self._report(QCoreApplication.translate(
                "Nugget", "{0} does not look like the gn-sideload engine.").format(path or "?"))

    def _build_engine(self):
        cargo = shutil.which("cargo")
        if not cargo:
            self._report(QCoreApplication.translate(
                "Nugget",
                "cargo (the Rust toolchain) was not found — install Rust "
                "from rustup.rs, then try again.")) 
            return
        confirmed = ask_confirmation(
            self,
            QCoreApplication.translate("Nugget", "Build the sideload engine?"),
            QCoreApplication.translate(
                "Nugget",
                "cargo will build gn-sideload (tools/sideload-engine, MIT "
                "license, based on the isideload crate). The first build "
                "downloads many dependencies and can take a while. Continue?"),
            confirm_text=QCoreApplication.translate("Nugget", "Build"))
        if not confirmed:
            return
        self._set_busy(True)
        self._report(QCoreApplication.translate(
            "Nugget", "Building the engine with cargo — this can take a while…"))
        self._install_progress = self._make_busy_dialog(
            QCoreApplication.translate("Nugget", "Building gn-sideload…"),
            QCoreApplication.translate("Nugget", "Cargo"))
        self._cargo = cargo
        self._start_engine_process(
            cargo, ["build", "--release"], mode="build")

    # --- engine subprocess plumbing ---

    def _start_engine_process(self, program: str, args: list[str], mode: str,
                              password: str | None = None) -> None:
        if self._eng_proc is not None and self._eng_proc.state() != QProcess.ProcessState.NotRunning:
            return
        self._eng_mode = mode
        self._eng_out = ""
        self._eng_buf = ""
        self._eng_password = password
        self._eng_result_error = None
        proc = QProcess(self)
        proc.setProgram(program)
        proc.setArguments(args)
        if mode == "build":
            proc.setWorkingDirectory(str(self._engine_repo_dir()))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(self._drain_engine)
        proc.finished.connect(self._on_engine_finished)
        self._eng_proc = proc
        self._set_busy(True)
        proc.start(program, args)

    def _drain_engine(self):
        if self._eng_proc is None:
            return
        data = bytes(self._eng_proc.readAllStandardOutput())
        text = data.decode("utf-8", "replace")
        self._eng_out += text
        self._eng_buf += text
        if self._eng_prompt_active:
            # queued output will be scanned when the modal prompt closes
            return
        self._pump_engine()

    def _pump_engine(self):
        """Consume complete lines from the unconsumed buffer.

        Line-indexed bookkeeping is a trap here: a trailing ``""`` between the
        chunk we already read and new output shifts every subsequent line, so
        the pump keeps ``_eng_buf`` as raw, unsplit bytes and only breaks
        complete lines off the front.
        """
        buf = self._eng_buf
        while True:
            nl = buf.find("\n")
            if nl == -1:
                break
            line = buf[:nl].rstrip("\r")
            buf = buf[nl + 1:]
            if not line:
                continue
            if line.startswith("PROMPT "):
                if self._eng_proc is None:
                    buf = ""
                    break                       # process died mid-prompt
                kind, _, payload = line[len("PROMPT "):].partition(" ")
                self._eng_prompt_active = True
                try:
                    answer = self._resolve_prompt(kind, payload)
                    if answer is None:           # user cancelled → kill
                        self._eng_proc.kill()
                        buf = ""
                        self._report(QCoreApplication.translate(
                            "Nugget", "The step was cancelled."))
                        break
                    self._eng_proc.write((answer + "\n").encode("utf-8"))
                finally:
                    self._eng_prompt_active = False
                continue
            if line.startswith("PROGRESS ") and self._eng_mode == "install":
                match = self._PROGRESS_RE.match(line)
                if match:
                    pct = min(100, int(match.group(1)))
                    dialog = self._install_progress
                    if dialog is not None:
                        dialog.setRange(0, 100)
                        dialog.setValue(pct)
                    self._report(QCoreApplication.translate(
                        "Nugget", "Sideload — {0}%").format(pct))
            elif line.startswith("STAGE "):
                match = self._STAGE_RE.match(line)
                if match:
                    stages = {
                        "login": QCoreApplication.translate("Nugget", "Signing in with Apple ID…"),
                        "sign": QCoreApplication.translate("Nugget", "Signing the app…"),
                        "install": QCoreApplication.translate("Nugget", "Installing on the iPhone…"),
                    }
                    self._report(stages.get(
                        match.group(1),
                        QCoreApplication.translate("Nugget", "Engine stage: {0}").format(
                            match.group(1))))
                    if match.group(1) == "install" and self._install_progress is not None:
                        self._install_progress.setLabelText(QCoreApplication.translate(
                            "Nugget", "Installing on the iPhone — keep it awake"))
            elif line.startswith("RESULT ERROR"):
                self._eng_result_error = line[len("RESULT ERROR"):].strip()
        self._eng_buf = buf

    def _resolve_prompt(self, kind: str, payload: str) -> str | None:
        """Turn an engine prompt into the stdin line the user picked."""
        if kind == "PASSWORD":
            # supplied up front; nothing is echoed anywhere
            return self._eng_password or ""
        if kind == "2FA":
            return self._ask_2fa(payload)
        if kind == "TEAM":
            return self._ask_team(payload)
        if kind == "CERTS":
            return self._ask_certs(payload)
        return ""

    def _ask_2fa(self, payload: str) -> str | None:
        hint = QCoreApplication.translate(
            "Nugget",
            "Enter the verification code Apple sent to your trusted devices. "
            "Type 'd' to request the code, 'r' to resend it, or 'p<id>' to "
            "have it sent to a listed phone number. 'q' cancels.")
        try:
            params = json.loads(payload or "{}")
        except (ValueError, TypeError):
            params = {}
        if params.get("unknown"):
            hint = QCoreApplication.translate(
                "Nugget",
                "The previous 2FA attempt failed — try another method. "
                "Type 'd' to have the code sent to your devices.")
        numbers = params.get("numbers") or []
        if numbers:
            listing = "\n".join(
                QCoreApplication.translate("Nugget", "p{0}: SMS to {1}").format(
                    n.get("id", "?"), n.get("number_with_dial_code", "?"))
                for n in numbers)
            hint = hint + "\n" + listing
        text, ok = QInputDialog.getText(
            self,
            QCoreApplication.translate("Nugget", "Two-factor authentication"),
            hint,
            QLineEdit.EchoMode.Normal)
        if not ok:
            return "q"
        return text.strip()

    def _ask_team(self, payload: str) -> str | None:
        try:
            teams = json.loads(payload or "{}").get("teams", [])
        except (ValueError, TypeError):
            teams = []
        if not teams:
            return "q"
        items = []
        for team in teams:
            name = team.get("name") or QCoreApplication.translate("Nugget", "<Unnamed>")
            items.append(f"{name} ({team.get('id', '')})")
        item, ok = QInputDialog.getItem(
            self,
            QCoreApplication.translate("Nugget", "Development team"),
            QCoreApplication.translate(
                "Nugget", "Your Apple ID has several teams — pick the "
                "personal one (usually the free membership)."),
            items, 0, False)
        if not ok:
            return "q"
        return str(items.index(item) + 1)

    def _ask_certs(self, payload: str) -> str | None:
        try:
            certs = json.loads(payload or "{}").get("certificates", [])
        except (ValueError, TypeError):
            certs = []
        listing = "\n".join(
            "{0}: {1} {2}".format(
                index + 1,
                (cert or {}).get("name") or "?",
                (cert or {}).get("machine_name") or "",
            )
            for index, cert in enumerate(certs))
        text, ok = QInputDialog.getMultiLineText(
            self,
            QCoreApplication.translate("Nugget", "Revoke certificates"),
            QCoreApplication.translate(
                "Nugget",
                "Free accounts hold 2 certificates; a new one needs a slot. "
                "Choose which to revoke (numbers, comma separated):\n"
                "{0}\n\nCertificates backed by other sideloading tools will "
                "stop working. Leave empty to abort.").format(listing or "—"),
            "")
        if not ok:
            return "q"
        return text.strip()

    def _cancel_engine(self):
        if self._eng_proc is not None and self._eng_proc.state() != QProcess.ProcessState.NotRunning:
            self._eng_proc.kill()

    def _on_engine_finished(self, code: int, _status=None):
        # pick up any output that arrived between the last readyRead and finish;
        # a trailing partial line (no newline yet) still gets one last pump
        self._eng_buf += "\n"
        self._pump_engine()
        proc, self._eng_proc = self._eng_proc, None
        mode, self._eng_mode = self._eng_mode, None
        out = self._eng_out
        self._eng_password = None
        if proc is not None:
            proc.deleteLater()
        if self._pending_ipa_path is not None:
            self._cleanup_download(self._pending_ipa_path)
            self._pending_ipa_path = None
        if self._install_progress is not None:
            self._install_progress = self._dismiss(self._install_progress)
        if self._download_progress is not None:
            self._download_progress = self._dismiss(self._download_progress)

        if mode == "build":
            self._set_busy(False)
            if code == 0 and self._refresh_engine_state():
                self._report(QCoreApplication.translate(
                    "Nugget", "Engine built — tap Sign in with Apple ID && "
                    "Sideload again."))
            else:
                self._report(QCoreApplication.translate(
                    "Nugget", "The build failed:\n{0}").format(
                        (out.strip()[-400:] or "no output")))
            return

        # mode == "install" (Apple ID sideload)
        self._set_busy(False)
        if code == 0 and "RESULT OK" in out:
            self._report(QCoreApplication.translate(
                "Nugget",
                "{0} was signed and installed with your Apple ID. "
                "Exporting the pairing file…").format(mh.MOBILE_APP_NAME))
            self._send_pairing()
            return
        detail = self._eng_result_error or self._last_engine_error(out)
        self._report(QCoreApplication.translate(
            "Nugget", "Sideload failed:\n{0}").format(detail))

    @staticmethod
    def _last_engine_error(out: str) -> str:
        lines = [ln for ln in out.splitlines() if ln.strip()]
        for line in reversed(lines):
            if "error" in line.lower() or "fail" in line.lower():
                return line.strip()
        return "\n".join(lines[-3:]) if lines else "no output"

    # --- sideload flow (Apple ID) ---

    def _start_sideload(self):
        if not self._ensure_engine():
            return
        if self._require_device() is None:
            return
        if self._prompt_apple_login():
            self._download_latest(intent="signed")

    def _prompt_apple_login(self) -> bool:
        """Collect the (in-memory) Apple ID credentials for the engine."""
        while True:
            dialog = _AppleLoginDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self._report(QCoreApplication.translate(
                    "Nugget", "Sign-in cancelled — the sideload was not started."))
                return False
            apple_id, password = dialog.credentials()
            if apple_id and password:
                # kept on the dialog instance only; sent to Apple via the engine
                self._apple_id = apple_id
                self._apple_password = password
                return True
            QMessageBox.warning(
                self,
                QCoreApplication.translate("Nugget", "Sign in with Apple ID"),
                QCoreApplication.translate(
                    "Nugget", "Both the Apple ID and the password are required."))

    def _make_busy_dialog(self, label: str, title: str, cancelable: bool = False):
        dialog = QProgressDialog(label, None, 0, 100, self)
        dialog.setWindowTitle(title)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        if not cancelable:
            dialog.setCancelButton(None)
            dialog.setRange(0, 0)
        dialog.setValue(0)
        return dialog

    # --- latest-release download ---

    def _download_direct(self):
        self._download_latest(intent="direct")

    def _download_latest(self, intent: str):
        if not self._require_device():
            return
        if self._release_reply is not None or self._ipa_reply is not None:
            return
        self._download_intent = intent
        self._set_busy(True)
        self._report(QCoreApplication.translate(
            "Nugget", "Checking the latest GoldenNugget Mobile release…"))
        request = QNetworkRequest(QUrl(mh.LATEST_RELEASE_API))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "GoldenNugget")
        self._release_reply = self._nam.get(request)
        self._release_reply.finished.connect(self._on_release_json)

    def _on_release_json(self):
        reply, self._release_reply = self._release_reply, None
        if reply is None:
            return
        data = bytes(reply.readAll())
        err = reply.error()
        reply.deleteLater()
        if err != QNetworkReply.NetworkError.NoError or not data:
            self._set_busy(False)
            self._report(QCoreApplication.translate(
                "Nugget",
                "Could not reach GitHub. Check your internet connection and "
                "try again, or install from a local .ipa file."))
            return
        try:
            release = json.loads(data)
            assets = [a for a in release.get("assets", [])
                      if a.get("name", "").lower().endswith(".ipa")]
        except (ValueError, TypeError):
            assets = []
        if not assets:
            self._set_busy(False)
            self._report(QCoreApplication.translate(
                "Nugget", "No .ipa found in the latest release."))
            return
        asset = assets[0]
        version = release.get("tag_name", "")
        signed = self._download_intent == "signed"
        if not self._confirm_download(asset, version, signed):
            self._set_busy(False)
            return
        self._download_asset(asset)

    def _confirm_download(self, asset: dict, version: str, signed: bool) -> bool:
        mb_size = (asset.get("size", 0) or 0) // 1_000_000
        if signed:
            title = QCoreApplication.translate(
                "Nugget", "Sign with Apple ID && sideload?")
            message = QCoreApplication.translate(
                "Nugget",
                "Release {0} — {1} ({2} MB) will be downloaded, signed with "
                "your Apple ID and installed on the iPhone; the pairing file "
                "is sent afterwards.").format(
                    version, asset.get("name", "GoldenNuggetMobile.ipa"), mb_size)
            return ask_confirmation(self, title, message,
                                    confirm_text=QCoreApplication.translate("Nugget", "Sideload"))
        message = QCoreApplication.translate(
            "Nugget",
            "Release {0} — {1} ({2} MB) will be downloaded from GitHub "
            "and installed on the iPhone.").format(
                version, asset.get("name", "GoldenNuggetMobile.ipa"), mb_size)
        return ask_confirmation(self,
                                QCoreApplication.translate("Nugget", "Download GoldenNugget Mobile?"),
                                message,
                                confirm_text=QCoreApplication.translate("Nugget", "Download"))

    def _download_asset(self, asset: dict):
        self._ipa_file = tempfile.NamedTemporaryFile(
            prefix="goldennugget_mobile_", suffix=".ipa", delete=False)
        self._ipa_response_size = asset.get("size", 0) or 0
        self._download_progress = QProgressDialog(
            QCoreApplication.translate("Nugget", "Downloading…"),
            None, 0, max(1, self._ipa_response_size), self)
        self._download_progress.setWindowTitle(QCoreApplication.translate(
            "Nugget", "Downloading {0}").format(asset.get("name", "GoldenNuggetMobile.ipa")))
        self._download_progress.setCancelButton(None)
        self._download_progress.setWindowModality(Qt.WindowModal)
        self._download_progress.setMinimumDuration(0)
        self._download_progress.setValue(0)
        request = QNetworkRequest(QUrl(asset["browser_download_url"]))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "GoldenNugget")
        self._ipa_reply = self._nam.get(request)
        self._ipa_reply.readyRead.connect(self._drain_ipa_download)
        self._ipa_reply.downloadProgress.connect(self._on_download_progress)
        self._ipa_reply.finished.connect(self._on_ipa_download)

    def _drain_ipa_download(self):
        if self._ipa_reply is None or self._ipa_file is None:
            return
        try:
            self._ipa_file.write(bytes(self._ipa_reply.readAll()))
        except OSError as e:
            self._ipa_reply.abort()
            self._ipa_file = None
            self._report(QCoreApplication.translate("Nugget", "Download failed: {0}").format(e))

    def _on_ipa_download(self):
        reply, self._ipa_reply = self._ipa_reply, None
        if reply is None:
            return
        err = reply.error()
        reply.deleteLater()
        output, self._ipa_file = self._ipa_file, None
        path = output.name if output is not None else ""
        if output is not None:
            try:
                output.close()
            except OSError:
                pass
        self._download_progress = self._dismiss(self._download_progress)
        if output is None or err != QNetworkReply.NetworkError.NoError:
            self._cleanup_download(path)
            self._set_busy(False)
            self._report(QCoreApplication.translate(
                "Nugget", "Download failed. Try again, or install from a local .ipa file."))
            return
        downloaded = 0
        if os.path.isfile(path):
            downloaded = os.path.getsize(path)
        if self._ipa_response_size and downloaded != self._ipa_response_size:
            self._cleanup_download(path)
            self._set_busy(False)
            self._report(QCoreApplication.translate(
                "Nugget", "The download is incomplete ({0} of {1} bytes).").format(
                    downloaded, self._ipa_response_size))
            return
        udid = self._udid()
        if self._download_intent == "signed":
            if self._ensure_engine() and udid is not None:
                self._report(QCoreApplication.translate(
                    "Nugget", "Downloaded — signing with your Apple ID and "
                    "installing…"))
                self._pending_ipa_path = path
                self._install_progress = self._make_busy_dialog(
                    QCoreApplication.translate(
                        "Nugget", "Signing and installing — keep the iPhone awake"),
                    QCoreApplication.translate("Nugget", "Sideload"), cancelable=True)
                self._install_progress.canceled.connect(self._cancel_engine)
                self._start_engine_process(
                    self._engine_path,
                    ["--apple-id", self._apple_id, "--password-stdin",
                     "--udid", udid, path],
                    mode="install", password=self._apple_password)
                return
            self._cleanup_download(path)
            self._set_busy(False)
            self._report(QCoreApplication.translate(
                "Nugget", "The iPhone was disconnected — nothing was installed."))
            return

        self._report(QCoreApplication.translate(
            "Nugget", "Downloaded — installing on the iPhone…"))
        self._pending_ipa_path = path
        self._start_install(path)

    # --- direct install (already-signed IPA) ---

    def _install_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            QCoreApplication.translate("Nugget", "Choose the GoldenNugget Mobile .ipa"),
            os.path.expanduser("~"),
            "iOS app (*.ipa)")
        if not path:
            return
        if self._ensure_engine():
            answer = QMessageBox.question(
                self,
                QCoreApplication.translate("Nugget", "Sign this .ipa?"),
                QCoreApplication.translate(
                    "Nugget",
                    "Sign this .ipa with your Apple ID before installing?\n\n"
                    "Yes — sign with the Apple ID (needed for unsigned IPA).\n"
                    "No — install it as-is (only works if the IPA is already "
                    "signed)."),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                udid = self._require_device()
                if udid is None:
                    return
                if not self._prompt_apple_login():
                    return
                self._pending_ipa_path = path
                self._install_progress = self._make_busy_dialog(
                    QCoreApplication.translate("Nugget", "Signing and installing…"),
                    QCoreApplication.translate("Nugget", "Sideload"), cancelable=True)
                self._install_progress.canceled.connect(self._cancel_engine)
                self._start_engine_process(
                    self._engine_path,
                    ["--apple-id", self._apple_id, "--password-stdin",
                     "--udid", udid, path],
                    mode="install", password=self._apple_password)
                return
        self._start_install(path)

    def _start_install(self, ipa_path: str):
        self._install_progress = QProgressDialog(
            QCoreApplication.translate("Nugget", "Installing GoldenNugget Mobile…"),
            None, 0, 100, self)
        self._install_progress.setWindowTitle(QCoreApplication.translate(
            "Nugget", "Installing"))
        self._install_progress.setWindowModality(Qt.WindowModal)
        self._install_progress.setMinimumDuration(0)
        self._install_progress.setValue(0)
        self._report(QCoreApplication.translate(
            "Nugget", "Installing on the iPhone… If the phone shows the "
            "Trust dialog, tap Trust."))
        self._start_thread("install", {"ipa_path": ipa_path})

    def _on_install_progress(self, percent: float):
        dialog = self._install_progress
        if dialog is None:
            return
        dialog.setRange(0, 100)
        dialog.setValue(int(max(0.0, min(100.0, percent))))
        dialog.setLabelText(QCoreApplication.translate(
            "Nugget", "Installing on the iPhone — {0}%").format(int(percent)))

    def _on_download_progress(self, received: int, total: int):
        dialog = self._download_progress
        if dialog is None:
            return
        if total > 0:
            dialog.setRange(0, total)
            dialog.setValue(received)
            dialog.setLabelText(QCoreApplication.translate(
                "Nugget", "Downloading… {0} of {1} MB").format(
                    received // 1_000_000, max(total, received) // 1_000_000))
        else:
            dialog.setLabelText(QCoreApplication.translate(
                "Nugget", "Downloading… {0} MB").format(received // 1_000_000))

    def _cleanup_download(self, path: str):
        try:
            os.remove(path)
        except (FileNotFoundError, OSError):
            pass

    def _dismiss(self, dialog):
        if dialog is not None:
            try:
                dialog.reset()
                dialog.deleteLater()
            except RuntimeError:
                pass
        return None

    # --- pairing file ---

    def _send_pairing(self):
        if self._require_device() is None:
            return
        self._report(QCoreApplication.translate(
            "Nugget", "Reading the pairing record… If the phone shows the "
            "Trust dialog, tap Trust."))
        self._start_thread("send", {})

    def _save_pairing(self):
        udid = self._require_device()
        if udid is None:
            return
        default_name = os.path.join(
            os.path.expanduser("~"), f"{udid}.mobiledevicepairing")
        path, _ = QFileDialog.getSaveFileName(
            self,
            QCoreApplication.translate("Nugget", "Save Pairing File"),
            default_name,
            "Pairing file (*.mobiledevicepairing)")
        if not path:
            return
        self._report(QCoreApplication.translate(
            "Nugget", "Exporting the pairing record…"))
        self._start_thread("save", {"dest_path": path})

    # --- thread outcomes ---

    def _on_thread_done(self, result: dict):
        action = result.get("action")
        if action == "install":
            self._report(QCoreApplication.translate(
                "Nugget",
                "{0} installed. Now export the pairing file below.").format(
                    result.get("ipa", "GoldenNugget Mobile")))
            return
        if action == "save":
            self._report(QCoreApplication.translate(
                "Nugget",
                "Pairing file saved to:\n{0}\n\nAirDrop it to the iPhone and "
                "share it to GoldenNugget Mobile, or import it from the app's "
                "file picker.").format(result.get("path", "")))
            return
        # action == "send"
        if result.get("sent"):
            self._report(QCoreApplication.translate(
                "Nugget",
                "Pairing file delivered to {0} {1}. Reopen the app to pair.").format(
                    result.get("app", "GoldenNugget Mobile"),
                    result.get("version", "")).strip())
        else:
            # App missing — offer to save the record for a manual import.
            path, _ = QFileDialog.getSaveFileName(
                self,
                QCoreApplication.translate(
                    "Nugget", "GoldenNugget Mobile is not installed — save the pairing file?"),
                os.path.join(os.path.expanduser("~"), f"{self._udid()}.mobiledevicepairing"),
                "Pairing file (*.mobiledevicepairing)")
            if path:
                self._start_thread("save", {"dest_path": path})
            else:
                self._report(QCoreApplication.translate(
                    "Nugget", "Pairing file not sent — the app is not installed."))

    def _on_thread_failed(self, error: str):
        self._report(QCoreApplication.translate("Nugget", "Failed: {0}").format(error))

    # --- lifecycle ---

    def done(self, result):
        proc = getattr(self, "_eng_proc", None)
        if (self._thread is not None and self._thread.isRunning()) or \
                (proc is not None and proc.state() != QProcess.ProcessState.NotRunning) or \
                self._ipa_reply is not None or self._release_reply is not None:
            QMessageBox.information(
                self,
                QCoreApplication.translate("Nugget", "Operation in progress"),
                QCoreApplication.translate(
                    "Nugget",
                    "An operation is still running — closing now would kill "
                    "it. Wait until it finishes, or cancel from its progress "
                    "window."))
            return
        super().done(result)

    def _retheme(self):
        self.setStyleSheet(t("mobile_helper_dialog"))
