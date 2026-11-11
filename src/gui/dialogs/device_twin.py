"""Dialog around DeviceTwinView: the two screens plus what they do and do not show."""
from PySide6.QtCore import QCoreApplication, Qt, QThread, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from src.gui.ios.device_twin import DeviceTwinView
from src.gui.theme import t
from src.gui.theme.theme_manager import connect_visible_theme


def _tr(text):
    return QCoreApplication.translate("DeviceTwin", text)


def legend_text(state) -> str:
    lines = []
    if state.shown:
        lines.append(_tr("On the preview: {0}.").format(", ".join(state.shown)))
    else:
        lines.append(_tr("None of the selected tweaks change how the screens look."))
    if state.not_shown:
        lines.append(_tr("{0} more tweak(s) change behaviour, not looks, so they are not drawn.").format(
            state.not_shown))
    lines.append(_tr("This is a drawing to compare looks, not a screenshot of your iPhone."))
    return "\n".join(lines)


class DeviceTwinDialog(QDialog):
    def __init__(self, state, title="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title or _tr("iPhone Preview"))
        self.setModal(True)
        self.resize(760, 860)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        heading = QLabel(self.windowTitle())
        heading.setObjectName("confirmTitle")
        layout.addWidget(heading)
        self.view = DeviceTwinView(state)
        layout.addWidget(self.view, 1)
        self.legend = QLabel(legend_text(state))
        self.legend.setObjectName("confirmMuted")
        self.legend.setWordWrap(True)
        layout.addWidget(self.legend)
        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton(_tr("Close"))
        close.setCursor(Qt.PointingHandCursor)
        close.setMinimumHeight(44)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._retheme()
        connect_visible_theme(self)

    def _retheme(self):
        self.setStyleSheet(t("confirm_dialog") + t("summary_dialog"))


class _IconFetchThread(QThread):
    """Reads the stock app icons off the iPhone without blocking the dialog."""
    fetched = Signal(dict)

    def __init__(self, udid, version, parent=None):
        super().__init__(parent)
        self.udid, self.version = udid, version

    def run(self):
        import asyncio
        import logging

        from src.controllers.device_icons import fetch_icons
        try:
            icons = asyncio.run(fetch_icons(self.udid, self.version))
        except Exception as error:
            logging.getLogger("GoldenNugget.preview").info("Could not read app icons: %s", error)
            return
        if icons:
            self.fetched.emit(icons)


def show_twin(parent, tweaks_data, version="", model="", build="", wallpaper=None, title="",
              udid=None):
    from src.gui.ios.device_twin import build_state
    state = build_state(tweaks_data, version, model, build, wallpaper)
    fetcher = None
    if udid:
        from src.controllers.device_icons import cached_icons
        state.stock_icons = cached_icons(udid, version)
    dialog = DeviceTwinDialog(state, title, parent)
    if udid and not state.stock_icons:
        fetcher = _IconFetchThread(udid, version, dialog)

        def use_icons(icons):
            state.stock_icons = icons
            dialog.view.set_state(state)

        fetcher.fetched.connect(use_icons)
        fetcher.start()
    dialog.exec()
    if fetcher is not None:
        fetcher.wait()
    dialog.deleteLater()
    return state


def show_current_twin(window, parent=None):
    """Twin for the current selection on the connected (or a default) iPhone."""
    from src.controllers.hotload import HotLoad
    from src.controllers.preset_manager import PresetManager
    from src.gui.ios.device_twin import current_wallpaper
    manager = window.device_manager
    version = manager.get_current_device_version() or ""
    model = manager.get_current_device_model() or ""
    build = ""
    try:
        build = manager.data_singleton.current_device.build or ""
    except AttributeError:
        pass
    hotload = HotLoad(manager.pref_manager.settings)
    context = dict(device_version=version, device_model=model)
    hidden = hotload.hidden_tweak_names(**context)
    data = {name: entry for name, entry in PresetManager()._serialize()["tweaks"].items()
            if name not in hidden and hotload.rule_for(name, **context) is None}
    return show_twin(parent or window, data, version, model, build, current_wallpaper(),
                     udid=manager.get_current_device_udid())
