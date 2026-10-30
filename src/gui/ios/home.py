import time
from PySide6.QtCore import (
    Qt, QCoreApplication, QT_TRANSLATE_NOOP, Slot, QTimer, QSize, QEvent, Signal, QThread,
)
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QSizePolicy, QScrollArea, QTabWidget, QBoxLayout
)

from src.gui.widgets import (
    IOSCard, IOSPrimaryButton,
)
from src.gui.theme import t, ColorThemeManager, theme_icon, theme_pixmap

from src.gui.ios.feature_icons import FEATURE_ICONS
from src.gui.ios.nugget_logo import NuggetLogo
from src.devicemanagement.device_capabilities import device_os_name
from src.devicemanagement.constants import normalize_udid
from src.devicemanagement.storage_info import format_device_capacity
from src.devicemanagement.passcode_support import current_passcode_theme_reason


class _StorageThread(QThread):
    result = Signal(object, object, object)
    capacity_ready = Signal(object)

    def __init__(self, udid, parent=None):
        super().__init__(parent)
        self.udid = udid

    def run(self):
        import asyncio
        asyncio.run(self._query())

    async def _query(self):
        import asyncio
        import logging
        from src.devicemanagement.session import lockdown_session
        from pymobiledevice3.services.afc import AfcService
        from pymobiledevice3.services.diagnostics import DiagnosticsService

        async def storage():
            try:
                async with lockdown_session(self.udid, autopair=False, connection_type="USB") as lockdown:
                    try:
                        disk = await lockdown.get_value(domain="com.apple.disk_usage")
                        capacity = self._first_number(disk, "TotalDiskCapacity")
                        if capacity and capacity > 1_000_000_000:
                            self.capacity_ready.emit(capacity)
                    except Exception:
                        logging.getLogger('GoldenNugget.device_preview').debug('Hardware capacity unavailable', exc_info=True)
                    async with AfcService(lockdown) as afc:
                        info = await afc.get_device_info()
                    total = self._first_number(info, "FSTotalBytes", "TotalBytes")
                    free = self._first_number(info, "FSFreeBytes", "FreeBytes")
                    self.result.emit(total, free, None)
            except Exception:
                logging.getLogger('GoldenNugget.device_preview').debug('Storage query unavailable for %s', self.udid, exc_info=True)

        async def battery():
            try:
                async with lockdown_session(self.udid, autopair=False, connection_type="USB") as lockdown:
                    async with DiagnosticsService(lockdown) as diagnostics:
                        report = await diagnostics.get_battery()
                    if not isinstance(report, dict):
                        return
                    percent = self._first_number(report, "CurrentCapacity", "BatteryCurrentCapacity")
                    if percent is None:
                        return
                    charging = report.get("IsCharging", False)
                    if isinstance(charging, str):
                        charging = charging.casefold() in ("1", "true", "yes")
                    self.result.emit(None, None, {
                        "percent": percent, "charging": bool(charging),
                        "low_power": report.get("LowPowerModeEnabled") if isinstance(report.get("LowPowerModeEnabled"), bool) else None})
            except Exception:
                logging.getLogger('GoldenNugget.device_preview').debug('Battery query unavailable for %s', self.udid, exc_info=True)

        await asyncio.gather(asyncio.wait_for(storage(), 4), asyncio.wait_for(battery(), 4), return_exceptions=True)

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
    """A home feature tile with a stationary hover outline."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)

    def showEvent(self,event):
        for label in self.findChildren(QLabel):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
        super().showEvent(event)

    def _retheme(self):
        self.setStyleSheet(t("home_tile"))


class _CardGrid(QWidget):
    """Keep visible home tiles in their final row, including before first show."""
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
            if etype == QEvent.Hide and obj.isHidden():
                self._hidden.add(obj)
                self._reflow()
            elif etype == QEvent.Show:
                self._hidden.discard(obj)
                self._reflow()
        return super().eventFilter(obj, event)

    def reflow(self):
        self._reflow()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self):
        include = [c for c in self._cards if c not in self._hidden]
        self.setMinimumWidth(self.MIN_CARD_WIDTH)
        target = []
        if include:
            fit = min(len(include), self.MAX_COLUMNS, max(1, (self.width() + self.SPACING) // (self.MIN_CARD_WIDTH + self.SPACING)))
            rows = (len(include) + fit - 1) // fit
            cols = (len(include) + rows - 1) // rows
            for i, card in enumerate(include):
                target.append((i // cols, i % cols, card))
        key = tuple((r, c, id(w)) for r, c, w in target)
        if key == self._layout_key:
            return
        for card in self._cards:
            self._grid.removeWidget(card)
        for col in range(self.MAX_COLUMNS):
            self._grid.setColumnStretch(col, 1 if include and col < cols else 0)
        for r, c, w in target:
            self._grid.addWidget(w, r, c, Qt.AlignHCenter)
        self._layout_key = key


class DeviceSelector(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentIndexChanged.connect(self.update_visible_devices)

    def update_visible_devices(self, *_args):
        current = self.currentIndex()
        has_alternative = any(isinstance(self.itemData(row, Qt.UserRole), int)
                              and row != current for row in range(self.count()))
        for row in range(self.count()):
            selected_device = row == current and isinstance(self.itemData(row, Qt.UserRole), int)
            leading_separator = not has_alternative and self.itemData(row, Qt.AccessibleDescriptionRole) == "separator"
            self.view().setRowHidden(row, selected_device or leading_separator)

    def showPopup(self):
        self.update_visible_devices()
        super().showPopup()

    def hidePopup(self):
        super().hidePopup()
        self.update_visible_devices()


class IOSHomePage(QWidget):
    selection_counts_requested = Signal()
    # Feature tile: a big icon over the name. The tile height is left to the
    # layout so a subtitle that wraps to two lines grows the whole row.
    TILE_ICON_PX = 92

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
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._scroll = scroll
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 6, 16, 98)
        layout.setSpacing(12)

        # Logo + Title row
        self._header_layout = header = QHBoxLayout()
        header.setSpacing(20)
        self._branding = branding = QWidget(content)
        branding_layout = QVBoxLayout(branding)
        branding_row = QHBoxLayout()
        branding_row.setSpacing(12)
        branding_layout.addLayout(branding_row)
        branding_layout.setContentsMargins(0, 0, 0, 0)
        branding_layout.setSpacing(8)
        branding.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        header.addWidget(branding, 0, Qt.AlignTop)

        self._logo = NuggetLogo(self)
        branding_row.addWidget(self._logo, 0, Qt.AlignTop)

        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(8)
        title_layout.setAlignment(Qt.AlignTop)
        self._title = QLabel(QCoreApplication.translate("Nugget", "GoldenNugget"), self)
        self._title.setStyleSheet(t("home_title"))
        self._title.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        title_layout.addWidget(self._title)

        self.subtitle = QLabel(QCoreApplication.translate("Nugget", "No device connected"), self)
        self.subtitle.setStyleSheet(t("home_subtitle"))
        self.subtitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.subtitle.setTextFormat(Qt.PlainText)
        title_layout.addWidget(self.subtitle)
        self._update_available = None
        self.update_notice = QWidget(branding)
        notice_row = QHBoxLayout(self.update_notice)
        notice_row.setContentsMargins(0, 0, 0, 0)
        notice_row.setSpacing(4)
        self.outdated_lbl = QLabel(self.tr("Outdated version"), self.update_notice)
        self.update_info_btn = QPushButton("ⓘ", self.update_notice)
        self.update_info_btn.setFixedSize(24, 24)
        self.update_info_btn.setCursor(Qt.PointingHandCursor)
        self.update_info_btn.setAccessibleName(self.tr("About this outdated version and updates"))
        self.update_info_btn.setToolTip(self.tr("You're on an outdated version of Nugget. View update options."))
        self.update_info_btn.clicked.connect(self._show_update_info)
        notice_row.addWidget(self.outdated_lbl)
        notice_row.addWidget(self.update_info_btn)
        notice_row.addStretch()
        self.update_notice.hide()
        title_layout.addWidget(self.update_notice)
        branding_row.addLayout(title_layout, 1)

        self.control_tabs = QTabWidget(self)
        self.control_tabs.setDocumentMode(True)
        self.control_tabs.tabBar().setUsesScrollButtons(False)
        self.control_tabs.tabBar().setDrawBase(False)
        self.control_tabs.setFixedSize(500, 174)

        devices_page = QWidget(self.control_tabs)
        self._device_summary_page = devices_page
        devices_row = QHBoxLayout(devices_page)
        devices_row.setContentsMargins(10, 0, 12, 0)
        devices_row.setSpacing(10)
        from src.gui.ios.device_preview import DevicePreview
        self._device_preview = DevicePreview(self.window, devices_page, scale=1.25)
        devices_row.addWidget(self._device_preview)
        devices_layout = QVBoxLayout()
        devices_row.addLayout(devices_layout, 1)
        devices_layout.setContentsMargins(0, 0, 0, 0)
        devices_layout.setSpacing(8)
        devices_layout.setAlignment(Qt.AlignVCenter)
        self.device_combo = DeviceSelector(devices_page)
        self.device_combo.setFixedHeight(38)
        self.device_combo.setMinimumWidth(260)
        self.device_combo.setMaximumWidth(440)
        selector_row = QHBoxLayout()
        selector_row.setSpacing(10)
        self.device_name = QLabel(devices_page)
        self.device_name.setWordWrap(True)
        self.device_software = QLabel(devices_page)
        self.device_software.setWordWrap(True)
        devices_layout.addWidget(self.device_name)
        title_layout.insertWidget(2, self.device_combo)
        devices_layout.addWidget(self.device_software)
        self.device_connection = QLabel(devices_page)
        self.device_connection.setWordWrap(True)
        devices_layout.addWidget(self.device_connection)
        self._devices_page = QWidget(self.control_tabs)
        picker_layout = QHBoxLayout(self._devices_page)
        picker_layout.setContentsMargins(10, 0, 10, 0)
        picker_layout.setSpacing(14)
        self._picker_preview = DevicePreview(self.window, self._devices_page)
        picker_layout.addWidget(self._picker_preview)
        picker_info = QVBoxLayout()
        picker_info.setSpacing(8)
        self.picker_combo = DeviceSelector(self._devices_page)
        self.picker_combo.setModel(self.device_combo.model())
        self.picker_combo.setMinimumWidth(260)
        self.picker_combo.setMinimumHeight(38)
        self.picker_combo.setStyleSheet(self.device_combo.styleSheet())
        self.picker_combo.currentIndexChanged.connect(self._on_picker_device_changed)
        picker_info.addWidget(self.picker_combo)
        self.picker_software = QLabel(self._devices_page)
        self.picker_software.setWordWrap(True)
        picker_info.addWidget(self.picker_software)
        from src.gui.ios.device_details import DeviceDetailsWidget
        self.picker_details = DeviceDetailsWidget(self.window, self._devices_page)
        picker_info.addWidget(self.picker_details)
        picker_layout.addLayout(picker_info, 1)
        self.control_tabs.addTab(self._devices_page, self.tr("Device selection"))
        self.status_lbl = QLabel("", devices_page)
        self.status_lbl.setTextFormat(Qt.RichText)
        self.status_lbl.setOpenExternalLinks(False)
        self.status_lbl.setWordWrap(False)
        self.status_lbl.setStyleSheet("font-size: 13px; font-weight: 600;")
        self.status_lbl.linkActivated.connect(self._show_device_support)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addWidget(self.status_lbl)
        status_row.addStretch()
        devices_layout.addLayout(status_row)
        self.control_tabs.addTab(devices_page, QCoreApplication.translate("Nugget", "Devices"))
        presets_page = QWidget(self.control_tabs)
        self._presets_page = presets_page
        presets_layout = QHBoxLayout(presets_page)
        presets_layout.setContentsMargins(10, 6, 10, 6)
        presets_layout.setSpacing(12)
        self.presets_card = QWidget(presets_page)
        preset_content = QHBoxLayout(self.presets_card)
        preset_content.setContentsMargins(12, 4, 12, 4)
        preset_content.setSpacing(10)
        self.presets_icon = QLabel(self.presets_card)
        self.presets_icon.setPixmap(theme_pixmap(":/icon/folder.svg", self._c.accent, 26))
        self.presets_icon.setFixedSize(26, 26)
        preset_content.addWidget(self.presets_icon)
        preset_text = QVBoxLayout()
        preset_text.setContentsMargins(0, 0, 0, 0)
        preset_text.setSpacing(3)
        self.presets_title = QLabel(QCoreApplication.translate("Nugget", "PRESET"))
        self.presets_title.setStyleSheet(t("home_tile_title"))
        preset_text.addWidget(self.presets_title)
        self.presets_lbl = QLabel(QCoreApplication.translate("Nugget", "Manage presets"))
        self.presets_lbl.setStyleSheet(t("home_tile_subtitle"))
        self.presets_lbl.setWordWrap(False)
        preset_text.addWidget(self.presets_lbl)
        preset_content.addLayout(preset_text)
        self.manage_presets_btn = QPushButton(
            QCoreApplication.translate("Nugget", "Manage"), self.presets_card)
        self.manage_presets_btn.setFixedHeight(36)
        self.manage_presets_btn.setCursor(Qt.PointingHandCursor)
        self._style_manage_presets_button()
        self.manage_presets_btn.clicked.connect(self.open_presets_section)
        preset_content.addSpacing(6)
        preset_content.addWidget(self.manage_presets_btn)
        preset_content.addStretch(1)
        presets_layout.addWidget(self.presets_card, 1)
        self._build_control_tabs()

        self._style_control_tabs()
        self.control_tabs.tabBar().hide()

        self._device_area = QWidget(content)
        self._device_area_layout = QBoxLayout(QBoxLayout.LeftToRight, self._device_area)
        self._device_area_layout.setContentsMargins(0, 0, 0, 0)
        self._device_area_layout.setSpacing(16)
        self._device_area_layout.addWidget(self.control_tabs, 0, Qt.AlignTop | Qt.AlignLeft)
        from src.gui.ios.support_panel import CommunityLinks
        self.community_links = CommunityLinks(self._device_area)
        self._device_area_layout.addWidget(self.community_links, 1, Qt.AlignTop | Qt.AlignLeft)
        header.addWidget(self._device_area, 1, Qt.AlignTop)
        layout.addLayout(header)
        self._scroll.viewport().installEventFilter(self)
        QTimer.singleShot(0, self._fit_header)
        self.connection_notice = QLabel(self)
        self.connection_notice.setWordWrap(True)
        self.connection_notice.setTextFormat(Qt.PlainText)
        self.connection_notice.setStyleSheet(t("home_subtitle"))
        self.connection_notice.hide()
        layout.addWidget(self.connection_notice)
        from src.gui.ios.device_details import DeviceDetailsWidget
        self.device_details = DeviceDetailsWidget(self.window, devices_page)
        self.device_details.selection_counts_changed.connect(self.community_links.set_counts)
        self.window.ios_pages.currentChanged.connect(self._refresh_home_counts)
        self.device_details.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        devices_layout.addWidget(self.device_details)
        selector_row.addStretch()

        self._style_device_combo()
        self.populate_device_picker()
        self.device_combo.currentIndexChanged.connect(self.on_device_changed)

        self._storage_thread = None
        self._storage_workers = {}
        self._device_info_cache = {}
        self._device_info_stopping = False
        self.control_tabs.currentChanged.connect(self._on_control_tab_changed)

        cards_row = [self._make_card(
            "PosterBoard", QT_TRANSLATE_NOOP("Nugget", "Animated wallpapers & video"), 2),
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
        (self.posterboard_card, _, self.daemons_card,
         self.statusbar_card, _, self.passcode_theme_card) = cards_row
        self.cards_grid = _CardGrid(cards_row)
        layout.addWidget(self.cards_grid)
        # GoldenNugget Mobile opens a dialog, not a page — it gets the compact
        # one-line row the Catalog uses, so the tile grid stays 6-wide.
        self.mobile_row = self._make_mobile_row()
        layout.addWidget(self.mobile_row)
        # Keep the catalog as a compact row below the feature tiles.
        self.catalog_card = self._make_catalog_row()
        layout.addWidget(self.catalog_card)

        # Apply / Reset share one row on the home screen.
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(12)

        self.apply_btn = apply_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Apply Tweaks"))
        apply_btn.clicked.connect(self.open_apply_classic)
        actions.addWidget(apply_btn, 1)

        layout.addLayout(actions)

        from src.gui.ios.restore_progress import RestoreProgressCard
        self.progress_card = RestoreProgressCard(self, compact=True)
        layout.addWidget(self.progress_card)
        self.operation_status_btn = IOSPrimaryButton(self.tr("Restore Status"))
        self.operation_status_btn.clicked.connect(self.open_apply_classic)
        self.operation_status_btn.hide()
        layout.addWidget(self.operation_status_btn)
        from src.gui.ios.find_my_warning import FindMyWarningCard
        self.find_my_warning = FindMyWarningCard(self.window, self)
        layout.addWidget(self.find_my_warning)
        self._progress_busy = False
        self.process_status_lbl = QLabel("", self)
        self.process_status_lbl.setWordWrap(True)
        self.process_status_lbl.setAlignment(Qt.AlignCenter)
        self.process_status_lbl.setStyleSheet(t("process_status_green"))
        self.process_status_lbl.hide()
        layout.addWidget(self.process_status_lbl)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_process_status)
        from src.controllers.feature_news import FeatureNews
        FeatureNews.instance()

        from src.gui.ios.operation_result import OperationResultCard
        self.result_card = OperationResultCard(self.open_logs, self.window.dismiss_operation_result)
        layout.addWidget(self.result_card)

        from src.gui.ios.support_panel import SupportPanel
        self.support_panel = SupportPanel(self, links=self.community_links)
        layout.addWidget(self.support_panel)
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
                border: 1px solid {c.accent};
                border-radius: 12px;
                color: {c.text_primary};
                padding: 0 10px;
                font-size: 15px;
            }}
            QComboBox::drop-down {{
                width: 24px;
                border: none;
                subcontrol-origin: padding;
                subcontrol-position: top right;
            }}
            QComboBox::down-arrow {{
                image: url(:/icon/caret-down-fill.svg);
                width: 10px;
                height: 10px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {c.bg_secondary};
                color: {c.text_primary};
                selection-background-color: {c.accent};
            }}
        """)

    def _style_control_tabs(self):
        c = self._c
        self.control_tabs.setStyleSheet(f"""
            QTabWidget::tab-bar {{
                alignment: center;
            }}
            QTabWidget::pane {{
                background: {c.bg_secondary};
                border: 1px solid {c.border};
                border-radius: 22px;
                top: -1px;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {c.text_secondary};
                border: 1px solid transparent;
                border-radius: 7px;
                padding: 5px 6px;
                margin: 3px 1px;
                font-size: 12px;
                font-weight: 600;
            }}
            QTabBar::tab:selected {{
                background: {c.bg_tertiary};
                color: {c.text_primary};
                border-color: {c.border};
            }}
            QTabBar::tab:hover:!selected {{
                background: {c.surface_hover};
                color: {c.text_primary};
            }}
        """)

    def _style_manage_presets_button(self):
        c = self._c
        self.manage_presets_btn.setStyleSheet(f"""
            QPushButton {{
                background: {c.accent};
                color: {c.text_inverse};
                border: none;
                border-radius: 8px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton:hover {{ background: {c.accent_hover}; }}
            QPushButton:pressed {{ background: {c.accent}; }}
        """)

    def _retheme(self):
        self._c = ColorThemeManager.instance().colors
        c = self._c
        self._scroll.setStyleSheet(f"background-color: {c.bg_primary}; border: none;")
        if self._logo.pixmap() is None or self._logo.pixmap().isNull():
            self._logo.setStyleSheet(f"background-color: {c.bg_secondary}; border-radius: 14px;")
        self._title.setStyleSheet(t("home_title"))
        self.subtitle.setStyleSheet(t("home_subtitle"))
        self.community_links._retheme()
        self._style_control_tabs()
        self._style_device_combo()
        self._update_control_icons()
        self.presets_title.setStyleSheet(t("home_tile_title"))
        self.presets_lbl.setStyleSheet(t("home_tile_subtitle"))
        self.presets_icon.setPixmap(theme_pixmap(":/icon/folder.svg", c.accent, 26))
        self._style_manage_presets_button()
        self.process_status_lbl.setStyleSheet(t("process_status_green"))
        self.update_status()
        # Feature tiles: recolor the icon and restyle the two labels
        for icon_lbl, icon_res, title_lbl, sub_lbl in self._tiles:
            self._paint_tile_icon(icon_lbl, icon_res)
            title_lbl.setStyleSheet(t("home_tile_title"))
            sub_lbl.setStyleSheet(t("home_tile_subtitle"))
        self.device_name.setStyleSheet(f"color:{c.text_primary}; font-size:16px; font-weight:600; background:transparent;")
        self.device_software.setStyleSheet(f"color:{c.text_secondary}; font-size:12px; background:transparent;")
        self.device_connection.setStyleSheet(self.device_software.styleSheet())
        self.picker_software.setStyleSheet(self.device_software.styleSheet())
        self.picker_combo.setStyleSheet(self.device_combo.styleSheet())
        self._paint_catalog_row()
        self._paint_mobile_row()
        self.update_passcode_support()

    def _device_picker_label(self, device):
        from pymobiledevice3.irecv_devices import IRECV_DEVICES
        model = getattr(device, "model", "")
        model_name = next((item.display_name for item in IRECV_DEVICES
                           if item.product_type == model), model)
        info = getattr(self, "_device_info_cache", {}).get(device.udid, {})
        capacity = format_device_capacity(info.get("capacity"))
        details = " · ".join(part for part in (model_name, capacity) if part)
        return f"{device.name} ({details})"

    def _update_picker_labels(self):
        devices = {device.udid: device for device in self.window.device_manager.devices}
        for row in range(self.device_combo.count()):
            device = devices.get(self.device_combo.itemData(row, Qt.UserRole + 1))
            if device is not None:
                label = self._device_picker_label(device)
                self.device_combo.setItemText(row, label)
                self.device_combo.setItemData(row, label, Qt.ToolTipRole)
        for combo in (self.device_combo, self.picker_combo):
            combo.view().setMinimumWidth(max(combo.width(), combo.view().sizeHintForColumn(0) + 64))

    def _refresh_picker_storage(self):
        if (self._device_info_stopping or getattr(self.window, "apply_in_progress", False)
                or getattr(self.window, "_cache_restore_in_progress", False)):
            return
        for row in range(self.device_combo.count()):
            udid = self.device_combo.itemData(row, Qt.UserRole + 1)
            if not udid or udid in self._storage_workers:
                continue
            cached = self._device_info_cache.get(udid, {})
            if time.monotonic() - cached.get("checked", 0) < 15:
                continue
            worker = _StorageThread(udid, self)
            self._storage_workers[udid] = worker
            worker.result.connect(self._on_storage_result)
            worker.capacity_ready.connect(self._on_capacity_result)
            worker.finished.connect(self._on_storage_finished)
            worker.start()

    def populate_device_picker(self):
        self.picker_combo.blockSignals(True)
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        usb_devices = []
        try:
            devices = list(self.window.device_manager.devices)
            connected = getattr(self.window, "_connected_usb_udids", None)
            connected = {normalize_udid(udid) for udid in connected} if connected is not None else None
            selected_udid = normalize_udid(self.window.device_manager.get_current_device_udid())
            usb_devices = [
                (index, device) for index, device in enumerate(devices)
                if device.connected_via_usb and (
                    connected is None or normalize_udid(device.udid) in connected)
            ]
            if usb_devices:
                for device_index, device in usb_devices:
                    label = self._device_picker_label(device)
                    self.device_combo.addItem(label)
                    self.device_combo.setItemData(
                        self.device_combo.count() - 1, device_index, Qt.UserRole)
                    self.device_combo.setItemData(
                        self.device_combo.count() - 1, device.udid, Qt.UserRole + 1)
                selected = next(
                    (position for position, (_, device) in enumerate(usb_devices)
                     if normalize_udid(device.udid) == selected_udid),
                    0)
                self.device_combo.setCurrentIndex(selected)
            else:
                self.device_combo.addItem(QCoreApplication.translate("QCoreApplication", "No Device"))
        except Exception:
            self.device_combo.addItem(QCoreApplication.translate("QCoreApplication", "No Device"))
            usb_devices = []
        self.picker_combo.setCurrentIndex(self.device_combo.currentIndex())
        self.picker_combo.blockSignals(False)
        self.picker_combo.update_visible_devices()
        self.device_combo.blockSignals(False)
        self.device_combo.update_visible_devices()
        self.device_combo.view().setMinimumWidth(max(
            self.device_combo.width(), self.device_combo.view().sizeHintForColumn(0) + 64))
        QTimer.singleShot(0, self._refresh_picker_storage)

    def _on_picker_device_changed(self, index):
        self.device_combo.blockSignals(True)
        self.device_combo.setCurrentIndex(index)
        self.device_combo.blockSignals(False)
        self.on_device_changed(index)

    @Slot()
    def on_device_changed(self, index):
        if getattr(self, '_support_dialog', None) is not None:
            self._support_dialog.close()
        device_index = self.device_combo.itemData(index, Qt.UserRole)
        if isinstance(device_index, int):
            self.picker_combo.blockSignals(True)
            self.picker_combo.setCurrentIndex(index)
            self.picker_combo.blockSignals(False)
            self.picker_combo.update_visible_devices()
            udid = self.device_combo.itemData(index, Qt.UserRole + 1)
            self.window._preferred_device_udid = udid
            selected = next((position for position, device in enumerate(self.window.device_manager.devices)
                             if device.udid == udid), None)
            if selected is not None:
                self.window.change_selected_device(selected)

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
        self.window.bottom_navigation.navigate(index)

    def open_apply_classic(self):
        """Open the dedicated Apply page before starting an operation."""
        self.window.show_ios_page(6)
        self.window._sync_sidebar_selection()

    def reset_tweaks(self):
        from src.gui.dialogs.reset_dialog import ResetDialog
        dialog = ResetDialog(device_manager=self.window.device_manager, apply_reset=self.window.apply_changes)
        dialog.exec()

    def set_operation_busy(self, busy):
        if busy:
            self.operation_status_btn.show()
        if busy and not self._progress_busy:
            manager = self.window.device_manager
            preferences = manager.pref_manager
            self.progress_card.start(manager.get_current_device_partially_supported(),
                                     preferences.auto_reboot or preferences.skip_setup,
                                     manager.get_current_device_model())
            self.process_status_lbl.hide()
        self._progress_busy = busy
        self.find_my_warning.set_busy(busy)
        self.progress_card.setVisible(busy)

    def show_process_status(self, text: str, success: bool = None):
        if self._progress_busy and success is None:
            self.progress_card.set_status(text)
            self.process_status_lbl.hide()
            return
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
        self._hide_timer.stop()
        if success is not False and not getattr(self.window, "apply_in_progress", False):
            self._hide_timer.start(6000)

    def hide_process_status(self):
        self.process_status_lbl.hide()

    def set_update_available(self, available):
        self._update_available = available
        self.update_notice.setVisible(available is not None)
        self.outdated_lbl.setText(self.tr("Outdated version") if available else self.tr("Up to date!"))
        self.update_info_btn.setVisible(available is True)
        self.update_status()

    def _show_update_info(self):
        from src.gui.dialogs.update_dialog import UpdateDialog
        dialog = UpdateDialog(self.window)
        dialog.exec()
        dialog.deleteLater()

    def update_status(self):
        c = self._c
        update_color = c.success if self._update_available is False else c.error
        self.outdated_lbl.setStyleSheet(f"color: {update_color}; font-size: 13px; font-weight: 600;")
        self.update_info_btn.setStyleSheet(f"QPushButton {{ color: {c.error}; background: transparent; border: none; font-size: 17px; }} QPushButton:hover {{ background: {c.bg_tertiary}; border-radius: 6px; }}")
        try:
            if self.window.device_manager.get_current_device_udid():
                if not self.window.device_manager.get_current_device_is_supported_by_fork():
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
                status_text = ""
                color = c.text_primary
        except AttributeError:
            status_text = ""
            color = c.text_primary
        self.status_lbl.setVisible(bool(status_text))
        if status_text:
            self.status_lbl.setText(
                f"<a href='support' style='color:{color}; text-decoration:none;'>"
                f"{status_text}  ⓘ</a>")
            self.status_lbl.setToolTip(QCoreApplication.translate(
                "Nugget", "View device compatibility and safety restrictions."))
        else:
            self.status_lbl.setText(f"<span style='color:{color};'>{status_text}</span>")
            self.status_lbl.setToolTip("")
        self.status_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: 600; padding-left: 2px; color: {color};")

    def _show_device_support(self, _link=None):
        if not self.window.device_manager.get_current_device_udid():
            return
        from src.gui.dialogs.device_support import DeviceSupportDialog
        previous = getattr(self, '_support_dialog', None)
        if previous is not None:
            previous.raise_()
            previous.activateWindow()
            return
        dialog = DeviceSupportDialog(self.window.device_manager, self.window)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        self._support_dialog = dialog
        dialog.finished.connect(lambda: setattr(self, '_support_dialog', None))
        dialog.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_header()

    def eventFilter(self, obj, event):
        if obj is self._scroll.viewport() and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._fit_header)
        return super().eventFilter(obj, event)

    def _fit_header(self):
        if not hasattr(self, "community_links"):
            return
        available = max(1, self._scroll.viewport().width() - 32)
        branding = self._branding.minimumSizeHint().width()
        phone = getattr(self, "_control_preferred_width", 360)
        cards = self.community_links.minimumWidth()
        stacked_header = available < branding + phone + 20
        self._header_layout.setDirection(QBoxLayout.TopToBottom if stacked_header else QBoxLayout.LeftToRight)
        right_width = available if stacked_header else available - branding - 20
        side_by_side = right_width >= phone + cards + 16
        self._device_area_layout.setDirection(QBoxLayout.LeftToRight if side_by_side else QBoxLayout.TopToBottom)
        self.control_tabs.setFixedWidth(min(phone, right_width))

    def _refresh_home_counts(self, index):
        if index == 0:
            self.device_details._update_selection_counts()

    def update_device_info(self):
        manager = self.window.device_manager
        connected = bool(manager.get_current_device_udid())
        self.device_name.setText(self.device_combo.currentText() if connected else self.tr("No device connected"))
        self.device_name.setToolTip(self.device_combo.currentText() if connected else "")
        self._picker_preview.set_device(manager.get_current_device_udid(), manager.get_current_device_model())
        self._device_preview.set_device(
            self.window.device_manager.get_current_device_udid(),
            self.window.device_manager.get_current_device_model())
        if getattr(self, '_support_dialog', None) is not None:
            self._support_dialog.close()
        software_text = ""
        try:
            ver = self.window.device_manager.get_current_device_version()
            build = self.window.device_manager.get_current_device_build()
            if ver:
                text = QCoreApplication.translate("Nugget", "{0} {1}").format(device_os_name(self.window.device_manager.get_current_device_model()), ver)
                self.subtitle.setText(text)
                software_text = text
                if build:
                    software_text += "  ·  " + QCoreApplication.translate("Nugget", "Build {0}").format(build)
            else:
                self.subtitle.setText(QCoreApplication.translate("Nugget", "No device connected"))
        except AttributeError:
            self.subtitle.setText(QCoreApplication.translate("Nugget", "No device connected"))
        self.subtitle.clear()
        self.subtitle.hide()
        self.device_name.setVisible(connected)
        self.device_name.setText(manager.get_current_device_name() if connected else "")
        self.device_software.setText(software_text if connected else "")
        device = next((item for item in manager.devices if item.udid == manager.get_current_device_udid()), None)
        connection = self.tr("Connected via USB") if connected else ""
        developer_mode = getattr(device, "developer_mode", None)
        if isinstance(developer_mode, bool):
            connection += " · " + (self.tr("Developer Mode: On") if developer_mode else self.tr("Developer Mode: Off"))
        self.device_connection.setText(connection)
        self.device_connection.setVisible(connected)
        self.picker_software.setText(software_text if connected else self.tr("No device connected"))
        self.picker_combo.blockSignals(True)
        self.picker_combo.setCurrentIndex(self.device_combo.currentIndex())
        self.picker_combo.blockSignals(False)
        self.picker_combo.update_visible_devices()
        self.update_passcode_support()
        self.device_details.setVisible(bool(self.window.device_manager.get_current_device_udid()))
        self.device_details.update_info()
        self.device_details._update_selection_counts()
        self.picker_details.update_info()
        self._refresh_storage()

    def update_passcode_support(self):
        reason = current_passcode_theme_reason(self.window.device_manager)
        self.passcode_theme_card.setEnabled(not reason)
        icon, resource, title, caption = self._tiles[-1]
        if reason:
            message = "Your version is not supported" if self.window.device_manager.get_current_device_udid() else "Connect an iPhone"
            caption.setText(QCoreApplication.translate("Nugget", message))
        else:
            caption.setText(QCoreApplication.translate("Nugget", "Custom keypad theme (.passthm)"))
        self.passcode_theme_card.setAccessibleDescription(reason or "")
        color = self._c.text_disabled if reason else self._c.text_secondary
        caption.setStyleSheet(t("home_tile_subtitle") + f"color: {color};")
        title.setStyleSheet(t("home_tile_title") +
                           f"color: {self._c.text_disabled if reason else self._c.text_primary};")
        self._paint_tile_icon(icon, resource)

    def _refresh_storage(self):
        udid = self.window.device_manager.get_current_device_udid()
        cached = self._device_info_cache.get(udid, {})
        self.window._storage_info = cached.get("storage")
        self.window._battery_info = cached.get("battery")
        self.device_details.update_info()
        self.picker_details.update_info()
        if not udid or self._device_info_stopping:
            return
        if udid in self._storage_workers:
            self._storage_thread = self._storage_workers[udid]
            return
        if time.monotonic() - cached.get("checked", 0) < 15:
            return
        worker = _StorageThread(udid, self)
        self._storage_thread = worker
        self._storage_workers[udid] = worker
        worker.result.connect(self._on_storage_result)
        worker.capacity_ready.connect(self._on_capacity_result)
        worker.finished.connect(self._on_storage_finished)
        worker.start()
        self.device_details.update_info()
        self.picker_details.update_info()

    @Slot(object)
    def _on_capacity_result(self, capacity):
        worker = self.sender()
        if self._storage_workers.get(worker.udid) is not worker:
            return
        cached = self._device_info_cache.setdefault(worker.udid, {})
        cached["capacity"] = int(capacity)
        if cached.get("storage"):
            cached["storage"]["capacity"] = int(capacity)
        self._update_picker_labels()
        if worker.udid == self.window.device_manager.get_current_device_udid():
            self.device_details.update_info()
            self.picker_details.update_info()

    @Slot(object, object, object)
    def _on_storage_result(self, total, free, battery):
        worker = self.sender()
        if self._storage_workers.get(worker.udid) is not worker:
            return
        cached = self._device_info_cache.setdefault(worker.udid, {})
        if battery is not None:
            cached["battery"] = {"udid": worker.udid, **battery}
        if total and total > 0 and free is not None:
            cached["storage"] = {"udid": worker.udid, "total": int(total), "free": int(free),
                                 "capacity": cached.get("capacity")}
            self._update_picker_labels()
        if worker.udid == self.window.device_manager.get_current_device_udid():
            self.window._storage_info = cached.get("storage")
            self.window._battery_info = cached.get("battery")
            self.device_details.update_info()
            self.picker_details.update_info()

    def _on_storage_finished(self):
        worker = self.sender()
        if self._storage_workers.get(worker.udid) is worker:
            del self._storage_workers[worker.udid]
        self._device_info_cache.setdefault(worker.udid, {})["checked"] = time.monotonic()
        if worker is self._storage_thread:
            self._storage_thread = None
        worker.deleteLater()
        if worker.udid == self.window.device_manager.get_current_device_udid():
            self.device_details.update_info()
            self.picker_details.update_info()

    def stop_device_info(self):
        self._device_info_stopping = True
        deadline = time.monotonic() + 5
        return all(worker.wait(max(0, int((deadline - time.monotonic()) * 1000)))
                   for worker in list(self._storage_workers.values()))

    def refresh_device_combo(self):
        self.populate_device_picker()

    def _build_control_tabs(self):
        self._control_icons = {self._devices_page: ":/icon/phone.svg", self._presets_page: ":/icon/folder.svg"}
        self.control_tabs.addTab(self._presets_page, QCoreApplication.translate("Nugget", "Presets"))
        self._control_actions = {}
        self._control_action_titles = {}
        for title, resource, callback in (
            ("Settings", ":/icon/gear.svg", self.open_settings),
        ):
            page = QWidget(self.control_tabs)
            self.control_tabs.addTab(page, self.tr(title))
            self._control_action_titles[page] = self.tr(title)
            self.control_tabs.setTabToolTip(self.control_tabs.indexOf(page), self.tr(title))
            page.setAccessibleName(self.tr(title))
            self._control_actions[page] = callback
            self._control_icons[page] = resource
        self._last_control_page = self._device_summary_page
        self.control_tabs.setCurrentWidget(self._device_summary_page)
        self.control_tabs.setIconSize(QSize(21, 21))
        self._update_control_icons()
        self._control_preferred_width = 360
        self.control_tabs.setFixedWidth(min(self._control_preferred_width, max(320, self.width() - 48)))

    def _update_control_icons(self):
        for page, resource in self._control_icons.items():
            self.control_tabs.setTabIcon(self.control_tabs.indexOf(page), theme_icon(resource, self._c.text_secondary))

    def _on_control_tab_changed(self, index):
        page = self.control_tabs.widget(index)
        action = self._control_actions.get(page)
        if action is None:
            self._last_control_page = page
            return
        self.control_tabs.blockSignals(True)
        self.control_tabs.setCurrentWidget(self._last_control_page)
        self.control_tabs.blockSignals(False)
        QTimer.singleShot(0, action)

    def refresh_preset_widget(self):
        """Keep the top-bar preset card's subtitle in sync."""
        try:
            autosave = self.window.autosave_enabled()
        except Exception:
            autosave = True
        name = self.window.settings.value("last_loaded_preset", "", type=str) or ""
        if name:
            self.presets_lbl.setText(name)
        elif autosave:
            self.presets_lbl.setText(QCoreApplication.translate("Nugget", "AutoSave"))
        else:
            self.presets_lbl.setText(QCoreApplication.translate("Nugget", "Manage presets"))

    def set_statusbar_visible(self, visible: bool):
        self.statusbar_card.setVisible(visible)
        self.cards_grid.reflow()

    def _make_card(self, title: str, subtitle: str, page_index: int) -> IOSCard:
        """One home feature tile: a big themed icon with the name below it."""
        card = _TileCard()
        card.setProperty('liquidHomeCard',True)
        card.setMaximumWidth(180)
        card.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 20, 10, 16)
        card_layout.setSpacing(12)
        card_layout.setAlignment(Qt.AlignHCenter)

        icon_res = FEATURE_ICONS.get(title, ":/icon/compass.svg")
        from src.gui.liquid.controls import MagnifyingArtwork
        icon_lbl = MagnifyingArtwork(card)
        icon_lbl.setFixedSize(140, 128)
        icon_lbl.setAlignment(Qt.AlignCenter)
        card._home_artwork_motion=icon_lbl
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
        return card

    def _make_mobile_row(self) -> IOSCard:
        """The GoldenNugget Mobile compact row: opens the helper dialog.

        Same one-line shape as _make_catalog_row() — this entry has no page
        of its own, it exec()s MobileHelperDialog on a click.
        """
        card = _TileCard()
        card.setProperty('liquidCatalog', True)
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)
        self._mobile_icon = QLabel(card)
        self._mobile_icon.setFixedSize(38, 38)
        self._mobile_icon.setStyleSheet("background-color: transparent;")
        row.addWidget(self._mobile_icon)
        self._mobile_title = QLabel(
            QCoreApplication.translate("Nugget", "GoldenNugget Mobile"), card)
        row.addWidget(self._mobile_title)
        self._mobile_caption = QLabel(QCoreApplication.translate(
            "Nugget", "Companion app for your iPhone"), card)
        row.addWidget(self._mobile_caption, 1)
        self._mobile_chevron = QLabel("›", card)
        row.addWidget(self._mobile_chevron)

        def open_helper(_event):
            from src.gui.dialogs.mobile_helper_dialog import MobileHelperDialog
            MobileHelperDialog(self.window()).exec()

        card.mousePressEvent = open_helper
        card.setCursor(Qt.PointingHandCursor)
        self._paint_mobile_row()
        return card

    def _make_catalog_row(self) -> IOSCard:
        """The Community Catalog entry: icon, name and caption on one line."""
        card = _TileCard()
        card.setProperty('liquidCatalog',True)
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)
        self._catalog_icon = QLabel(card)
        self._catalog_icon.setFixedSize(38, 38)
        self._catalog_icon.setStyleSheet("background-color: transparent;")
        row.addWidget(self._catalog_icon)
        self._catalog_title = QLabel(QCoreApplication.translate("Nugget", "Community Catalog"), card)
        row.addWidget(self._catalog_title)
        self._catalog_caption = QLabel(
            QCoreApplication.translate("Nugget", "Presets & templates from the community"), card)
        row.addWidget(self._catalog_caption, 1)
        self._catalog_chevron = QLabel("›", card)
        row.addWidget(self._catalog_chevron)
        card.mousePressEvent = lambda e: self.switch_to_ios_page(13)
        card.setCursor(Qt.PointingHandCursor)
        self._paint_catalog_row()
        QTimer.singleShot(0, self.refresh_catalog_badge)
        return card

    def refresh_catalog_badge(self):
        """Mention catalog updates for imported presets and added templates,
        counted against the cached catalog (no download)."""
        text = QCoreApplication.translate("Nugget", "Presets & templates from the community")
        try:
            from src.controllers import preset_catalog
            from src.controllers.preset_manager import PresetManager
            data, _saved_at = preset_catalog.read_cache()
            if data is not None:
                pm = getattr(getattr(self.window, "ios_presets", None), "preset_manager", None) or PresetManager()
                entries, templates, _ = preset_catalog.parse_catalog(data, pm._valid_import_structure)
                updates = preset_catalog.count_updates(entries + templates, preset_catalog.installed_items(pm))
                if updates:
                    text = QCoreApplication.translate("Nugget", "{0} update(s) available").format(updates)
        except Exception:
            pass
        self._catalog_caption.setText(text)

    def _paint_catalog_row(self):
        if not hasattr(self, "_catalog_icon"):
            return
        self._catalog_icon.setPixmap(theme_pixmap(
            FEATURE_ICONS["Community Catalog"], self._c.text_primary, 38, self.devicePixelRatioF()))
        self._catalog_title.setStyleSheet(t("home_tile_title") + "font-size: 18px;")
        self._catalog_caption.setStyleSheet(t("home_tile_subtitle") + "font-size: 14px;")
        self._catalog_chevron.setStyleSheet(t("home_tile_subtitle") + "font-size: 20px;")

    def _paint_mobile_row(self):
        if not hasattr(self, "_mobile_icon"):
            return
        self._mobile_icon.setPixmap(theme_pixmap(
            FEATURE_ICONS["GoldenNugget Mobile"], self._c.text_primary,
            38, self.devicePixelRatioF()))
        self._mobile_title.setStyleSheet(t("home_tile_title") + "font-size: 18px;")
        self._mobile_caption.setStyleSheet(t("home_tile_subtitle") + "font-size: 14px;")
        self._mobile_chevron.setStyleSheet(t("home_tile_subtitle") + "font-size: 20px;")

    def _paint_tile_icon(self, label: QLabel, icon_res: str):
        """Draw a feature icon at tile size (and screen density) in the
        current text color."""
        dpr = self.devicePixelRatioF()
        sizes = {
            FEATURE_ICONS["Passcode Theme"]: 126,
            FEATURE_ICONS["Status Bar"]: 138,
            FEATURE_ICONS["Icon Themes"]: 120,
            FEATURE_ICONS["Daemons"]: 126,
            FEATURE_ICONS["Tweaks"]: 126,
            FEATURE_ICONS["PosterBoard"]: 126,
        }
        artwork = theme_pixmap(icon_res, self._c.text_primary,
                               sizes.get(icon_res, 100), dpr)
        offsets = {
            FEATURE_ICONS["Tweaks"]: -14,
            FEATURE_ICONS["Icon Themes"]: 9,
        }
        offset = offsets.get(icon_res, 0)
        canvas = QPixmap(round(label.width() * dpr), round(label.height() * dpr))
        canvas.setDevicePixelRatio(dpr)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        width = artwork.width() / artwork.devicePixelRatioF()
        height = artwork.height() / artwork.devicePixelRatioF()
        painter.drawPixmap(round((label.width() - width) / 2 + offset),
                           round((label.height() - height) / 2), artwork)
        painter.end()
        label.setPixmap(canvas)
