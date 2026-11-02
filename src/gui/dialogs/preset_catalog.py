"""Browse the community preset catalog, and submit a preset to it.

The catalog window has two lists: presets (share codes) and .batter
templates. A template is downloaded by id, checked against the size and
SHA-256 in the index, stored in the app's data folder and added to the
Templates list; nothing is applied until the user presses Apply."""
import time

from PySide6.QtCore import QCoreApplication, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QVBoxLayout,
)

from src.controllers import preset_catalog, share_code
from src.gui.dialogs.share_preset import _ThemedDialog
from src.gui.ios.components import IOSSegmentedFilter
from src.gui.theme import ColorThemeManager

AUTHOR_KEY = "catalog_author"


def _tr(text):
    return QCoreApplication.translate("PresetCatalog", text)


def _error_text(error):
    context = "ShareCode" if isinstance(error, share_code.ShareCodeError) else "PresetCatalog"
    return QCoreApplication.translate(context, str(error))


def _size_text(size):
    if size >= 1048576:
        return _tr("{0} MB").format(f"{size / 1048576:.1f}")
    return _tr("{0} KB").format(max(1, round(size / 1024)))


def add_template(path, device_version=""):
    """Add a downloaded template to the Templates list, replacing an older copy."""
    from src.tweaks.posterboard.template_file import TemplateFile
    from src.tweaks.tweaks import TweakID, tweaks
    holder = tweaks[TweakID.Templates]
    template = TemplateFile(path, device_version=device_version or None)
    for old in [item for item in holder.templates if getattr(item, "path", None) == path]:
        holder.templates.remove(old)
        if hasattr(old, "clean_files"):
            old.clean_files()
    holder.templates.append(template)
    return template


def _device_context(window):
    """(iOS version, model, HotLoad or None) of the connected iPhone."""
    manager = getattr(window, "device_manager", None)
    if manager is None:
        return "", "", None
    from src.controllers.hotload import HotLoad
    return (manager.get_current_device_version() or "", manager.get_current_device_model() or "",
            HotLoad(manager.pref_manager.settings))


class CatalogDialog(_ThemedDialog):
    """List on the left, the selected preset with its risk on the right."""

    def __init__(self, preset_manager, device_version="", device_model="", hotload=None,
                 parent=None, fetch=True, embedded=False):
        super().__init__(_tr("Community Catalog"), parent)
        # embedded: a plain widget on the Community Catalog page, whose nav bar
        # already shows the title and which has nothing to close
        self.embedded = embedded
        self.on_change = None   # called after an import or an added template
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setModal(False)
            self._layout.setContentsMargins(16, 16, 16, 16)
            heading = self.findChild(QLabel, "confirmTitle")
            if heading is not None:
                heading.hide()
        self.pm = preset_manager
        self.device_version = device_version
        self.device_model = device_model
        self.hotload = hotload
        self.entries = []
        self.templates = []
        self.imported = []
        self.added_templates = []
        self.installed = {}     # see preset_catalog.installed_items
        self.add_template = add_template
        self._download = None
        self.risk_panel = None
        self._reply = None
        self._saved_at = 0
        if not embedded:
            self.setMinimumSize(880, 620)
        self._muted(_tr("Presets and templates shared by the community and reviewed by the GoldenNugget "
                        "team. Nothing reaches your iPhone until you apply."))
        self.kind = IOSSegmentedFilter([(_tr("Presets"), "presets"), (_tr("Templates"), "templates")])
        self.kind.currentIndexChanged.connect(lambda *_: self._fill_list())
        self._layout.addWidget(self.kind)

        filters = QHBoxLayout()
        filters.setSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_tr("Search by name, author or tag"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill_list)
        filters.addWidget(self.search, 1)
        self.compatible_only = QCheckBox(_tr("Only for iOS {0}").format(device_version))
        self.compatible_only.setChecked(bool(device_version))
        self.compatible_only.setVisible(bool(device_version))
        self.compatible_only.toggled.connect(self._fill_list)
        filters.addWidget(self.compatible_only)
        self.refresh_button = self._button(_tr("Refresh"), self.fetch)
        filters.addWidget(self.refresh_button)
        self._layout.addLayout(filters)
        self.status = self._muted("")

        body = QHBoxLayout()
        body.setSpacing(16)
        self.list = QListWidget()
        self.list.setFixedWidth(320)
        self.list.currentItemChanged.connect(lambda *_: self._show_selected())
        body.addWidget(self.list)
        detail = QVBoxLayout()
        detail.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName("catalogName")
        self.title.setWordWrap(True)
        detail.addWidget(self.title)
        self.meta = QLabel()
        self.meta.setObjectName("confirmMuted")
        self.meta.setWordWrap(True)
        detail.addWidget(self.meta)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setTextFormat(Qt.PlainText)
        self.description.setObjectName("catalogText")
        detail.addWidget(self.description)
        self.writes = QLabel()
        self.writes.setWordWrap(True)
        self.writes.setTextFormat(Qt.PlainText)
        self.writes.setObjectName("confirmMuted")
        self.writes.setTextInteractionFlags(Qt.TextSelectableByMouse)
        detail.addWidget(self.writes)
        self._risk_holder = QVBoxLayout()
        detail.addLayout(self._risk_holder)
        detail.addStretch()
        actions = QHBoxLayout()
        actions.setSpacing(12)
        actions.addStretch()
        self.preview_button = self._button(
            QCoreApplication.translate("DeviceTwin", "Preview on iPhone"), self._preview)
        actions.addWidget(self.preview_button)
        self.import_button = self._button(_tr("Import"), self._import, secondary=False)
        actions.addWidget(self.import_button)
        detail.addLayout(actions)
        body.addLayout(detail, 1)
        self._layout.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.addWidget(self._button(_tr("How to Submit…"), self._open_repo))
        footer.addStretch()
        if not embedded:
            footer.addWidget(self._button(_tr("Close"), self.accept))
        self._layout.addLayout(footer)
        self._retheme()
        self._show_selected()

        cached, saved_at = preset_catalog.read_cache()
        if cached is not None:
            self.load_data(cached, saved_at=saved_at)
        if fetch:
            self.fetch()

    def _retheme(self):
        super()._retheme()
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(self.styleSheet() + f"""
            QListWidget {{ background-color: {c.bg_input}; border: none; border-radius: 10px;
                color: {c.text_primary}; font-size: 13px; padding: 4px; }}
            QListWidget::item {{ padding: 8px; border-radius: 6px; }}
            QListWidget::item:selected {{ background-color: {c.scrollbar_pressed}; color: {c.text_primary}; }}
            QLabel#catalogName {{ color: {c.text_primary}; font-size: 18px; font-weight: 600; }}
            QLabel#catalogText {{ color: {c.text_primary}; font-size: 14px; }}
        """)

    # --- loading ---------------------------------------------------------
    def fetch(self):
        if self._reply is not None:
            return
        if not hasattr(self, "_nam"):
            self._nam = QNetworkAccessManager(self)
        request = QNetworkRequest(QUrl(preset_catalog.INDEX_URL))
        request.setRawHeader(b"User-Agent", b"GoldenNugget")
        request.setTransferTimeout(15000)
        self._reply = self._nam.get(request)
        self._reply.downloadProgress.connect(self._on_progress)
        self._reply.finished.connect(self._on_finished)
        self.refresh_button.setEnabled(False)
        if not self.entries and not self.templates:
            self.status.setText(_tr("Loading the catalog…"))
            self.status.setVisible(True)

    def _on_progress(self, received, _total):
        if received > preset_catalog.MAX_INDEX_BYTES and self._reply is not None:
            self._reply.abort()

    def _on_finished(self):
        reply, self._reply = self._reply, None
        self.refresh_button.setEnabled(True)
        if reply is None:
            return
        data = bytes(reply.readAll())
        error = reply.error()
        message = reply.errorString()
        reply.deleteLater()
        if error != QNetworkReply.NetworkError.NoError:
            self._offline(message)
            return
        if self.load_data(data):
            preset_catalog.write_cache(data)

    def _offline(self, message):
        if self.entries or self.templates:
            self.status.setText(_tr("Could not reach the catalog, so this is the copy saved on {0}.").format(
                time.strftime("%Y-%m-%d", time.localtime(self._saved_at))) if self._saved_at else message)
        else:
            self.status.setText(_tr("Could not load the catalog: {0}").format(message))
        self.status.setVisible(True)

    def load_data(self, data, saved_at=0):
        """Show the presets in index.json ``data``; returns False when it is unusable."""
        try:
            entries, templates, rejected = preset_catalog.parse_catalog(data, self.pm._valid_import_structure)
        except preset_catalog.CatalogError as error:
            if not self.entries and not self.templates:
                self._offline(_error_text(error))
            return False
        self.entries = entries
        self.templates = templates
        self._saved_at = saved_at
        self._rejected = rejected
        self.refresh_installed()
        return True

    def refresh_installed(self):
        """Re-read what is imported or downloaded, for the update marks."""
        self.installed = preset_catalog.installed_items(self.pm)
        text = _tr("{0} preset(s) and {1} template(s) in the catalog.").format(len(self.entries), len(self.templates))
        if getattr(self, "_rejected", 0):
            text += " " + _tr("{0} damaged entry(s) were skipped.").format(self._rejected)
        updates = self.update_count()
        if updates:
            text += " " + _tr("{0} update(s) available.").format(updates)
        self.status.setText(text)
        self.status.setVisible(True)
        self._fill_list()

    def update_count(self):
        return preset_catalog.count_updates(self.entries + self.templates, self.installed)

    def status_of(self, entry):
        return preset_catalog.entry_status(entry, self.installed)

    def showing_templates(self):
        return self.kind.currentData() == "templates"

    def _source(self):
        return self.templates if self.showing_templates() else self.entries

    def visible_entries(self):
        version = self.device_version if self.compatible_only.isChecked() else ""
        query = self.search.text()
        return [entry for entry in self._source() if entry.supports(version) and entry.matches(query)]

    def _fill_list(self):
        selected = self.selected_entry()
        self.list.clear()
        for entry in self.visible_entries():
            mark = {preset_catalog.UPDATE: "  ·  " + _tr("Update available"),
                    preset_catalog.INSTALLED: "  ·  ✓"}.get(self.status_of(entry)[0], "")
            if entry.untested:
                mark += "  ·  ⚠ " + _tr("Not tested on a device")
            item = QListWidgetItem(f"{entry.name}\n{entry.author}{mark}")
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            item.setToolTip(", ".join(entry.tags))
            self.list.addItem(item)
            if selected is not None and entry.id == selected.id:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._show_selected()

    def selected_entry(self):
        item = self.list.currentItem() if hasattr(self, "list") else None
        entry_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        return next((entry for entry in self._source() if entry.id == entry_id), None)

    def _show_selected(self):
        from src.controllers.risk_assessment import assess
        from src.gui.ios.risk_panel import RiskPanel
        entry = self.selected_entry()
        if self.risk_panel is not None:
            self._risk_holder.removeWidget(self.risk_panel)
            self.risk_panel.hide()
            self.risk_panel.deleteLater()
            self.risk_panel = None
        templates = self.showing_templates()
        self.preview_button.setVisible(not templates)
        state = self.status_of(entry)[0] if entry is not None else None
        if state == preset_catalog.UPDATE:
            self.import_button.setText(_tr("Update"))
        elif state == preset_catalog.INSTALLED:
            self.import_button.setText(_tr("Download Again") if templates else _tr("Import Again"))
        else:
            self.import_button.setText(_tr("Download and Add") if templates else _tr("Import"))
        for button in (self.preview_button, self.import_button):
            button.setEnabled(entry is not None and self._download is None)
        self.writes.setVisible(templates and entry is not None)
        if entry is None:
            empty = _tr("No templates found") if templates else _tr("No presets found")
            self.title.setText(empty if self._source() else "")
            self.meta.setText("")
            self.description.setText("")
            return
        self.title.setText(entry.name)
        parts = [_tr("by {0}").format(entry.author),
                 _tr("{0} tweak(s)").format(entry.tweak_count)]
        if templates:
            parts.append(_size_text(entry.size))
        if entry.ios_range():
            parts.append(_tr("iOS {0}").format(entry.ios_range()))
        if entry.tags:
            parts.append(", ".join(entry.tags))
        if entry.untested:
            parts.append("⚠ " + _tr("not tested on a device by its author"))
        if state == preset_catalog.UPDATE:
            parts.append(_tr("a newer version than yours"))
        elif state == preset_catalog.INSTALLED:
            parts.append(_tr("already added") if templates else _tr("already imported"))
        self.meta.setText("  ·  ".join(parts))
        self.description.setText(entry.description)
        self.description.setVisible(bool(entry.description))
        if templates:
            self.writes.setText(self._writes_text(entry))
            return
        report = assess(self._tweaks(entry), self.device_version, self.device_model, hotload=self.hotload)
        self.risk_panel = RiskPanel(report)
        self._risk_holder.addWidget(self.risk_panel)

    @staticmethod
    def _writes_text(entry):
        lines = []
        if entry.domain:
            lines.append(_tr("Restores its own files to {0}.").format(entry.domain))
        if entry.writes:
            lines.append(_tr("What its tweaks write on the iPhone:"))
            lines += [f"• {label}: " + ", ".join(paths) for label, paths in entry.writes]
        return "\n".join(lines)

    def _tweaks(self, entry):
        return share_code.decode(entry.code)["tweaks"]

    # --- actions ---------------------------------------------------------
    def _preview(self):
        entry = self.selected_entry()
        if entry is None:
            return
        from src.gui.dialogs.device_twin import show_twin
        show_twin(self, self._tweaks(entry), self.device_version, self.device_model, title=entry.name)

    def _import(self):
        entry = self.selected_entry()
        if entry is None:
            return
        if isinstance(entry, preset_catalog.TemplateEntry):
            self._start_download(entry)
            return
        state, existing = self.status_of(entry)
        try:
            if state == preset_catalog.UPDATE:
                # an update replaces the imported preset under its current name
                name = self.pm.import_share_code(entry.code, existing, preset_catalog.catalog_mark(entry),
                                                 replace=True)
            else:
                name = self.pm.import_share_code(entry.code, entry.name, preset_catalog.catalog_mark(entry))
        except (share_code.ShareCodeError, OSError) as error:
            QMessageBox.critical(self, self.windowTitle(), _error_text(error))
            return
        self.imported.append(name)
        self.refresh_installed()
        self._changed()
        if state == preset_catalog.UPDATE:
            text = _tr("“{0}” was updated. Load it again on the Presets page to use the new version.")
        else:
            text = _tr("“{0}” was saved to your presets. Load it on the Presets page to use it.")
        QMessageBox.information(self, self.windowTitle(), text.format(name))

    def _start_download(self, entry):
        if self._download is not None:
            return
        if not hasattr(self, "_nam"):
            self._nam = QNetworkAccessManager(self)
        request = QNetworkRequest(QUrl(entry.url))
        request.setRawHeader(b"User-Agent", b"GoldenNugget")
        request.setTransferTimeout(60000)
        reply = self._nam.get(request)
        self._download = (reply, entry)
        reply.downloadProgress.connect(lambda received, _total: (
            received > entry.size and reply.abort()))
        reply.finished.connect(self._on_downloaded)
        self.import_button.setEnabled(False)
        self.status.setText(_tr("Downloading “{0}”…").format(entry.name))
        self.status.setVisible(True)

    def _on_downloaded(self):
        if self._download is None:
            return
        (reply, entry), self._download = self._download, None
        data = bytes(reply.readAll())
        error, message = reply.error(), reply.errorString()
        reply.deleteLater()
        self.status.setText("")
        self._show_selected()
        if error != QNetworkReply.NetworkError.NoError:
            QMessageBox.critical(self, self.windowTitle(), _tr("Could not download the template: {0}").format(message))
            return
        self.install_template(entry, data)

    def install_template(self, entry, data) -> bool:
        """Check, store and add downloaded template bytes."""
        try:
            path = preset_catalog.save_template(entry, data)
            self.add_template(path, self.device_version)
        except preset_catalog.CatalogError as error:
            QMessageBox.critical(self, self.windowTitle(), _error_text(error))
            return False
        except Exception as error:  # the template loader raises several kinds
            QMessageBox.critical(self, self.windowTitle(),
                                 _tr("The template could not be added: {0}").format(error))
            return False
        self.added_templates.append(path)
        self.refresh_installed()
        self._changed()
        QMessageBox.information(
            self, self.windowTitle(),
            _tr("“{0}” was added to PosterBoard → Templates. Turn on the tweaks you want there, "
                "then apply.").format(entry.name))
        return True

    def _changed(self):
        if self.on_change is not None:
            self.on_change()

    def stop(self):
        """Abort downloads still running (the embedded page never calls done())."""
        for pending in (self._reply, self._download[0] if self._download else None):
            if pending is not None:
                pending.abort()
                pending.deleteLater()
        self._reply = self._download = None

    def _open_repo(self):
        anchor = "#submitting-a-template" if self.showing_templates() else "#submitting-a-preset"
        QDesktopServices.openUrl(QUrl(preset_catalog.REPO_URL + anchor))

    def done(self, result):
        self.stop()
        super().done(result)


class SubmitPresetDialog(_ThemedDialog):
    """Fill in the catalog details for a saved preset, then open GitHub."""

    def __init__(self, preset_manager, preset_name, code, settings=None, device_version="",
                 device_model="", hotload=None, parent=None):
        super().__init__(_tr("Submit to Catalog"), parent)
        self.pm = preset_manager
        self.code = code
        self.settings = settings
        self.submitted = None
        self.setMinimumWidth(560)
        data = preset_manager.read_preset(preset_name) or {"tweaks": {}, "metadata": {}}
        meta = data.get("metadata", {})
        self._muted(_tr("Your preset is sent as a pull request to the GoldenNugget-Presets repository on "
                        "GitHub (you need a free GitHub account). The team reviews it before it appears "
                        "in the catalog. Templates, icon themes and wallpapers are not included."))

        names = QHBoxLayout()
        names.setSpacing(12)
        self.name_edit = self._field(_tr("Name"), "", preset_name, preset_catalog.TEXT_LIMITS["name"], names)
        author = settings.value(AUTHOR_KEY, "", type=str) if settings is not None else ""
        self.author_edit = self._field(_tr("Author"), _tr("Your nickname"), author,
                                       preset_catalog.TEXT_LIMITS["author"], names)
        self._layout.addLayout(names)
        self.description_edit = QPlainTextEdit(meta.get("description", ""))
        self.description_edit.setPlaceholderText(_tr("What it changes, in a sentence or two"))
        self.description_edit.setFixedHeight(76)
        self.description_edit.setAccessibleName(_tr("Description"))
        description = QVBoxLayout()
        description.setSpacing(4)
        description.addWidget(self._caption(_tr("Description")))
        description.addWidget(self.description_edit)
        self._layout.addLayout(description)
        details = QHBoxLayout()
        details.setSpacing(12)
        ios = meta.get("ios_version", "")
        ios = ios if preset_catalog.VERSION_PATTERN.match(ios or "") else ""
        self.tags_edit = self._field(_tr("Tags"), _tr("battery, minimal"), "", None, details, 2)
        self.ios_min_edit = self._field(_tr("Lowest iOS"), _tr("Any"), ios, 8, details)
        self.ios_max_edit = self._field(_tr("Highest iOS"), _tr("Any"), "", 8, details)
        self._layout.addLayout(details)
        self.tested_check = QCheckBox(_tr("I tested this preset on my iPhone"))
        self.tested_check.setToolTip(_tr("Leave it off and the catalog marks the preset as not tested on a device."))
        self._layout.addWidget(self.tested_check)

        from src.controllers.risk_assessment import assess
        from src.gui.ios.risk_panel import RiskPanel
        self._layout.addWidget(RiskPanel(assess(
            share_code.decode(code)["tweaks"], device_version, device_model, hotload=hotload)))
        self.error = self._muted("")
        self.error.setObjectName("catalogError")
        self.error.setVisible(False)

        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        buttons.addStretch()
        buttons.addWidget(self._button(_tr("Cancel"), self.reject))
        buttons.addWidget(self._button(_tr("Open GitHub"), self._submit, secondary=False))
        self._layout.addLayout(buttons)
        self._retheme()

    def _retheme(self):
        super()._retheme()
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(self.styleSheet() + f"QLabel#catalogError {{ color: {c.error}; }}")

    @staticmethod
    def _caption(text):
        label = QLabel(text)
        label.setObjectName("confirmMuted")
        return label

    def _field(self, caption, placeholder, text, limit, row, stretch=1):
        """A captioned line edit added as one column of ``row``."""
        column = QVBoxLayout()
        column.setSpacing(4)
        column.addWidget(self._caption(caption))
        edit = QLineEdit(text)
        edit.setPlaceholderText(placeholder)
        edit.setAccessibleName(caption)
        if limit:
            edit.setMaxLength(limit)
        column.addWidget(edit)
        row.addLayout(column, stretch)
        return edit

    def build(self):
        """(file name, file text) for the entered details; raises CatalogError."""
        return preset_catalog.submission(
            self.name_edit.text(), self.author_edit.text(), self.code,
            description=self.description_edit.toPlainText(),
            ios_min=self.ios_min_edit.text().strip(), ios_max=self.ios_max_edit.text().strip(),
            tags=self.tags_edit.text().split(","), validate=self.pm._valid_import_structure,
            untested=not self.tested_check.isChecked())

    def _submit(self):
        try:
            filename, text = self.build()
        except (preset_catalog.CatalogError, share_code.ShareCodeError) as error:
            self.error.setText(_error_text(error))
            self.error.setVisible(True)
            return
        if self.settings is not None:
            self.settings.setValue(AUTHOR_KEY, self.author_edit.text().strip())
        url, prefilled = preset_catalog.submit_url(filename, text)
        if not prefilled:
            QGuiApplication.clipboard().setText(text)
        QDesktopServices.openUrl(QUrl.fromEncoded(url.encode("ascii")))
        self.submitted = (filename, prefilled)
        steps = _tr("In the browser, click “Propose changes”, then “Create pull request”.")
        if not prefilled:
            steps = _tr("The preset is too long to fill in automatically, so it was copied. "
                        "Paste it into the empty file on GitHub.") + "\n\n" + steps
        QMessageBox.information(self, self.windowTitle(), steps)
        self.accept()


def browse_catalog_flow(parent, pm, window=None):
    """Returns the names of the presets imported from the catalog."""
    version, model, hotload = _device_context(window)
    dialog = CatalogDialog(pm, version, model, hotload, parent)
    dialog.exec()
    imported = list(dialog.imported)
    if dialog.added_templates:
        refresh_template_list(window)
    dialog.deleteLater()
    return imported


def refresh_template_list(window):
    page = getattr(window, "ios_templates", None)
    if page is not None and hasattr(page, "_load_templates_list"):
        page._load_templates_list()


def submit_preset_flow(parent, pm, name, window=None) -> bool:
    try:
        code = pm.share_code(name)
    except share_code.ShareCodeError as error:
        QMessageBox.warning(parent, _tr("Submit to Catalog"), _error_text(error))
        return False
    version, model, hotload = _device_context(window)
    settings = getattr(window, "settings", None)
    # ``window.settings`` is the app's Qt-free ``src.utils.settings.Settings``
    # store; duck-type it instead of checking for QSettings.
    if settings is None or not hasattr(settings, "value"):
        settings = None
    dialog = SubmitPresetDialog(pm, name, code, settings, version, model, hotload, parent)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    dialog.deleteLater()
    return accepted
