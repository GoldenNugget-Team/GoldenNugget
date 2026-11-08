import os

from PySide6.QtCore import QCoreApplication, QSize, Qt, QUrl
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.gui.liquid.choice_editor import GlassComboBox as QComboBox  # noqa: F811 (intentional: swap in glass combos)
from src.gui.theme import ColorThemeManager, t, theme_pixmap
from src.gui.widgets import (
    IOSCard,
    IOSPrimaryButton,
    IOSSwitch,
)
from src.tweaks.tweaks import TweakID, tweaks


class TendieRow(IOSCard):
    """One installed ``.tendies`` wallpaper as a full-width list row.

    Left: the preview thumbnail. Middle: the wallpaper name plus a caption
    telling whether it is converted to the modern format on apply. Right: the
    **Convert** switch (legacy packages only — turning it off installs the
    original files untouched), the lock-screen preview and delete actions. The
    page fills the thumbnail in through ``_load_tendie_preview_by_name`` right
    after construction.
    """

    THUMB = 48

    def __init__(self, page, tendie, parent=None):
        super().__init__(parent)
        self._page = page
        self.tendie = tendie
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(72)

        inner = QHBoxLayout(self)
        inner.setContentsMargins(12, 8, 12, 8)
        inner.setSpacing(12)

        self.icon = QLabel(self)
        self.icon.setFixedSize(self.THUMB, self.THUMB)
        self.icon.setAlignment(Qt.AlignCenter)
        inner.addWidget(self.icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.name = QLabel(tendie.name.replace(".tendies", ""), self)
        self.name.setWordWrap(False)
        text_col.addWidget(self.name)
        # Second line: the conversion state the Convert switch controls.
        self.format_lbl = QLabel(self._format_caption(), self)
        self.format_lbl.setWordWrap(False)
        text_col.addWidget(self.format_lbl)
        inner.addLayout(text_col, 1)

        self.convert_switch = None
        self.convert_lbl = None
        if tweaks[TweakID.PosterBoard].tendie_needs_conversion(tendie):
            self.convert_switch = IOSSwitch(
                tweaks[TweakID.PosterBoard].tendie_convert_enabled(tendie), self)
            self.convert_switch.setToolTip(QCoreApplication.translate(
                "Nugget",
                "Convert this legacy wallpaper to the modern iOS 27 format when "
                "applied. Turn it off to install the original files untouched."))
            self.convert_switch.toggled.connect(self._on_convert_toggled)

            self.convert_lbl = QLabel(QCoreApplication.translate("Nugget", "Convert"), self)
            convert_row = QHBoxLayout()
            convert_row.setContentsMargins(0, 0, 0, 0)
            convert_row.setSpacing(8)
            convert_row.addWidget(self.convert_lbl)
            convert_row.addWidget(self.convert_switch)
            inner.addLayout(convert_row)

        self.preview_btn = QToolButton(self)
        self.preview_btn.setIconSize(QSize(18, 18))
        self.preview_btn.setIcon(QIcon(":/icon/wallpaper.svg"))
        self.preview_btn.setToolTip(QCoreApplication.translate(
            "Nugget", "Lock screen preview"))
        self.preview_btn.setCursor(Qt.PointingHandCursor)
        self.preview_btn.clicked.connect(lambda: page._show_tendie_preview(tendie))
        check_btn = QPushButton(QCoreApplication.translate('Nugget', 'Check'), self)
        self.check_btn = check_btn
        check_btn.clicked.connect(lambda: page._validate_package(tendie.path))
        inner.addWidget(check_btn)
        inner.addWidget(self.preview_btn)

        self.del_btn = QToolButton(self)
        self.del_btn.setIconSize(QSize(18, 18))
        self.del_btn.setIcon(QIcon(":/icon/trash.svg"))
        self.del_btn.setToolTip(QCoreApplication.translate("Nugget", "Delete"))
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.clicked.connect(lambda: page._delete_tendie(tendie))
        inner.addWidget(self.del_btn)

        # IOSCard.__init__ already connected _retheme to theme_changed; restyle
        # now that the child widgets exist.
        self._retheme()
        self._update_conversion_ui()

    def _conversion_supported(self) -> bool:
        version = self._page.window.device_manager.get_current_device_version()
        return tweaks[TweakID.PosterBoard]._legacy_convert_supported(version)

    def _update_conversion_ui(self):
        if self.convert_switch is not None:
            supported = self._conversion_supported()
            self.convert_switch.setVisible(supported)
            self.convert_lbl.setVisible(supported)
        self.format_lbl.setText(self._format_caption())

    def showEvent(self, event):
        super().showEvent(event)
        # Rows survive device changes; recheck the currently selected iPhone.
        self._update_conversion_ui()

    def _format_caption(self) -> str:
        posterboard = tweaks[TweakID.PosterBoard]
        if not posterboard.tendie_needs_conversion(self.tendie):
            return QCoreApplication.translate("Nugget", "Modern format")
        if self._conversion_supported() and posterboard.tendie_convert_enabled(self.tendie):
            return QCoreApplication.translate("Nugget", "Converts to the modern format")
        return QCoreApplication.translate("Nugget", "Installs as is")

    def _on_convert_toggled(self, checked: bool):
        tweaks[TweakID.PosterBoard].set_tendie_convert(self.tendie, checked)
        self.format_lbl.setText(self._format_caption())

    def _retheme(self):
        super()._retheme()
        if not hasattr(self, "icon"):
            return
        if hasattr(self, 'check_btn'):
            self.check_btn.setStyleSheet(t('mini_button'))
        c = ColorThemeManager.instance().colors
        self.icon.setStyleSheet(
            f"QLabel {{ background-color: {c.surface_hover}; border-radius: 8px; }}"
        )
        self.name.setStyleSheet(
            f"color: {c.text_primary}; font-size: 15px; background: transparent;"
        )
        self.format_lbl.setStyleSheet(
            f"color: {c.text_secondary}; font-size: 12px; background: transparent;"
        )
        if self.convert_lbl is not None:
            self.convert_lbl.setStyleSheet(
                f"color: {c.text_secondary}; font-size: 12px; background: transparent;"
            )
        self.preview_btn.setStyleSheet(
            f"QToolButton {{ background-color: {c.bg_secondary}; color: {c.accent}; "
            f"border: 1px solid {c.border}; border-radius: 10px; padding: 7px; }}"
            f"QToolButton:hover {{ background-color: {c.surface_hover}; }}"
        )
        self.del_btn.setStyleSheet(
            f"QToolButton {{ background-color: {c.bg_secondary}; color: {c.error}; "
            f"border: 1px solid {c.border}; border-radius: 10px; padding: 7px; }}"
            f"QToolButton:hover {{ background-color: {c.error}; color: {c.text_inverse}; }}"
        )
        self.preview_btn.setIcon(QIcon(theme_pixmap(':/icon/wallpaper.svg', c.accent, 18, self.devicePixelRatioF())))
        self.del_btn.setIcon(QIcon(theme_pixmap(':/icon/trash.svg', c.error, 18, self.devicePixelRatioF())))


class IOSPosterboardPage(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        self.setObjectName("iosContainer")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Reset PosterBoard card
        reset_card = IOSCard()
        reset_layout = QVBoxLayout(reset_card)
        reset_layout.setContentsMargins(16, 12, 16, 12)
        reset_layout.setSpacing(8)

        self._reset_btn = QPushButton(QCoreApplication.translate("Nugget", "Reset PosterBoard"))
        self._reset_btn.setFixedHeight(52)
        self._reset_btn.setCursor(Qt.PointingHandCursor)
        self._reset_btn.clicked.connect(self._reset_posterboard)
        self._check_btn = QPushButton(QCoreApplication.translate('Nugget', 'Check Package…'))
        self._check_btn.clicked.connect(self._choose_package_to_validate)
        reset_layout.addWidget(self._reset_btn)

        self._reset_caption = QLabel(QCoreApplication.translate(
            "Nugget",
            "Emergency reset for when PosterBoard behaves strangely or the "
            "database won't load after a restore. Resets on the next apply."
        ))
        self._reset_caption.setWordWrap(True)
        reset_layout.addWidget(self._reset_caption)


        # Tab bar
        self.tab_stack = QStackedWidget()

        # Tendies tab
        self.tendies_page = self._create_tendies_tab()
        self.tab_stack.addWidget(self.tendies_page)

        # Video tab
        self.video_page = self._create_video_tab()
        self.tab_stack.addWidget(self.video_page)
        from src.gui.ios.tweaks import IOSSectionPage
        from src.tweaks.registry import Section
        self.preferences_page=IOSSectionPage(window,Section.POSTERBOARD)
        self.tab_stack.addWidget(self.preferences_page)

        # Tab bar on top, sharing its row with "Check Package…": a mobile-style
        # bottom bar sat in the middle of the window, above the reset footer,
        # and left the check button floating alone under the header.
        self._tab_bar = QWidget()
        self._tab_bar.setObjectName("pbTabBar")
        self._tab_bar.setFixedHeight(52)
        tab_layout = QHBoxLayout(self._tab_bar)
        tab_layout.setContentsMargins(16, 8, 16, 4)
        tab_layout.setSpacing(4)

        self.tendies_tab_btn = self._make_tab_button(QCoreApplication.translate("Nugget", "Tendies"), ":/icon/wallpaper.svg", 0)
        self.video_tab_btn = self._make_tab_button(QCoreApplication.translate("Nugget", "Video"), ":/icon/play-circle.svg", 1)

        tab_layout.addWidget(self.tendies_tab_btn)
        tab_layout.addWidget(self.video_tab_btn)
        self.preferences_tab_btn=self._make_tab_button(self.tr('Preferences'),':/icon/wallpaper.svg',2)
        tab_layout.addWidget(self.preferences_tab_btn)
        tab_layout.addStretch()
        tab_layout.addWidget(self._check_btn)

        layout.addWidget(self._tab_bar)
        layout.addWidget(self.tab_stack)
        reset_footer = QWidget(self)
        reset_footer_layout = QVBoxLayout(reset_footer)
        reset_footer_layout.setContentsMargins(16, 8, 16, 16)
        reset_footer_layout.addWidget(reset_card)
        layout.addWidget(reset_footer)

        self._tendie_nam = QNetworkAccessManager(self)
        self._tendie_preview_replies = []

        self._retheme()
        self._switch_tab(0)
        self.refresh_tendies()


    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self._check_btn.setStyleSheet(t('mini_button'))
        self._reset_btn.setStyleSheet(t("maintenance_button"))
        self._reset_caption.setStyleSheet(f"color: {c.text_secondary}; font-size: 12px; background-color: transparent;")
        self._tab_bar.setStyleSheet(
            f"QWidget#pbTabBar {{ background-color: {c.bg_primary}; }}"
        )
        for btn in (self.tendies_tab_btn, self.video_tab_btn,self.preferences_tab_btn):
            btn.setStyleSheet(f"""
                QToolButton {{
                    background: transparent;
                    color: {c.text_secondary};
                    font-size: 13px;
                    font-weight: 600;
                    padding: 6px 12px;
                    border: none;
                    border-radius: 8px;
                }}
                QToolButton:hover {{ background-color: {c.surface_hover}; }}
                QToolButton:checked {{
                    color: {c.accent};
                    background-color: {c.bg_tertiary};
                }}
            """)
        self._retheme_tendies_tab()
        self._retheme_video_tab()
        self._update_tab_icons()

    def _retheme_tendies_tab(self):
        c = ColorThemeManager.instance().colors
        if hasattr(self, '_tendies_scroll'):
            self._tendies_scroll.setStyleSheet(
                f"background-color: {c.bg_primary}; border: none;"
            )
        if hasattr(self, '_download_icon'):
            self._download_icon.setStyleSheet(
                f"QLabel {{ background-color: {c.accent}; border-radius: 12px; font-size: 24px; color: {c.text_inverse}; }}"
            )
        if hasattr(self, '_download_title'):
            self._download_title.setStyleSheet(
                f"font-size: 16px; font-weight: 600; color: {c.text_primary}; background-color: transparent;"
            )
        if hasattr(self, '_download_subtitle'):
            self._download_subtitle.setStyleSheet(
                f"font-size: 12px; color: {c.text_secondary}; background-color: transparent;"
            )
        if hasattr(self, '_download_chevron'):
            self._download_chevron.setStyleSheet(
                f"font-size: 26px; color: {c.text_secondary}; background-color: transparent;"
            )
        if hasattr(self, '_import_icon'):
            self._import_icon.setStyleSheet(
                f"QLabel {{ background-color: {c.bg_secondary}; border-radius: 12px; border: 2px dashed {c.border}; font-size: 24px; color: {c.accent}; }}"
            )
        if hasattr(self, '_import_title'):
            self._import_title.setStyleSheet(
                f"font-size: 16px; font-weight: 600; color: {c.text_primary}; background-color: transparent;"
            )
        if hasattr(self, '_import_subtitle'):
            self._import_subtitle.setStyleSheet(
                f"font-size: 12px; color: {c.text_secondary}; background-color: transparent;"
            )
        if hasattr(self, '_import_chevron'):
            self._import_chevron.setStyleSheet(
                f"font-size: 26px; color: {c.text_secondary}; background-color: transparent;"
            )


    def _retheme_video_tab(self):
        c = ColorThemeManager.instance().colors
        if hasattr(self, '_video_scroll'):
            self._video_scroll.setStyleSheet(
                f"background-color: {c.bg_primary}; border: none;"
            )
        for lbl in getattr(self, '_video_labels', []):
            lbl.setStyleSheet(f"font-size: 15px; color: {c.text_primary}; min-width: 100px; background-color: transparent;")
        for btn in (getattr(self, 'thumb_btn', None), getattr(self, 'video_btn', None)):
            if btn is not None:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {c.bg_secondary};
                        border-radius: 10px;
                        color: {c.accent};
                        font-size: 15px;
                        padding: 12px 24px;
                        border: none;
                    }}
                    QPushButton:hover {{ background-color: {c.surface_hover}; }}
                """)
        for chk in (getattr(self, 'loop_chk', None), getattr(self, 'reverse_chk', None),
                     getattr(self, 'foreground_chk', None)):
            if chk is not None:
                chk.setStyleSheet(f"color: {c.text_primary}; font-size: 15px; background-color: transparent;")
        if hasattr(self, 'calc_mode_drp'):
            self.calc_mode_drp.setStyleSheet(f"""
                QComboBox {{
                    background-color: {c.bg_secondary};
                    border: none;
                    border-radius: 10px;
                    color: {c.text_primary};
                    font-size: 10.5pt;
                    padding: 8px 12px;
                }}
                QComboBox::drop-down {{ border: none; width: 24px; }}
                QComboBox QAbstractItemView {{
                    background-color: {c.surface_hover};
                    border: 1px solid {c.border};
                    border-radius: 10px;
                    color: {c.text_primary};
                    selection-background-color: {c.accent};
                }}
            """)

    def _make_tab_button(self, text: str, icon_path: str, index: int) -> QToolButton:
        btn = QToolButton()
        btn.setText(text)
        btn.setIconSize(QSize(18, 18))
        btn.setProperty('icon_resource', icon_path)
        btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self._switch_tab(index))
        return btn

    def _switch_tab(self, index: int):
        self.tab_stack.setCurrentIndex(index)
        self.tendies_tab_btn.setChecked(index == 0)
        self.video_tab_btn.setChecked(index == 1)
        self.preferences_tab_btn.setChecked(index == 2)
        self._update_tab_icons()

    def _update_tab_icons(self):
        c = ColorThemeManager.instance().colors
        for button in (self.tendies_tab_btn, self.video_tab_btn,self.preferences_tab_btn):
            color = c.accent if button.isChecked() else c.text_secondary
            button.setIcon(QIcon(theme_pixmap(button.property('icon_resource'), color, 18, self.devicePixelRatioF())))

    def _create_tendies_tab(self) -> QWidget:
        self._tendies_scroll = QScrollArea()
        self._tendies_scroll.setWidgetResizable(True)
        content = QWidget()
        self._tendies_scroll.setWidget(content)

        self.tendies_list = QVBoxLayout(content)
        self.tendies_list.setContentsMargins(16, 16, 16, 32)
        self.tendies_list.setSpacing(10)
        self.tendies_list.setAlignment(Qt.AlignTop)

        self.download_card = self._create_download_card()
        self.tendies_list.addWidget(self.download_card)

        self.import_row = self._create_import_row()
        self.tendies_list.addWidget(self.import_row)

        return self._tendies_scroll

    def _create_download_card(self) -> QWidget:
        card = IOSCard()
        card.setCursor(Qt.PointingHandCursor)
        card.setMinimumHeight(88)
        card.mousePressEvent = lambda e: self.open_wallpaper_downloader()

        inner = QHBoxLayout(card)
        inner.setContentsMargins(16, 12, 16, 12)
        inner.setSpacing(12)

        self._download_icon = QLabel()
        self._download_icon.setFixedSize(48, 48)
        self._download_icon.setAlignment(Qt.AlignCenter)
        self._download_icon.setText("\u2193")
        inner.addWidget(self._download_icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._download_title = QLabel(QCoreApplication.translate("Nugget", "Download Wallpapers"))
        text_col.addWidget(self._download_title)
        self._download_subtitle = QLabel(QCoreApplication.translate(
            "Nugget",
            "Browse and import wallpapers from Cowabunga and CaPlayground"))
        text_col.addWidget(self._download_subtitle)
        inner.addLayout(text_col, 1)

        self._download_chevron = QLabel("\u203A")
        inner.addWidget(self._download_chevron)

        return card

    def _create_import_row(self) -> QWidget:
        card = IOSCard()
        card.setCursor(Qt.PointingHandCursor)
        card.setMinimumHeight(88)
        card.mousePressEvent = lambda e: self.show_add_tendies_dialog()

        inner = QHBoxLayout(card)
        inner.setContentsMargins(16, 12, 16, 12)
        inner.setSpacing(12)

        self._import_icon = QLabel()
        self._import_icon.setFixedSize(48, 48)
        self._import_icon.setAlignment(Qt.AlignCenter)
        self._import_icon.setText("+")
        inner.addWidget(self._import_icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._import_title = QLabel(QCoreApplication.translate("Nugget", "Import Files (.tendies)"))
        text_col.addWidget(self._import_title)
        self._import_subtitle = QLabel(QCoreApplication.translate(
            "Nugget", "Add a wallpaper loop from a .tendies file"))
        text_col.addWidget(self._import_subtitle)
        inner.addLayout(text_col, 1)

        self._import_chevron = QLabel("\u203A")
        inner.addWidget(self._import_chevron)

        return card


    def _create_video_tab(self) -> QWidget:
        self._video_scroll = QScrollArea()
        self._video_scroll.setWidgetResizable(True)
        content = QWidget()
        self._video_scroll.setWidget(content)

        v_layout = QVBoxLayout(content)
        v_layout.setContentsMargins(16, 16, 16, 32)
        v_layout.setSpacing(16)

        self._video_labels = []

        thumb_row = QHBoxLayout()
        thumb_label = QLabel(QCoreApplication.translate("Nugget", "Thumbnail"))
        self._video_labels.append(thumb_label)
        self.thumb_btn = QPushButton(QCoreApplication.translate("Nugget", "Choose Freeze Frame (.HEIC)"))
        self.thumb_btn.setCursor(Qt.PointingHandCursor)
        self.thumb_btn.clicked.connect(self.on_choose_thumb_clicked)
        thumb_row.addWidget(thumb_label)
        thumb_row.addWidget(self.thumb_btn, 1)
        v_layout.addLayout(thumb_row)

        video_row = QHBoxLayout()
        video_label = QLabel(QCoreApplication.translate("Nugget", "Video"))
        self._video_labels.append(video_label)
        self.video_btn = QPushButton(QCoreApplication.translate("Nugget", "Choose Video"))
        self.video_btn.setCursor(Qt.PointingHandCursor)
        self.video_btn.clicked.connect(self.on_choose_video_clicked)
        video_row.addWidget(video_label)
        video_row.addWidget(self.video_btn, 1)
        v_layout.addLayout(video_row)

        v_layout.addWidget(QLabel(QCoreApplication.translate("Nugget", "Options")))
        self.loop_chk = QCheckBox(QCoreApplication.translate("Nugget", "Loop (use CoreAnimation method)"))
        self.loop_chk.setChecked(tweaks[TweakID.PosterBoard].loop_video)
        self.loop_chk.toggled.connect(self.on_loop_toggled)
        v_layout.addWidget(self.loop_chk)

        self.reverse_chk = QCheckBox(QCoreApplication.translate("Nugget", "Reverse on Loop"))
        self.reverse_chk.setChecked(tweaks[TweakID.PosterBoard].reverse_video)
        self.reverse_chk.toggled.connect(self.on_reverse_toggled)
        v_layout.addWidget(self.reverse_chk)

        self.foreground_chk = QCheckBox(QCoreApplication.translate("Nugget", "Make Foreground (hides clock)"))
        self.foreground_chk.setChecked(tweaks[TweakID.PosterBoard].use_foreground)
        self.foreground_chk.toggled.connect(self.on_foreground_toggled)
        v_layout.addWidget(self.foreground_chk)

        calc_row = QHBoxLayout()
        calc_label = QLabel(QCoreApplication.translate("Nugget", "Calculation Mode"))
        self._video_labels.append(calc_label)
        self.calc_mode_drp = QComboBox()
        self.calc_mode_drp.addItem(QCoreApplication.translate("Nugget", "Linear"))
        self.calc_mode_drp.addItem(QCoreApplication.translate("Nugget", "Discrete"))
        self.calc_mode_drp.setCurrentIndex(0 if tweaks[TweakID.PosterBoard].calculationMode == 'linear' else 1)
        self.calc_mode_drp.activated.connect(self.on_calc_mode_selected)
        calc_row.addWidget(calc_label)
        calc_row.addWidget(self.calc_mode_drp, 1)
        v_layout.addLayout(calc_row)

        export_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Export Video Loop (.tendies)"))
        export_btn.clicked.connect(self.on_export_video_clicked)
        v_layout.addWidget(export_btn)

        ext_row = QHBoxLayout()
        discover_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Discover Wallpapers"))
        discover_btn.clicked.connect(self.on_discover_wallpapers)
        help_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "Help"))
        help_btn.clicked.connect(self.on_help)
        ext_row.addWidget(discover_btn)
        ext_row.addWidget(help_btn)
        v_layout.addLayout(ext_row)

        v_layout.addStretch()

        self._update_video_labels()

        return self._video_scroll

    def _update_video_labels(self):
        pb = tweaks[TweakID.PosterBoard]
        thumb = pb.videoThumbnail if pb.videoThumbnail else None
        video = pb.videoFile if pb.videoFile else None
        self.thumb_btn.setText(QCoreApplication.translate("Nugget", "Choose Freeze Frame (.HEIC)") if not thumb else thumb)
        self.video_btn.setText(QCoreApplication.translate("Nugget", "Choose Video") if not video else video)
        self.reverse_chk.setVisible(pb.loop_video)
        self.foreground_chk.setVisible(pb.loop_video)

    def on_choose_thumb_clicked(self):
        from PySide6.QtWidgets import QFileDialog
        selected_file, _ = QFileDialog.getOpenFileName(
            self.window, QCoreApplication.translate("Nugget", "Select Image File"), "", "Image Files (*.heic)"
        )
        pb = tweaks[TweakID.PosterBoard]
        if selected_file:
            pb.videoThumbnail = selected_file
        else:
            pb.videoThumbnail = None
        self._update_video_labels()

    def on_choose_video_clicked(self):
        from PySide6.QtWidgets import QFileDialog
        selected_file, _ = QFileDialog.getOpenFileName(
            self.window, QCoreApplication.translate("Nugget", "Select Video File"), "", "Video Files (*.mov *.mp4 *.mkv)"
        )
        pb = tweaks[TweakID.PosterBoard]
        if selected_file:
            pb.videoFile = selected_file
        else:
            pb.videoFile = None
        self._update_video_labels()

    def on_loop_toggled(self, checked: bool):
        tweaks[TweakID.PosterBoard].loop_video = checked
        self.reverse_chk.setVisible(checked)
        self.foreground_chk.setVisible(checked)

    def on_reverse_toggled(self, checked: bool):
        tweaks[TweakID.PosterBoard].reverse_video = checked

    def on_foreground_toggled(self, checked: bool):
        tweaks[TweakID.PosterBoard].use_foreground = checked

    def on_calc_mode_selected(self, index: int):
        tweaks[TweakID.PosterBoard].calculationMode = 'linear' if index == 0 else 'discrete'

    def on_export_video_clicked(self):
        import subprocess
        import uuid
        from shutil import make_archive, rmtree

        from PySide6.QtWidgets import QFileDialog, QMessageBox
        directory = QFileDialog.getExistingDirectory(
            self.window, QCoreApplication.translate("Nugget", "Select Directory"), "",
            QFileDialog.ShowDirsOnly)
        if not directory:
            return
        try:
            path = os.path.join(directory, f"Nugget-Export-{uuid.uuid4()}")
            zip_path = path + ".tendies"
            from src.gui.dialogs.file_task import run_file_task
            def export():
                try:
                    tweaks[TweakID.PosterBoard].create_video_loop_files(output_dir=path)
                    make_archive(path, 'zip', path)
                    os.rename(path + '.zip', zip_path)
                finally:
                    rmtree(path, ignore_errors=True)
            run_file_task(self.window, QCoreApplication.translate("Nugget", "Export Video"), export)
            print(f"Created at {zip_path}")
            if os.name == 'nt':
                subprocess.Popen(f'explorer "{os.path.normpath(zip_path)}"')
            else:
                subprocess.Popen(["open", '-R', zip_path])
        except Exception as e:
            QMessageBox.critical(
                self.window, QCoreApplication.translate("QtCore.QCoreApplication", "Error!"),
                type(e).__name__ + ": " + repr(e))

    def on_discover_wallpapers(self):
        self.open_wallpaper_downloader()

    def open_wallpaper_downloader(self):
        from src.gui.dialogs.wallpaper_downloader import WallpaperDownloaderDialog
        dialog = WallpaperDownloaderDialog(self.window, self)
        dialog.exec()

    def on_help(self):
        from src.gui.dialogs import PBHelpDialog
        dialog = PBHelpDialog()
        dialog.exec()

    def show_add_tendies_dialog(self):
        from zipfile import BadZipFile

        from PySide6.QtWidgets import QFileDialog, QMessageBox
        selected_files, _ = QFileDialog.getOpenFileNames(
            self.window, QCoreApplication.translate("Nugget", "Select PosterBoard Files"), "", "Zip Files (*.tendies)"
        )
        if selected_files:
            try:
                device_version = self.window.device_manager.get_current_device_version()
            except Exception:
                device_version = None
            for file in selected_files:
                try:
                    if not tweaks[TweakID.PosterBoard].add_tendie(file, device_version):
                        break
                except (BadZipFile, OSError, ValueError) as error:
                    message = (QCoreApplication.translate(
                        "Nugget", "This file is not a valid wallpaper ZIP archive. "
                        "It may be incomplete or damaged. Download the original "
                        ".tendies file again; renaming another file will not convert it.")
                        if isinstance(error, BadZipFile) else str(error))
                    QMessageBox.warning(
                        self.window,
                        QCoreApplication.translate("Nugget", "Import Failed"),
                        os.path.basename(file) + "\n\n" + message)
            self.refresh_tendies()

    def refresh_tendies(self):
        for reply, *_ in self._tendie_preview_replies:
            reply.abort()
        self._tendie_preview_replies = []

        keep = (self.download_card, self.import_row)
        for i in reversed(range(self.tendies_list.count())):
            widget = self.tendies_list.itemAt(i).widget()
            if widget is not None and widget not in keep:
                # Detach before the deferred delete so the layout is correct
                # immediately (deleteLater alone keeps the row in the layout
                # until the event loop runs).
                self.tendies_list.removeWidget(widget)
                widget.deleteLater()

        # Fixed rows are re-added on every refresh so the order stays
        # download -> tendies -> import for both the empty and filled states.
        for w in keep:
            self.tendies_list.removeWidget(w)
        self.tendies_list.addWidget(self.download_card)
        for tendie in tweaks[TweakID.PosterBoard].tendies:
            self.tendies_list.addWidget(self._create_tendie_row(tendie))
        self.tendies_list.addWidget(self.import_row)

    def _create_tendie_row(self, tendie) -> QWidget:
        row = TendieRow(self, tendie)
        self._load_tendie_preview_by_name(row, row.icon, tendie.name)
        return row

    def _show_tendie_preview(self, tendie):
        from src.gui.dialogs.tendie_preview_dialog import TendiePreviewDialog
        TendiePreviewDialog(tendie, self).exec()

    def _choose_package_to_validate(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, QCoreApplication.translate('Nugget', 'Check Wallpaper Package'), '',
            'Wallpaper packages (*.tendies *.batter *.zip)')
        if path:
            self._validate_package(path)

    def _validate_package(self, path):
        from src.gui.dialogs.wallpaper_validation import WallpaperValidationDialog
        version = self.window.device_manager.get_current_device_version() or None
        WallpaperValidationDialog(path, version, self).exec()

    def _load_tendie_preview_by_name(self, card, icon_lbl, file_name):
        try:
            from src.controllers.wallpaper_api import (
                cached_preview_path,
                find_wallpaper_by_name,
            )
            wp = find_wallpaper_by_name(file_name)
        except Exception:
            return
        if wp is None:
            return
        path = cached_preview_path(wp.preview_url)
        if os.path.exists(path):
            self._set_tendie_thumbnail(icon_lbl, path)
            return
        reply = self._tendie_nam.get(QNetworkRequest(QUrl(wp.preview_url)))
        self._tendie_preview_replies.append((reply, card, icon_lbl, path))
        reply.finished.connect(
            lambda r=reply, c=card, il=icon_lbl, p=path:
                self._on_tendie_preview(r, c, il, p))

    def _on_tendie_preview(self, reply, card, icon_lbl, path):
        self._tendie_preview_replies = [
            (r, c, i, p) for (r, c, i, p) in self._tendie_preview_replies
            if r is not reply]
        data = bytes(reply.readAll())
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError or not data:
            return
        if not self._widget_is_valid(icon_lbl):
            return
        try:
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            return
        self._set_tendie_thumbnail(icon_lbl, path)

    def _set_tendie_thumbnail(self, icon_lbl, path):
        if not self._widget_is_valid(icon_lbl):
            return
        size = icon_lbl.width() or TendieRow.THUMB
        try:
            image = QImageReader(path).read()
            pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap(path)
            if pixmap.isNull():
                return
            scaled = pixmap.scaled(
                size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = (scaled.width() - size) // 2
            y = (scaled.height() - size) // 2
            icon_lbl.setPixmap(scaled.copy(x, y, size, size))
        except Exception:
            pass

    def _widget_is_valid(self, widget) -> bool:
        import shiboken6
        try:
            return shiboken6.isValid(widget)
        except RuntimeError:
            return False

    def _delete_tendie(self, tendie):
        from src.tweaks.tweaks import TweakID, tweaks
        if tendie in tweaks[TweakID.PosterBoard].tendies:
            tweaks[TweakID.PosterBoard].tendies.remove(tendie)
        self.refresh_tendies()

    def _reset_posterboard(self):
        c = ColorThemeManager.instance().colors
        from PySide6.QtWidgets import (
            QCheckBox,
            QDialog,
            QDialogButtonBox,
            QLabel,
            QMessageBox,
            QVBoxLayout,
        )

        dialog = QDialog(self.window)
        dialog.setWindowTitle(QCoreApplication.translate("Nugget", "Reset PosterBoard"))
        dialog.setMinimumWidth(350)
        dialog.setStyleSheet(f"""
            QDialog {{ background-color: {c.bg_primary}; }}
            QLabel {{ color: {c.text_primary}; font-size: 15px; }}
            QCheckBox {{ color: {c.text_primary}; font-size: 14px; spacing: 8px; }}
            QCheckBox::indicator {{ width: 20px; height: 20px; }}
            QDialogButtonBox QPushButton {{
                background-color: {c.accent};
                border-radius: 10px;
                color: {c.text_primary};
                font-size: 14px;
                font-weight: 600;
                padding: 10px 20px;
                border: none;
                min-width: 80px;
            }}
            QDialogButtonBox QPushButton:hover {{ background-color: {c.accent_hover}; }}
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        desc = QLabel(QCoreApplication.translate(
            "Nugget",
            "Select what to reset. This is useful if PosterBoard is behaving "
            "strangely or the database is corrupted (malformed) after a restore."
        ))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {c.text_secondary}; font-size: 13px; background-color: transparent;")
        layout.addWidget(desc)

        reset_full = QCheckBox(QCoreApplication.translate(
            "Nugget", "Full Reset (empty database, wipe everything)"))
        reset_full.setChecked(False)
        layout.addWidget(reset_full)

        reset_collections = QCheckBox(QCoreApplication.translate("Nugget", "Collections"))
        reset_collections.setChecked(True)
        layout.addWidget(reset_collections)

        reset_suggested = QCheckBox(QCoreApplication.translate("Nugget", "Suggested Photos"))
        reset_suggested.setChecked(True)
        layout.addWidget(reset_suggested)

        reset_gallery = QCheckBox(QCoreApplication.translate("Nugget", "Gallery Cache"))
        reset_gallery.setChecked(True)
        layout.addWidget(reset_gallery)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)

        if dialog.exec() == QDialog.Accepted:
            if reset_full.isChecked():
                tweaks[TweakID.PosterBoard].full_reset = True
                tweaks[TweakID.PosterBoard].resetModes = []
                QMessageBox.information(
                    self.window,
                    QCoreApplication.translate("Nugget", "Reset Scheduled"),
                    QCoreApplication.translate(
                        "Nugget",
                        "A full PosterBoard reset has been scheduled. The "
                        "entire container will be wiped and an empty database "
                        "restored on the next apply. Apply your tweaks to "
                        "execute the reset."))
                return
            selected = []
            if reset_collections.isChecked():
                selected.append("Collections")
            if reset_suggested.isChecked():
                selected.append("Suggested Photos")
            if reset_gallery.isChecked():
                selected.append("Gallery Cache")
            tweaks[TweakID.PosterBoard].resetModes = selected
            QMessageBox.information(
                self.window,
                QCoreApplication.translate("Nugget", "Reset Scheduled"),
                QCoreApplication.translate(
                    "Nugget",
                    "PosterBoard reset has been scheduled. The selected items "
                    "will be cleared on the next apply. Apply your tweaks to "
                    "execute the reset.")
            )
