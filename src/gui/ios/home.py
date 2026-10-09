from PySide6.QtCore import (
    Qt, QCoreApplication, Slot, QTimer, QSize, QEvent, Signal, QThread,
    QPropertyAnimation, QEasingCurve,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QSizePolicy, QScrollArea, QGraphicsOpacityEffect, QProgressBar
)

from src.gui.ios.components import IOSCard, IOSPrimaryButton, IOSDangerButton
from src.gui.preset_widget import PresetWidget
from src.gui.theme import t, ColorThemeManager, theme_icon, theme_pixmap

# Feature tile icon per home card (keyed by the card title).
_FEATURE_ICONS = {
    "PosterBoard": ":/icon/wallpaper.svg",
    "Tweaks": ":/icon/toggles.svg",
    "Daemons": ":/icon/hdd.svg",
    "Status Bar": ":/icon/app-indicator.svg",
    "Icon Themes": ":/icon/brush.svg",
    "Passcode Theme": ":/icon/lock.svg",
}


class _StorageThread(QThread):
    result = Signal(object, object)

    def __init__(self, udid, parent=None):
        super().__init__(parent)
        self.udid = udid

    def run(self):
        import asyncio
        try:
            total, free = asyncio.run(self._query())
        except Exception:
            total, free = None, None
        self.result.emit(total, free)

    async def _query(self):
        from src.devicemanagement.session import lockdown_session
        from pymobiledevice3.services.diagnostics import DiagnosticsService
        async with lockdown_session(self.udid) as lockdown:
            try:
                async with DiagnosticsService(lockdown) as diagnostics:
                    report = await diagnostics.info("All")
                if isinstance(report, dict):
                    nested = report.get("DiskUsage") if isinstance(report.get("DiskUsage"), dict) else {}
                    total = report.get("TotalDataCapacity", nested.get("TotalDataCapacity"))
                    free = report.get("TotalDataSpace", nested.get("TotalDataSpace"))
                    if total is not None and free is not None:
                        return int(total), int(free)
            except Exception:
                # Some iOS versions reject the diagnostics relay request while
                # still exposing the same volume figures through AFC.
                pass

            from pymobiledevice3.services.afc import AfcService
            async with AfcService(lockdown) as afc:
                info = await afc.get_device_info()
            total = self._first_number(info, "FSTotalBytes", "TotalBytes")
            free = self._first_number(info, "FSFreeBytes", "FreeBytes")
            if total is None or free is None:
                return None, None
            return total, free

    @staticmethod
    def _first_number(values, *keys):
        if not isinstance(values, dict):
            return None
        for key in keys:
            value = values.get(key)
            try:
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                continue
        return None


class _TileCard(IOSCard):
    """A home feature tile (icon + name). Same look as a card, plus hover."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover_effect = QGraphicsOpacityEffect(self)
        self._hover_effect.setOpacity(0.92)
        self.setGraphicsEffect(self._hover_effect)
        self._hover_anim = QPropertyAnimation(self._hover_effect, b"opacity", self)
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _animate_hover(self, opacity: float):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_effect.opacity())
        self._hover_anim.setEndValue(opacity)
        self._hover_anim.start()

    def enterEvent(self, event):
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.92)
        super().leaveEvent(event)

    def _retheme(self):
        self.setStyleSheet(t("home_tile"))


class _CardGrid(QWidget):
    """Responsive grid for the home feature tiles.

    Reflows the visible tiles into columns based on the available width, up to
    ``MAX_COLUMNS``: all six features stay on one row at every window size the
    app allows (the window has a 1000px minimum and the iOS shell hides the
    sidebar, so the home page always has room for the full row).
    Tiles hidden on purpose (Status Bar on iOS 27, HotLoad-hidden features)
    are tracked via their Show/Hide events, so the grid stays correct even
    before the page itself has been shown. Hidden tiles are dropped from the
    layout entirely and collapse cleanly.
    """
    MIN_CARD_WIDTH = 140
    SPACING = 12
    MAX_COLUMNS = 6

    def __init__(self, cards, parent=None):
        super().__init__(parent)
        self._cards = cards
        self._hidden = set()
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(self.SPACING)
        self._grid.setVerticalSpacing(self.SPACING)
        for card in cards:
            card.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            card.installEventFilter(self)
        self._layout_key = None
        self._reflow()

    def eventFilter(self, obj, event):
        if obj in self._cards:
            etype = event.type()
            if etype == QEvent.Hide:
                self._hidden.add(obj)
                self._reflow()
            elif etype == QEvent.Show:
                self._hidden.discard(obj)
                self._reflow()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def reflow(self):
        self._reflow()

    def _col_count(self, count: int) -> int:
        """Pick the largest column count whose tiles stay wide enough.

        Never more than ``MAX_COLUMNS``, so a wide window must not stretch the
        tiles into a long strip; narrower windows drop a column instead of
        squeezing the tiles below a readable width.
        """
        for n in range(min(count, self.MAX_COLUMNS), 0, -1):
            avail = self.width() - self.SPACING * (n - 1)
            if avail / n >= self.MIN_CARD_WIDTH:
                return n
        return 1

    def _reflow(self):
        include = [c for c in self._cards if c not in self._hidden]
        target = []
        if include:
            cols = max(1, min(len(include), self._col_count(len(include))))
            for i, card in enumerate(include):
                target.append((i // cols, i % cols, card))
        key = tuple((r, c, id(w)) for r, c, w in target)
        if key == self._layout_key:
            return
        for card in self._cards:
            self._grid.removeWidget(card)
        for col in range(self.MAX_COLUMNS):
            self._grid.setColumnStretch(col, 1 if col < len(include) else 0)
        for r, c, w in target:
            self._grid.addWidget(w, r, c)
        self._layout_key = key


class IOSHomePage(QWidget):
    # Feature tile: a big icon over the name. The tile height is left to the
    # layout so a subtitle that wraps to two lines grows the whole row.
    TILE_ICON_PX = 68

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("iosContainer")
        self._c = ColorThemeManager.instance().colors
        # (icon label, icon resource, title label, subtitle label) per tile
        self._tiles = []

        # Scroll area: the tile grid must never be squeezed below the tile
        # content height, so a short window scrolls instead of overlapping.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        self._scroll = scroll
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Logo + Title row
        header = QHBoxLayout()
        header.setSpacing(16)

        # Load logo from resources
        self._logo = QLabel(self)
        self._logo.setFixedSize(80, 80)
        self._logo.setScaledContents(True)
        pixmap = QPixmap(":/credits/big_nugget.png")
        if not pixmap.isNull():
            self._logo.setPixmap(pixmap)
        else:
            self._logo.setStyleSheet(f"background-color: {self._c.bg_secondary}; border-radius: 14px;")
        header.addWidget(self._logo)

        title_layout = QVBoxLayout()
        self._title = QLabel(QCoreApplication.translate("Nugget", "GoldenNugget"), self)
        self._title.setStyleSheet(t("home_title"))
        title_layout.addWidget(self._title)

        self.subtitle = QLabel(QCoreApplication.translate("Nugget", "iPhone (iOS —)"), self)
        self.subtitle.setStyleSheet(t("home_subtitle"))
        title_layout.addWidget(self.subtitle)
        header.addLayout(title_layout, 1)

        self.device_combo = QComboBox(self)
        self.device_combo.setFixedHeight(36)
        self._style_device_combo()
        self.populate_device_picker()
        self.device_combo.currentIndexChanged.connect(self.on_device_changed)
        header.addWidget(self.device_combo)

        self._refresh_btn = QPushButton(self)
        self._refresh_btn.setFixedSize(36, 36)
        self._refresh_btn.setIconSize(QSize(18, 18))
        self._refresh_btn.setStyleSheet(t("home_icon_button"))
        self._apply_icon(self._refresh_btn, ":/icon/arrow-clockwise.svg")
        self._refresh_btn.clicked.connect(self.refresh_devices)
        header.addWidget(self._refresh_btn)

        self._logs_btn = QPushButton(self)
        self._logs_btn.setFixedSize(36, 36)
        self._logs_btn.setIconSize(QSize(18, 18))
        self._logs_btn.setStyleSheet(t("home_icon_button"))
        self._logs_btn.setToolTip(QCoreApplication.translate("Nugget", "Application Log"))
        self._apply_icon(self._logs_btn, ":/icon/file-earmark-text.svg")
        self._logs_btn.clicked.connect(self.open_logs)
        header.addWidget(self._logs_btn)

        self._settings_btn = QPushButton(self)
        self._settings_btn.setFixedSize(36, 36)
        self._settings_btn.setIconSize(QSize(18, 18))
        self._settings_btn.setStyleSheet(t("home_icon_button"))
        self._apply_icon(self._settings_btn, ":/icon/gear.svg")
        self._settings_btn.clicked.connect(self.open_settings)
        header.addWidget(self._settings_btn)

        layout.addLayout(header)

        self.status_lbl = QLabel("", self)
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setTextFormat(Qt.RichText)
        layout.addWidget(self.status_lbl)

        self.storage_card = IOSCard()
        storage_layout = QVBoxLayout(self.storage_card)
        storage_layout.setContentsMargins(16, 12, 16, 12)
        storage_layout.setSpacing(6)
        self.storage_title = QLabel(QCoreApplication.translate("Nugget", "iPhone Storage"))
        self.storage_title.setStyleSheet(t("home_tile_title"))
        storage_layout.addWidget(self.storage_title)
        self.storage_bar = QProgressBar()
        self.storage_bar.setRange(0, 100)
        self.storage_bar.setValue(0)
        self.storage_bar.setTextVisible(False)
        self.storage_bar.setFixedHeight(8)
        storage_layout.addWidget(self.storage_bar)
        self.storage_lbl = QLabel(QCoreApplication.translate("Nugget", "Connect an iPhone to view storage"))
        self.storage_lbl.setStyleSheet(t("home_tile_subtitle"))
        storage_layout.addWidget(self.storage_lbl)
        layout.addWidget(self.storage_card)
        self._storage_thread = None

        cards_row = [self._make_card(
            "PosterBoard", "Animated wallpapers & templates", 2),
            self._make_card(
            "Tweaks", "Customize system settings", 1),
            self._make_card(
            "Daemons", "Disable system daemons", 3),
            self._make_card(
            "Status Bar", "Customize the status bar", 5),
            self._make_card(
            "Icon Themes", "Themed app icons & labels", 10),
            self._make_card(
            "Passcode Theme", "Custom keypad theme (.passthm)", 11)]
        (self.posterboard_card, self.tweaks_card,
         self.daemons_card, self.statusbar_card,
         self.icon_themes_card, self.passcode_theme_card) = cards_row
        self.cards_grid = _CardGrid(cards_row)
        layout.addWidget(self.cards_grid)

        # Apply / Reset share one row instead of stacking, which also keeps the
        # preset widget closer to the top on short windows.
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(12)

        apply_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Apply Tweaks"))
        apply_btn.clicked.connect(self.open_apply_classic)
        actions.addWidget(apply_btn, 1)

        reset_btn = IOSDangerButton(QCoreApplication.translate("Nugget", "Reset Tweaks"))
        reset_btn.clicked.connect(self.reset_tweaks)
        actions.addWidget(reset_btn, 1)

        layout.addLayout(actions)

        self.preset_widget = PresetWidget(
            window=self.window, on_manage=self.open_presets_section, ios_style=True)
        layout.addWidget(self.preset_widget)

        self.process_status_lbl = QLabel("", self)
        self.process_status_lbl.setWordWrap(True)
        self.process_status_lbl.setAlignment(Qt.AlignCenter)
        self.process_status_lbl.setStyleSheet(t("process_status_green"))
        self.process_status_lbl.hide()
        layout.addWidget(self.process_status_lbl)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_process_status)

        layout.addStretch()

        # Paint the scroll area background for the active palette right away
        # (the shared _retheme only re-runs on a theme change).
        self._retheme()
        self.update_status()
        self.update_device_info()
        self.refresh_preset_widget()

    def _style_device_combo(self):
        c = self._c
        self.device_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {c.bg_secondary};
                border-radius: 18px;
                color: {c.text_primary};
                padding: 0 16px;
                font-size: 11.25pt;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background-color: {c.bg_secondary};
                color: {c.text_primary};
                selection-background-color: {c.accent};
            }}
        """)

    def _apply_icon(self, button, resource_path: str):
        button.setIcon(theme_icon(resource_path, self._c.text_primary))

    def _retheme(self):
        self._c = ColorThemeManager.instance().colors
        c = self._c
        self._scroll.setStyleSheet(f"background-color: {c.bg_primary}; border: none;")
        if self._logo.pixmap() is None or self._logo.pixmap().isNull():
            self._logo.setStyleSheet(f"background-color: {c.bg_secondary}; border-radius: 14px;")
        self._title.setStyleSheet(t("home_title"))
        self.subtitle.setStyleSheet(t("home_subtitle"))
        self._style_device_combo()
        self._refresh_btn.setStyleSheet(t("home_icon_button"))
        self._apply_icon(self._refresh_btn, ":/icon/arrow-clockwise.svg")
        self._logs_btn.setStyleSheet(t("home_icon_button"))
        self._apply_icon(self._logs_btn, ":/icon/file-earmark-text.svg")
        self._settings_btn.setStyleSheet(t("home_icon_button"))
        self._apply_icon(self._settings_btn, ":/icon/gear.svg")
        self.storage_title.setStyleSheet(t("home_tile_title"))
        self.storage_lbl.setStyleSheet(t("home_tile_subtitle"))
        self.storage_bar.setStyleSheet(f"""
            QProgressBar {{ background: {c.bg_input}; border: none; border-radius: 4px; }}
            QProgressBar::chunk {{ background: {c.accent}; border-radius: 4px; }}
        """)
        self.process_status_lbl.setStyleSheet(t("process_status_green"))
        self.update_status()
        # Feature tiles: recolor the icon and restyle the two labels
        for icon_lbl, icon_res, title_lbl, sub_lbl in self._tiles:
            self._paint_tile_icon(icon_lbl, icon_res)
            title_lbl.setStyleSheet(t("home_tile_title"))
            sub_lbl.setStyleSheet(t("home_tile_subtitle"))

    def populate_device_picker(self):
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        try:
            devices = self.window.device_manager.devices
            if devices:
                for device in devices:
                    tag = " (@ USB)" if device.connected_via_usb else " (@ WiFi)"
                    self.device_combo.addItem(f"{device.name}{tag}")
            else:
                self.device_combo.addItem(QCoreApplication.translate("QCoreApplication", "No Device"))
        except Exception:
            self.device_combo.addItem(QCoreApplication.translate("QCoreApplication", "No Device"))
        self.device_combo.blockSignals(False)

    @Slot()
    def on_device_changed(self, index):
        if len(self.window.device_manager.devices) > 0 and index >= 0:
            self.window.change_selected_device(index)
            self.update_device_info()
            self.update_status()

    @Slot()
    def refresh_devices(self):
        self.window.refresh_devices()

    @Slot()
    def open_settings(self):
        self.window.show_ios_page(4)

    @Slot()
    def open_logs(self):
        """Open the session-log viewer over the main window."""
        from src.gui.dialogs.log_viewer import LogViewerDialog
        dialog = LogViewerDialog(self.window)
        dialog.exec()

    def open_presets_section(self):
        self.window.open_presets_section()

    def switch_to_ios_page(self, index: int):
        self.window.show_ios_page(index)

    def open_apply_classic(self):
        self.window.apply_changes()

    def reset_tweaks(self):
        from src.gui.dialogs.reset_dialog import ResetDialog
        dialog = ResetDialog(device_manager=self.window.device_manager, apply_reset=self.window.apply_changes)
        dialog.exec()

    def show_process_status(self, text: str, success: bool = None):
        c = self._c
        if success is True:
            color = c.success
        elif success is False:
            color = c.error
        else:
            color = c.accent
        self.process_status_lbl.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {color};")
        self.process_status_lbl.setText(text)
        self.process_status_lbl.show()
        self._hide_timer.start(6000)

    def hide_process_status(self):
        self.process_status_lbl.hide()

    def update_status(self):
        c = self._c
        try:
            if self.window.device_manager.get_current_device_udid():
                if not self.window.device_manager.get_current_device_is_supported_by_fork():
                    # the fork only supports iOS 26.2+; anything older cannot
                    # be tweaked, so never show it as supported
                    status_text = QCoreApplication.translate(
                        "QCoreApplication", "Not Supported.")
                    color = c.error
                elif self.window.device_manager.get_current_device_partially_supported():
                    status_text = QCoreApplication.translate("Nugget", "Partially Supported")
                    color = c.warning
                else:
                    status_text = QCoreApplication.translate("QCoreApplication", "Supported!")
                    color = c.success
            else:
                status_text = QCoreApplication.translate("Nugget", "Not connected")
                color = c.text_primary
        except AttributeError:
            status_text = QCoreApplication.translate("Nugget", "Not connected")
            color = c.text_primary
        self.status_lbl.setText(f"<span style='color:{color};'>{status_text}</span>")

    def update_device_info(self):
        try:
            ver = self.window.device_manager.get_current_device_version() or "—"
            build = self.window.device_manager.get_current_device_build() or "—"
            self.subtitle.setText(QCoreApplication.translate("Nugget", "iPhone (iOS {0} {1})").format(ver, build))
        except AttributeError:
            self.subtitle.setText(QCoreApplication.translate("Nugget", "iPhone (iOS —)"))
        self._refresh_storage()

    def _refresh_storage(self):
        if self._storage_thread is not None and self._storage_thread.isRunning():
            return
        udid = self.window.device_manager.get_current_device_udid()
        if not udid:
            self.storage_bar.setValue(0)
            self.storage_lbl.setText(QCoreApplication.translate(
                "Nugget", "Connect an iPhone to view storage"))
            return
        self.storage_lbl.setText(QCoreApplication.translate("Nugget", "Loading storage…"))
        self._storage_thread = _StorageThread(udid, self)
        self._storage_thread.result.connect(self._on_storage_result)
        self._storage_thread.start()

    @Slot(object, object)
    def _on_storage_result(self, total, free):
        current_udid = self.window.device_manager.get_current_device_udid()
        sender = self.sender()
        if sender is not self._storage_thread or getattr(sender, "udid", None) != current_udid:
            QTimer.singleShot(0, self._refresh_storage)
            return
        if not total or free is None or total <= 0:
            self.storage_bar.setValue(0)
            self.storage_lbl.setText(QCoreApplication.translate(
                "Nugget", "Storage information unavailable"))
            return
        used = max(0, total - free)
        percent = min(100, round(used * 100 / total))
        self.storage_bar.setValue(percent)
        self.storage_lbl.setText(QCoreApplication.translate(
            "Nugget", "Used {0} GB · Free {1} GB").format(
                self._format_gb(used), self._format_gb(free)))

    @staticmethod
    def _format_gb(value):
        return f"{value / (1024 ** 3):.1f}"

    def refresh_device_combo(self):
        self.populate_device_picker()

    def refresh_preset_widget(self):
        self.preset_widget.refresh()

    def set_statusbar_visible(self, visible: bool):
        self.statusbar_card.setVisible(visible)
        self.cards_grid.reflow()

    def _make_card(self, title: str, subtitle: str, page_index: int) -> IOSCard:
        """One home feature tile: a big themed icon with the name below it."""
        card = _TileCard()
        card.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 20, 10, 16)
        card_layout.setSpacing(12)
        card_layout.setAlignment(Qt.AlignHCenter)

        icon_res = _FEATURE_ICONS.get(title, ":/icon/compass.svg")
        icon_lbl = QLabel(card)
        icon_lbl.setFixedSize(self.TILE_ICON_PX, self.TILE_ICON_PX)
        icon_lbl.setAlignment(Qt.AlignCenter)
        # transparent, so the label never paints the palette window color over
        # the tile (see the home_tile_* styles)
        icon_lbl.setStyleSheet("background-color: transparent;")
        self._paint_tile_icon(icon_lbl, icon_res)
        card_layout.addWidget(icon_lbl, 0, Qt.AlignHCenter)

        title_lbl = QLabel(QCoreApplication.translate("Nugget", title), card)
        title_lbl.setWordWrap(True)
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setStyleSheet(t("home_tile_title"))
        card_layout.addWidget(title_lbl, 0, Qt.AlignHCenter)

        sub_lbl = QLabel(QCoreApplication.translate("Nugget", subtitle), card)
        sub_lbl.setWordWrap(True)
        sub_lbl.setAlignment(Qt.AlignCenter)
        sub_lbl.setStyleSheet(t("home_tile_subtitle"))
        card_layout.addWidget(sub_lbl, 0, Qt.AlignHCenter)

        card_layout.addStretch(1)

        # kept for _retheme(): icons are recolored, labels restyled
        self._tiles.append((icon_lbl, icon_res, title_lbl, sub_lbl))

        card.mousePressEvent = lambda e: self.switch_to_ios_page(page_index)
        card.setCursor(Qt.PointingHandCursor)
        card.setToolTip(QCoreApplication.translate("Nugget", subtitle))
        return card

    def _paint_tile_icon(self, label: QLabel, icon_res: str):
        """Draw a feature icon at tile size (and screen density) in the
        current text color."""
        label.setPixmap(theme_pixmap(
            icon_res, self._c.text_primary, self.TILE_ICON_PX,
            self.devicePixelRatioF()))
