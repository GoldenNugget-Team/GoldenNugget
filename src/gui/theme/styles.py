"""Component stylesheet templates with ``{slot}`` placeholders.

Usage::

    from src.gui.theme.styles import STYLES
    widget.setStyleSheet(STYLES["card"].format_map(theme.colors.__dict__))
"""


# Single UI font used on every platform. The bundled variable font
# (src/qt/fonts/InterVariable.ttf + InterVariable-Italic.ttf) is registered at
# startup in main_app.py; the global stylesheet pins it here so Designer
# hardcoded families (e.g. .AppleSystemUIFont) can never leak in.
FONT_FAMILY = "Inter Variable"


STYLES = {
    # ---- Components ------------------------------------------------------
    "text_input_dialog": """
        QDialog {{ background-color: {bg_elevated}; }}
        QLabel {{ color: {text_primary}; font-size: 15px; }}
        QLineEdit {{
            background-color: {bg_input};
            border: none;
            border-radius: 10px;
            color: {text_primary};
            font-size: 15px;
            padding: 12px 16px;
        }}
        QPushButton {{
            background-color: {accent};
            border-radius: 10px;
            color: {text_inverse};
            font-size: 15px;
            font-weight: 600;
            padding: 12px 24px;
            border: none;
            min-width: 80px;
        }}
        QPushButton:hover {{ background-color: {accent_hover}; }}
    """,

    "number_input_dialog": """
        QDialog {{ background-color: {bg_elevated}; }}
        QLabel {{ color: {text_primary}; font-size: 15px; }}
        QSpinBox {{
            background-color: {bg_input};
            border: none;
            border-radius: 10px;
            color: {text_primary};
            font-size: 15px;
            padding: 12px 16px;
        }}
        QSpinBox::up-button, QSpinBox::down-button {{ width: 0; }}
        QPushButton {{
            background-color: {accent};
            border-radius: 10px;
            color: {text_inverse};
            font-size: 15px;
            font-weight: 600;
            padding: 12px 24px;
            border: none;
            min-width: 80px;
        }}
        QPushButton:hover {{ background-color: {accent_hover}; }}
    """,

    "section_header": (
        "font-size: 13px; font-weight: 600; color: {text_secondary}; "
        "text-transform: uppercase; letter-spacing: 0.5px; padding-left: 4px;"
    ),

    # Header of an IOSCollapsibleSection: same look as a plain section header,
    # but it is a button and carries a chevron in its text.
    "collapsible_header": """
        QPushButton#iosCollapsibleHeader {{
            background: transparent;
            border: none;
            color: {text_secondary};
            font-size: 13px;
            font-weight: 600;
            text-align: left;
            padding: 10px 4px 10px 4px;
        }}
        QPushButton#iosCollapsibleHeader:hover {{ color: {text_primary}; }}
        QPushButton#iosCollapsibleHeader:checked {{ color: {text_primary}; }}
    """,

    "card": """
        IOSCard {{
            background-color: {bg_secondary};
            border-radius: 12px;
            border: none;
        }}
    """,

    "nav_bar": "background-color: {bg_secondary}; border-bottom: 1px solid {divider};",

    "nav_back_btn": """
        QPushButton {{
            background: transparent;
            color: {accent};
            font-size: 17px;
            font-weight: 400;
            border: none;
            padding: 8px 0;
        }}
        QPushButton:hover {{ color: {accent_hover}; }}
    """,

    "nav_title": "font-size: 17px; font-weight: 600; color: {text_primary};",

    "nav_right_btn": """
        QPushButton {{
            background: transparent;
            color: {accent};
            font-size: 15px;
            font-weight: 600;
            border: none;
            padding: 8px 0;
        }}
        QPushButton:hover {{ color: {accent_hover}; }}
    """,

    "settings_row": """
        QPushButton {{
            background-color: {bg_secondary};
            border-radius: 10px;
            color: {text_primary};
            font-size: 15px;
            text-align: left;
            padding: 14px 16px;
            border: none;
        }}
        QPushButton:hover {{ background-color: {surface_hover}; }}
    """,

    "primary_button": """
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 {accent}, stop:1 {accent_pressed});
            border-radius: 12px;
            color: {text_inverse};
            font-size: 17px;
            font-weight: 600;
            border: none;
        }}
        QPushButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 {accent_hover}, stop:1 {accent}); }}
        QPushButton:pressed {{ background-color: {accent_pressed}; }}
        QPushButton:disabled {{ background-color: {border}; color: {text_disabled}; }}
    """,

    "danger_button": """
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 {error}, stop:1 {error_pressed});
            border-radius: 12px;
            color: {text_inverse};
            font-size: 17px;
            font-weight: 600;
            border: none;
        }}
        QPushButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 {error_hover}, stop:1 {error}); }}
        QPushButton:pressed {{ background-color: {error_pressed}; }}
        QPushButton:disabled {{ background-color: {border}; color: {text_disabled}; }}
    """,

    "apply_preview_text": """
        QPlainTextEdit {{
            background-color: {bg_secondary}; color: {text_primary};
            border: 1px solid {border}; border-radius: 10px;
            padding: 12px; font-size: 14px;
            selection-background-color: {accent};
        }}
    """,

    "confirm_dialog": """
        QDialog {{ background-color: {bg_elevated}; }}
        QLabel {{ color: {text_primary}; font-size: 15px; background-color: transparent; }}
        QLabel#confirmTitle {{ font-size: 17px; font-weight: 700; color: {text_primary}; }}
        QLabel#confirmMuted {{ color: {text_secondary}; font-size: 13px; }}
        QLabel#confirmRow {{ font-size: 14px; color: {text_primary}; }}
        QPushButton {{
            background-color: {accent};
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 {accent}, stop:1 {accent_pressed});
            border-radius: 10px;
            color: {text_inverse};
            font-size: 15px;
            font-weight: 600;
            padding: 12px 24px;
            border: none;
            min-width: 110px;
        }}
        QPushButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 {accent_hover}, stop:1 {accent}); }}
        QPushButton#cancelBtn {{
            background-color: {bg_tertiary};
            color: {text_primary};
        }}
        QPushButton#cancelBtn:hover {{ background-color: {surface_hover}; }}
    """,

    # IOSSwitch paints its own track/knob (it animates the knob position and
    # fades the track color), so there is no switch stylesheet here.

    "value_label": "color: {text_secondary}; font-size: 14px;",

    # ---- Preset popup (home screen, opened from the preset banner) ------
    "preset_popup": """
        QFrame#presetPopup {{
            background-color: {bg_elevated};
            border: 1px solid {card_border};
            border-radius: 14px;
        }}
    """,

    # A preset row is a QPushButton holding labels, so the row's own text is
    # empty; [checked="true"] is how the selection is shown.
    "preset_row": """
        QPushButton#presetRow {{
            background-color: transparent;
            border: none;
            border-radius: 10px;
            text-align: left;
            padding: 0px;
        }}
        QPushButton#presetRow:hover {{ background-color: {surface_hover}; }}
        QPushButton#presetRow:checked {{
            background-color: {surface_hover};
            border: 1px solid {accent};
        }}
    """,

    "preset_mini_button": """
        QPushButton#presetMiniButton {{
            background-color: {surface_hover};
            color: {text_primary};
            border: none;
            border-radius: 8px;
            font-size: 13px;
            padding: 0px 10px;
        }}
        QPushButton#presetMiniButton:hover {{ background-color: {divider}; }}
        QPushButton#presetMiniButton:disabled {{ color: {text_disabled}; }}
    """,

    "preset_mini_danger": """
        QPushButton#presetMiniButton {{
            background-color: {error_hover};
            color: {text_inverse};
            border: none;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            padding: 0px 14px;
        }}
        QPushButton#presetMiniButton:hover {{ background-color: {error}; }}
        QPushButton#presetMiniButton:disabled {{
            background-color: {surface_hover};
            color: {text_disabled};
        }}
    """,

    # ---- Pages -----------------------------------------------------------
    "page_bg": "background-color: {bg_primary};",
    "scroll_area": "QScrollArea {{ background-color: {bg_primary}; border: none; }}",

    # ---- Settings --------------------------------------------------------
    "settings_list": """
        QListWidget {{
            background-color: {bg_secondary};
            color: {text_primary};
            border: none;
            border-radius: 8px;
            padding: 4px;
        }}
        QListWidget::item:selected {{
            background-color: {scrollbar_pressed};
            color: {text_inverse};
            border-radius: 6px;
        }}
    """,

    "mini_button": """
        QPushButton {{
            background-color: {bg_tertiary};
            border-radius: 8px;
            color: {text_primary};
            border: none;
            padding: 6px 12px;
            font-size: 13px;
        }}
        QPushButton:hover {{ background-color: {surface_hover}; }}
    """,

    "combo_dropdown": """
        QComboBox {{
            background-color: {bg_secondary};
            border: none;
            border-radius: 8px;
            color: {text_primary};
            padding: 8px 12px;
            font-size: 10.5pt;
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {bg_secondary};
            border: 1px solid {divider};
            selection-background-color: {accent};
            selection-color: {text_inverse};
            border-radius: 8px;
            padding: 4px;
        }}
    """,

    # ---- PosterBoard -----------------------------------------------------
    "tab_bar": "background-color: {bg_primary}; border-top: 1px solid {border};",

    "tab_button_inactive": "color: {text_secondary}; background: transparent; border: none; font-weight: 600; font-size: 14px;",
    "tab_button_active": "color: {accent}; background: transparent; border: none; font-weight: 600; font-size: 14px;",

    "add_icon": "background-color: {bg_secondary}; border: 2px dashed {divider}; border-radius: 12px; color: {accent}; font-size: 28px; font-weight: 300;",

    "tendie_preview_btn": """
        QToolButton {{
            background-color: {bg_secondary};
            color: {accent};
            border: 1px solid {divider};
            border-radius: 8px;
            padding: 6px 12px;
            font-size: 13px;
        }}
        QToolButton:hover {{ background-color: {surface_hover}; }}
    """,

    "tendie_delete_btn": """
        QToolButton {{
            background-color: {bg_secondary};
            color: {error};
            border: 1px solid {divider};
            border-radius: 8px;
            padding: 6px 12px;
            font-size: 13px;
        }}
        QToolButton:hover {{ background-color: {error}; color: {text_inverse}; }}
    """,

    "template_preview": "background-color: {bg_secondary}; border: 1px solid {divider}; border-radius: 12px;",

    "reset_pb_button": """
        QPushButton {{
            background-color: {bg_tertiary};
            border-radius: 8px;
            color: {error};
            border: none;
            padding: 10px 16px;
            font-size: 14px;
        }}
        QPushButton:hover {{ background-color: {surface_hover}; }}
    """,

    "download_card_icon": "background-color: {accent}; border-radius: 10px; color: white; font-size: 20px;",

    "thumb_button": """
        QPushButton {{
            background-color: {bg_secondary};
            color: {accent};
            border-radius: 8px;
            border: none;
            padding: 8px 16px;
            font-size: 14px;
        }}
        QPushButton:hover {{ background-color: {surface_hover}; }}
    """,

    # ---- Home ------------------------------------------------------------
    "home_title": "font-size: 32px; font-weight: 700; color: {text_primary};",
    "home_subtitle": "color: {text_secondary}; font-size: 14px;",

    "home_combo": """
        QComboBox {{
            background-color: {bg_secondary};
            border: none;
            border-radius: 10px;
            color: {text_primary};
            padding: 10px 14px;
            font-size: 10.5pt;
        }}
        QComboBox::drop-down {{ border: none; width: 24px; }}
        QComboBox QAbstractItemView {{
            background-color: {bg_secondary};
            selection-background-color: {accent};
            selection-color: {text_inverse};
            border: none;
        }}
    """,

    "home_icon_button": """
        QPushButton {{
            background-color: {bg_secondary};
            color: {text_primary};
            border-radius: 10px;
            border: none;
            font-size: 16px;
            padding: 10px;
        }}
        QPushButton:hover {{ background-color: {surface_hover}; }}
    """,

    # Home feature tile: one big icon with the feature name underneath, all
    # six tiles in one row. Replaces the old header+subtitle home cards. The
    # tile uses bg_tertiary (not bg_secondary) so it actually reads as a
    # raised tile against the page background, like the home screen mockup.
    "home_tile": """
        IOSCard {{
            background-color: {bg_tertiary};
            border-radius: 14px;
            border: 1px solid transparent;
        }}
        IOSCard:hover {{ border-color: {accent}; }}
    """,

    "home_tile_title": (
        "font-size: 16px; font-weight: 600; color: {text_primary}; "
        # a styled QLabel paints its palette window color by default, which
        # shows as a dark box on the raised tile — keep it transparent
        "background-color: transparent;"
    ),
    "home_tile_subtitle": (
        "color: {text_secondary}; font-size: 12px; "
        "background-color: transparent;"
    ),

    # ---- Session log viewer ----------------------------------------------
    # No font-family here on purpose: the app has ONE font (Inter, pinned by
    # the global template) and styles.py stays the only place that names a
    # family. The log view needs a fixed pitch to keep its pipe-separated
    # columns aligned, so the widget sets the platform fixed font in code
    # (see LogViewerDialog) instead.
    "log_viewer": """
        QDialog {{ background-color: {bg_elevated}; }}
        QLabel {{ color: {text_primary}; font-size: 14px; }}
        QLabel#logViewerTitle {{ font-size: 17px; font-weight: 700; color: {text_primary}; }}
        QLabel#logViewerPath {{
            color: {text_secondary}; font-size: 11px;
            background-color: transparent;
        }}
        QLabel#logViewerStatus {{
            color: {text_secondary}; font-size: 12px;
            background-color: transparent;
        }}
        QPlainTextEdit {{
            background-color: {bg_input};
            border: none;
            border-radius: 10px;
            color: {text_primary};
            font-size: 12px;
            padding: 10px 12px;
            selection-background-color: {accent};
            selection-color: {text_inverse};
        }}
        QLineEdit {{
            background-color: {bg_input};
            border: none;
            border-radius: 10px;
            color: {text_primary};
            font-size: 14px;
            padding: 8px 12px;
        }}
        QComboBox {{
            background-color: {bg_input};
            border: none;
            border-radius: 10px;
            color: {text_primary};
            padding: 8px 12px;
            font-size: 13px;
        }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
        QComboBox QAbstractItemView {{
            background-color: {bg_secondary};
            border: 1px solid {divider};
            selection-background-color: {accent};
            selection-color: {text_inverse};
            border-radius: 8px;
            padding: 4px;
        }}
        QPushButton {{
            background-color: {bg_tertiary};
            border-radius: 10px;
            color: {text_primary};
            border: none;
            font-size: 14px;
            padding: 8px 16px;
        }}
        QPushButton:hover {{ background-color: {surface_hover}; }}
        QPushButton#logViewerPrimary {{
            background-color: {accent};
            color: {text_inverse};
            font-weight: 600;
        }}
        QPushButton#logViewerPrimary:hover {{ background-color: {accent_hover}; }}
    """,

    "process_status_green": "color: {success}; font-size: 14px; font-weight: 500;",
    "process_status_red": "color: {error}; font-size: 14px; font-weight: 500;",
    "process_status_blue": "color: {accent}; font-size: 14px; font-weight: 500;",

    # ---- Daemons ---------------------------------------------------------
    "safety_note": "color: {danger_text}; font-size: 12px; font-style: italic;",

    # ---- Wallpaper downloader ---------------------------------------------
    "wp_card": """
        QFrame {{
            background-color: {bg_secondary};
            border-radius: 12px;
            border: none;
        }}
        QFrame:hover {{ background-color: {surface_hover}; }}
    """,

    "wp_name": "color: {text_primary}; font-size: 13px; font-weight: 600;",
    "wp_author": "color: {text_secondary}; font-size: 11px;",
    "wp_preview_bg": "background-color: {bg_tertiary};",
    "wp_loading_bg": "background-color: {bg_tertiary};",
    "wp_loading_text": "color: {text_disabled}; font-size: 12px;",

    "dialog_progress_bar": """
        QProgressBar {{
            background-color: {bg_tertiary};
            border: none;
            border-radius: 4px;
            height: 8px;
        }}
        QProgressBar::chunk {{
            background-color: {accent};
            border-radius: 4px;
        }}
    """,

    # ---- About dialog ----------------------------------------------------
    "about_separator": "background-color: {divider};",
    "about_desc": "color: {text_secondary}; font-size: 14px;",
    "about_credit_title": "color: {text_secondary}; font-size: 13px; font-weight: 600;",
    "about_link": "color: {accent}; font-size: 14px; border: none; background: transparent;",
    "about_link_hover": "color: {accent_hover}; font-size: 14px; border: none; background: transparent;",

    # ---- Interface picker ------------------------------------------------
    "picker_frame": """
        QFrame {{
            background-color: {bg_secondary};
            border-radius: 12px;
            border: 2px solid transparent;
        }}
        QFrame:hover {{ border-color: {accent}; }}
    """,

    # ---- Classic chrome (device bar) -------------------------------------

    "classic_bordered_btn": """
        QToolButton {{
            background: none;
            border: 1px solid {divider};
            color: {text_primary};
        }}
        QToolButton:hover {{
            background-color: {surface_hover};
        }}
        QToolButton:pressed {{
            background-color: {surface_hover};
            color: {text_primary};
        }}
    """,

    # ---- Global (main window stylesheet) ---------------------------------
    "global": """
        QWidget {{ color: {text_primary}; background-color: transparent; spacing: 0px; font-family: '{font_family}'; }}
        QWidget:focus {{ outline: none; }}
        QWidget[cls=central] {{ background-color: {bg_primary}; border-radius: 0px; border: 1px solid {divider}; }}
        QLabel {{ font-size: 14px; }}
        QToolButton {{ background-color: {scrollbar}; border: none; color: {text_primary}; font-size: 14px; min-height: 35px; icon-size: 16px; padding-left: 10px; padding-right: 10px; border-radius: 8px; }}
        QToolButton[cls=sidebarBtn] {{ background-color: transparent; icon-size: 24px; }}
        QToolButton:pressed {{ background-color: {scrollbar_pressed}; color: {text_primary}; }}
        QToolButton:checked {{ background-color: {accent}; color: {text_inverse}; }}
        QCheckBox {{ spacing: 8px; font-size: 14px; }}
        QRadioButton {{ spacing: 8px; font-size: 14px; }}
        QLineEdit {{ border: none; background-color: transparent; color: {text_primary}; font-size: 14px; }}
        QScrollBar:vertical {{ background: transparent; width: 8px; }}
        QScrollBar:horizontal {{ background: transparent; height: 8px; }}
        QScrollBar::handle {{ background: {scrollbar}; border-radius: 4px; }}
        QScrollBar::handle:pressed {{ background: {scrollbar_pressed}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ background: none; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
        QSlider::groove:horizontal {{ background-color: {scrollbar}; height: 4px; border-radius: 2px; }}
        QSlider::handle:horizontal {{ background-color: {scrollbar_pressed}; width: 8px; border-radius: 4px; }}
        QSlider::handle:horizontal:pressed {{ background-color: {accent}; }}
        QSlider::tick:horizontal {{ background-color: {scrollbar_pressed}; width: 1px; }}
    """,
}
