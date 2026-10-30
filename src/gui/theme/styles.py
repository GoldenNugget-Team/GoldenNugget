"""Component stylesheet templates with ``{slot}`` placeholders.

Usage::

    from src.gui.theme import t
    widget.setStyleSheet(t("card"))
"""


# Single UI font used on every platform. The bundled variable font
# (src/qt/fonts/InterVariable.ttf + InterVariable-Italic.ttf) is registered at
# startup in main_app.py; the global stylesheet pins it here so Designer
# hardcoded families (e.g. .AppleSystemUIFont) can never leak in.
FONT_FAMILY = "Inter Variable"


STYLES = {
    "templates_builder_title": "font-size: 16px; font-weight: 600; color: {text_primary}; background-color: transparent;",
    "templates_caption": "font-size: 12px; color: {text_secondary}; background-color: transparent;",
    "templates_builder_icon": "background-color: {accent}; border-radius: 12px; font-size: 24px; color: {text_inverse};",
    "templates_builder_chevron": "font-size: 26px; color: {text_secondary}; background-color: transparent;",
    "tweak_row_description": "color: {text_secondary}; font-size: 13px; background-color: transparent;",
    "tweak_row_label": "color: {text_primary}; font-size: 15px; background-color: transparent;",
    "onboarding_dialog": """
        QDialog {{ background-color: {bg_primary}; }}
        QLabel {{ color: {text_primary}; background-color: transparent; border: none; }}
    """,
    "onboarding_title": "font-size: 24px; font-weight: 700; color: {text_primary}; background-color: transparent;",
    "onboarding_description": "font-size: 13px; color: {text_secondary}; background-color: transparent; border: none;",
    "onboarding_option_title": "font-size: 18px; font-weight: 600; color: {text_primary}; background-color: transparent; border: none;",
    "onboarding_preview": "background-color: transparent; border: none;",
    "onboarding_badge": "color: {accent}; background-color: transparent; border: none; font-size: 11px; font-weight: 700;",
    "onboarding_choice": """
        QPushButton#interfaceChoice {{ background-color: {bg_secondary}; border: 2px solid {border}; border-radius: 16px; text-align: left; }}
        QPushButton#interfaceChoice:hover {{ background-color: {surface_hover}; }}
        QPushButton#interfaceChoice:checked {{ border-color: {accent}; }}
        QPushButton#interfaceChoice:focus {{ border-color: {accent}; }}
    """,
    "onboarding_continue": """
        QPushButton {{ background-color: {accent}; color: {text_inverse}; border: none; border-radius: 10px; padding: 12px 22px; font-size: 14px; font-weight: 600; }}
        QPushButton:hover {{ background-color: {accent_hover}; }}
        QPushButton:focus {{ border: 2px solid {text_primary}; padding: 10px 20px; }}
    """,
    "accent_swatch": """
        QPushButton {{ background-color: {swatch}; border-radius: 16px;
                       border: 3px solid transparent; }}
        QPushButton:hover, QPushButton:focus {{ border-color: {text_secondary}; }}
        QPushButton:checked {{ border-color: {text_primary}; }}
    """,
    # ---- Components ------------------------------------------------------
    "text_input_dialog": """
        QDialog {{ background-color: {bg_elevated}; }}
        QLabel {{ color: {text_primary}; font-size: 15px; }}
        QLineEdit {{
            background-color: {bg_input};
            border: 1px solid {border};
            border-radius: 10px;
            color: {text_primary};
            font-size: 15px;
            padding: 12px 16px;
            selection-background-color: {accent};
            selection-color: {text_inverse};
        }}
        QLineEdit:focus {{ border-color: {accent}; }}
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
        QSpinBox, QDoubleSpinBox {{
            background-color: {bg_input};
            border: 1px solid {border};
            border-radius: 10px;
            color: {text_primary};
            font-size: 15px;
            padding: 10px 14px;
        }}
        QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {accent}; }}
        QSpinBox QLineEdit, QDoubleSpinBox QLineEdit {{
            background: transparent;
            border: none;
            border-radius: 0;
            color: {text_primary};
            font-size: 15px;
            padding: 0;
            margin: 0;
            min-height: 0;
            selection-background-color: {accent};
            selection-color: {text_inverse};
        }}
        QSpinBox::up-button, QSpinBox::down-button,
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; }}
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

    "number_input_field": """
        QSpinBox, QDoubleSpinBox {{ background-color: {bg_input}; color: {text_primary};
            border: 1px solid {border}; border-radius: 10px;
            font-size: 15px; padding: 12px 16px; }}
    """,

    "section_header": (
        "font-size: 13px; font-weight: 600; color: {text_secondary}; "
        "text-transform: uppercase; letter-spacing: 0.5px; padding-left: 4px; background-color: transparent;"
    ),

    # Header of an IOSCollapsibleSection: same look as a plain section header,
    # but it is a button and carries a chevron in its text.
    "collapsible_header": """
        QPushButton#iosCollapsibleHeader {{
            background: transparent;
            border: none;
            color: {text_primary};
            font-size: 14px;
            font-weight: 650;
            text-align: left;
            padding: 9px 6px;
        }}
        QPushButton#iosCollapsibleHeader:hover {{ background: transparent; }}
        QPushButton#iosCollapsibleHeader:checked {{ color: {text_primary}; }}
        QPushButton#iosCollapsibleHeader:focus {{ color: {accent}; }}
    """,

    "card": """
        IOSCard {{
            background-color: {bg_secondary};
            border-radius: 14px;
            border: 1px solid {border};
        }}
        IOSCard QLabel {{ background-color: transparent; }}
    """,

    "nav_bar": """
        QWidget#iosNavBar {{
            background-color: {bg_secondary};
            border: 1px solid {divider};
            border-radius: 14px;
        }}
    """,

    "nav_back_btn": """
        QPushButton {{
            background: {bg_tertiary};
            color: {text_primary};
            font-size: 28px;
            border: none;
            border-radius: 10px;
            padding: 0px;
        }}
        QPushButton:hover {{ background: {surface_hover}; }}
    """,

    "nav_title": "font-size: 20px; font-weight: 600; color: {text_primary}; background: transparent;",

    "nav_category": """
        QPushButton {{
            background: transparent;
            border: none;
            border-radius: 8px;
            padding: 0px 12px;
            color: {text_secondary};
            font-size: 13px;
            font-weight: 500;
        }}
        QPushButton:hover {{ background: {bg_tertiary}; color: {text_primary}; }}
        QPushButton:checked {{ background: {bg_tertiary}; color: {accent}; }}
    """,

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

    "value_row": """
        QPushButton#iosValueRow {{ background: transparent; border: none; padding: 0px; }}
        QLabel#valueRowTitle {{ color: {text_primary}; font-size: 15px; background: transparent; }}
        QLabel#valueRowValue {{ color: {text_secondary}; font-size: 13px; background: transparent; }}
        QLabel#valueRowArrow {{ color: {text_secondary}; font-size: 22px; background: transparent; }}
    """,

    "settings_action": """
        QPushButton {{
            background-color: {bg_secondary};
            border: 1px solid {border};
            border-radius: 14px;
            color: {text_primary};
            text-align: left;
            font-size: 15px;
            font-weight: 500;
            padding: 10px 16px;
        }}
        QPushButton:hover {{ background-color: {bg_tertiary}; }}
        QPushButton:focus {{ border-color: {accent}; }}
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

    "search_clear_button": """
        QToolButton {{ background: transparent; border: none; border-radius: 8px;
            padding: 0px; margin: 0px; min-width: 0px; min-height: 0px; }}
        QToolButton:hover, QToolButton:focus {{ background: {surface_hover}; }}
        QToolButton:pressed {{ background: {border}; }}
    """,
    "list_search": """
        QLineEdit {{
            background-color: {bg_secondary}; color: {text_primary};
            border: 1px solid {border}; border-radius: 12px;
            padding: 0px 12px; font-size: 14px;
            selection-background-color: {accent};
        }}
        QLineEdit:focus {{ border-color: {text_secondary}; }}
    """,
    "segmented_filter": """
        QWidget#iosSegmentedFilter {{
            background-color: {bg_secondary}; border: 1px solid {border}; border-radius: 12px;
        }}
        QWidget#iosSegmentedFilter QPushButton {{
            background: transparent; border: none; border-radius: 8px;
            padding: 0px 12px; color: {text_secondary}; font-size: 13px; font-weight: 500;
        }}
        QWidget#iosSegmentedFilter QPushButton:hover {{ color: {text_primary}; }}
        QWidget#iosSegmentedFilter QPushButton:checked {{
            background: {bg_tertiary}; color: {text_primary}; font-weight: 600;
        }}
    """,
    "list_search_empty": """
        color: {text_secondary}; background-color: transparent;
        font-size: 14px; padding: 12px;
    """,

    "support_panel": """
            QLabel#supportTitle {{ color: {text_primary}; background: transparent; font-size: 19px; font-weight: 600; }}
            QLabel#supportMuted {{ color: {text_secondary}; background: transparent; font-size: 12px; }}
            QLabel#supportCredit {{ color: {text_primary}; background: transparent; font-size: 13px; }}
            QToolButton#supportLink {{ background: {bg_tertiary}; border: 1px solid {border}; border-radius: 14px; }}
            QToolButton#supportLink:hover {{ border-color: {accent}; background: {surface_hover}; }}
            QWidget#supportProfile {{ background: transparent; border: none; }}
            QToolButton#supportAvatar {{ background: transparent; border: none; padding: 2px; }}
            QPushButton#supportName {{ background: transparent; color: {text_primary}; font-size: 17px; font-weight: 600; border: none; padding: 5px; }}
            QPushButton#supportName:hover {{ color: {accent}; }}
            """,

    "restore_progress": """
        QWidget#restoreConnection {{ background: {bg_tertiary}; border: none; border-left: 3px solid {warning}; border-radius: 8px; }}
        QLabel#restoreConnectionIcon {{ background: transparent; }}
        QLabel#restoreConnectionDetail {{ color: {text_secondary}; font-size: 13px; background: transparent; }}
        QLabel#restoreWarning {{ color: {text_primary}; font-size: 15px; font-weight: 600; background: transparent; }}
        QLabel#restorePercent {{ color: {text_primary}; font-size: 18px; font-weight: 600; }}
        QLabel#restoreTime {{ color: {text_primary}; font-size: 16px; font-weight: 600; }}
        QLabel#restorePhase {{ color: {text_primary}; font-size: 18px; font-weight: 600; }}
        QLabel#restoreStatus {{ color: {text_primary}; font-size: 14px; }}
        QLabel#restoreMuted {{ color: {text_secondary}; font-size: 12px; }}
        QWidget#restoreStep {{ background: {bg_tertiary}; border: 1px solid {border}; border-radius: 12px; }}
        QWidget#restoreStep[state="active"] {{ border-color: {accent}; }}
        QLabel#restoreStepTitle {{ color: {text_secondary}; font-size: 12px; background: transparent; }}
    """,

    "device_support_dialog": """
        QDialog {{ background: {bg_primary}; }}
        QScrollArea#compatScroll, QWidget#compatContent {{ background: transparent; border: none; }}
        QLabel#compatTitle {{ color: {text_primary}; font-size: 22px; font-weight: 600; }}
        QLabel#compatDevice {{ color: {text_primary}; font-size: 17px; font-weight: 600; }}
        QLabel#compatBody {{ color: {text_primary}; font-size: 14px; }}
        QLabel#compatMuted {{ color: {text_secondary}; font-size: 13px; }}
        QLabel#compatSection {{ color: {text_primary}; font-size: 15px; font-weight: 600; }}
        QLabel#compatCount {{ color: {text_primary}; font-size: 23px; font-weight: 600; }}
        QLabel#compatWarning {{ color: {warning}; font-size: 13px; }}
        QLabel#compatBadge {{
            background: {bg_tertiary}; color: {success};
            border: 1px solid {border}; border-radius: 10px;
            padding: 6px 10px; font-size: 12px; font-weight: 600;
        }}
        QLabel#compatBadge[supportState="limited"] {{ color: {warning}; }}
        QLabel#compatBadge[supportState="unsupported"] {{ color: {error}; }}
    """,

    "summary_dialog": """
        QLabel#confirmTitle {{ font-size: 22px; }}
        QPushButton {{ background-image: none; }}
        QPushButton:disabled {{ background: {bg_tertiary}; color: {text_disabled}; }}
        QCheckBox {{ color: {text_primary}; font-size: 14px; background: transparent; spacing: 10px; }}
        QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px;
            border: 1.5px solid {text_secondary}; background: {bg_input}; }}
        QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
    """,
    "reset_dialog": """
        QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
        QPushButton#resetSelection {{
            background: {bg_secondary}; color: {text_primary};
            border: 1px solid {border}; border-radius: 12px;
            text-align: left; padding: 12px 16px;
        }}
        QPushButton#resetSelection:hover {{ background: {bg_tertiary}; }}
        QPushButton#resetSelection:checked {{
            background: {bg_tertiary}; border-color: {accent}; color: {accent};
        }}
        QPushButton:disabled {{ background: {bg_secondary}; color: {text_disabled}; }}
    """,

    "app_list_dialog": """
            QDialog {{ background-color: {bg_elevated}; }}
            QLabel {{ color: {text_primary}; font-size: 14px; }}
            QLineEdit {{
                background-color: {bg_input};
                border: none;
                border-radius: 10px;
                color: {text_primary};
                font-size: 14px;
                padding: 10px 12px;
            }}
            QListWidget {{
                background-color: {bg_secondary};
                border: none;
                border-radius: 10px;
                color: {text_primary};
                font-size: 14px;
                padding: 6px;
            }}
            QListWidget::item {{ padding: 8px 12px; border: 1px solid {border}; border-radius: 12px; }}
            QListWidget::item:selected {{ background-color: {bg_tertiary}; border-color: {accent}; color: {text_primary}; }}
            QPushButton {{
                background-color: {accent};
                border: none;
                border-radius: 10px;
                color: {text_inverse};
                font-size: 14px;
                font-weight: 600;
                padding: 10px 16px;
            }}
            QPushButton:hover {{ background-color: {accent_hover}; }}
            QPushButton:disabled {{ background-color: {scrollbar}; color: {text_disabled}; }}
                QLabel#appListTitle {{ color: {text_primary}; font-size: 22px; font-weight: 600; }}
        QPushButton#appListClose {{ background-color: {surface_hover}; color: {text_primary}; }}
    """,

    "mobile_helper_dialog": """
        QDialog {{ background-color: {bg_elevated}; }}
        QLabel {{ color: {text_primary}; font-size: 14px; background-color: transparent; }}
        QLabel#mhTitle {{ font-size: 22px; font-weight: 600; }}
        QLabel#mhIntro {{ color: {text_secondary}; }}
        QLabel#mhHint {{ color: {text_secondary}; font-size: 12px; }}
        QLabel#mhStatus {{
            color: {text_primary}; font-size: 14px;
            background-color: {bg_secondary}; border: 1px solid {border};
            border-radius: 10px; padding: 10px 12px;
        }}
        QPushButton {{
            background-color: {bg_secondary}; border: 1px solid {border};
            border-radius: 10px; color: {text_primary}; font-size: 14px;
            font-weight: 600; padding: 10px 14px;
        }}
        QPushButton:hover {{ background-color: {bg_tertiary}; }}
        QPushButton:disabled {{ color: {text_disabled}; background-color: {bg_secondary}; }}
        QPushButton#mhPrimary, QPushButton#mhAction {{
            background-color: {accent}; border: none; color: {text_inverse};
        }}
        QPushButton#mhPrimary:hover, QPushButton#mhAction:hover {{ background-color: {accent_hover}; }}
        QPushButton#mhClose {{ background-color: {surface_hover}; border: none; }}
    """,

    "confirmation_dialog": """
        QDialog#themedConfirmation {{ background-color: {bg_primary}; }}
        QLabel#confirmationTitle {{ color: {text_primary}; font-size: 20px; font-weight: 600; background: transparent; }}
        QLabel#confirmationSubject {{ color: {text_primary}; font-size: 16px; font-weight: 600; background: transparent; }}
        QLabel#confirmationMessage {{ color: {text_secondary}; font-size: 14px; background: transparent; }}
        QPushButton#confirmationCancel {{
            background-color: {bg_secondary}; border: 1px solid {border}; border-radius: 12px;
            color: {text_primary}; font-size: 15px; font-weight: 600; padding: 0px 18px;
        }}
        QPushButton#confirmationCancel:hover {{ background-color: {bg_tertiary}; }}
        QPushButton#confirmationCancel:focus {{ border-color: {accent}; }}
        QPushButton#confirmationAction {{
            background-color: {accent}; border: none; border-radius: 12px;
            color: {text_inverse}; font-size: 15px; font-weight: 600; padding: 0px 18px;
        }}
        QPushButton#confirmationAction:hover {{ background-color: {accent_hover}; }}
        QPushButton#confirmationAction[destructive="true"] {{ background-color: {error}; }}
        QPushButton#confirmationAction[destructive="true"]:hover {{ background-color: {error_hover}; }}
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

    "row_title": "color: {text_primary}; font-size: 15px; background-color: transparent;",
    "muted_caption": "color: {text_secondary}; font-size: 13px; background-color: transparent;",
    "small_hint": "color: {text_secondary}; font-size: 12px; background-color: transparent;",
    "edit_hint": "color: {accent}; font-size: 17px; background-color: transparent;",
    "value_label": "color: {text_secondary}; font-size: 14px; background-color: transparent;",

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
            color: {text_primary};
            border-radius: 6px;
        }}
    """,

    "apply_preview_table": """
        QTreeWidget {{ background: {bg_input}; color: {text_primary}; border: 1px solid {border}; border-radius: 10px; }}
        QTreeWidget::item {{ padding: 8px 4px; }}
        QTreeWidget::item:selected {{ background: {surface_hover}; color: {text_primary}; }}
        QHeaderView::section {{ background: {bg_tertiary}; color: {text_secondary}; border: none; padding: 10px; }}
    """,

    "tweak_info_scroll": """
        QScrollArea, QWidget#tweakInfoContent {{ background-color: {bg_elevated}; border: none; }}
    """,

    "tweak_favorite_button": """
        QPushButton {{
            background: transparent;
            color: {text_secondary};
            border: none;
            border-radius: 13px;
            padding: 0px;
        }}
        QPushButton:checked {{
            background: {surface_hover};
        }}
        QPushButton:hover {{ background: {surface_hover}; }}
    """,

    "tweak_info_button": """
        QPushButton {{
            background: transparent;
            color: {text_secondary};
            border: none;
            border-radius: 13px;
            padding: 0px;
        }}
        QPushButton:hover {{
            background: {surface_hover};
            color: {text_primary};
        }}
    """,

    "maintenance_button": """
        QPushButton {{
            background-color: {scrollbar};
            border: none;
            border-radius: 10px;
            color: {error};
            font-size: 15px;
            font-weight: 600;
            padding: 12px 16px;
        }}
        QPushButton:hover {{ background-color: {surface_hover}; }}
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

    "mini_button_danger": """
        QPushButton {{
            background-color: {bg_tertiary};
            border-radius: 8px;
            color: {error};
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

    "download_card_icon": "background-color: {accent}; border-radius: 10px; color: {text_inverse}; font-size: 20px;",

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
    "home_title": "font-size: 32px; font-weight: 700; color: {text_primary}; background-color: transparent;",
    "home_subtitle": "color: {text_secondary}; font-size: 13px; font-weight: 500; background: transparent;",

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

    "home_tile": """
        IOSCard {{
            background-color: {bg_tertiary};
            border-radius: 14px;
            border: 1px solid transparent;
        }}
        IOSCard QLabel {{ background-color: transparent; }}
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
    "about_dialog": """
        QDialog {{ background-color: {bg_elevated}; }}
        QLabel {{ color: {text_primary}; background-color: transparent; }}
        QDialogButtonBox QPushButton {{ background-color: {accent}; color: {text_inverse};
            border: none; border-radius: 10px; padding: 10px 24px; font-size: 15px; font-weight: 600; }}
        QDialogButtonBox QPushButton:hover {{ background-color: {accent_hover}; }}
    """,
    "about_version": "color: {text_secondary}; font-size: 15px; background: transparent;",
    "about_description": "color: {text_secondary}; font-size: 15px; padding: 0 20px; background: transparent;",
    "about_credit_heading": "font-size: 17px; font-weight: 600; color: {text_primary}; padding-top: 8px; background: transparent;",
    "about_credit_role": "color: {text_secondary}; font-size: 14px; font-weight: 500; min-width: 160px; background: transparent;",
    "about_credit_name": """
        QToolButton {{ color: {accent}; font-size: 14px; background: transparent; border: none; padding: 0; text-align: left; }}
        QToolButton:hover {{ color: {accent_hover}; text-decoration: underline; }}
    """,
    "about_footer_link": """
        QToolButton {{ color: {accent}; font-size: 14px; font-weight: 500; background: transparent; border: none; padding: 4px 8px; }}
        QToolButton:hover {{ color: {accent_hover}; text-decoration: underline; }}
    """,
    "about_credits_scroll": """
        QScrollArea, QWidget {{ background: transparent; border: none; }}
        QScrollBar:vertical {{ width: 6px; background: transparent; }}
        QScrollBar::handle {{ background: {border}; border-radius: 3px; min-height: 30px; }}
    """,

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
        QToolTip {{ color: {text_primary}; background-color: {bg_elevated}; border: 1px solid {divider}; border-radius: 6px; padding: 6px 8px; }}
        QWidget[cls=central] {{ background-color: {bg_primary}; border-radius: 0px; border: 1px solid {divider}; }}
        QLabel {{ font-size: 14px; background-color: transparent; }}
        QDialog {{ background-color: {bg_elevated}; }}
        QToolTip {{ background-color: {bg_elevated}; color: {text_primary}; border: 1px solid {border}; }}
        QMenu {{ background-color: {bg_elevated}; color: {text_primary}; border: 1px solid {border}; }}
        QMenu::item:selected {{ background-color: {accent}; color: {text_inverse}; }}
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
