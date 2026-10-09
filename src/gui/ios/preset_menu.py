"""Animated preset popup + the shared preset actions.

Two things live here:

* The *actions* (``load_preset_flow`` and friends). They all take a preset
  **name** and are the single implementation of what a preset action does
  (confirm dialogs, safety-rule warnings, restart). Both the Settings page
  (``IOSSettingsPage``) and the home-screen popup call into them, so the two
  entry points can never drift apart.
* ``PresetPopup`` — the frameless panel that slides open under the preset
  banner's *Manage* button. It lists every preset, lets the user pick one, and
  exposes the full action set, with *Delete* pinned to the far right.
"""

import os
import sys
import weakref
from typing import Optional

from PySide6.QtCore import (
    Qt, QCoreApplication, QObject, QEvent, QPoint, QRect,
    QPropertyAnimation, QEasingCurve, Signal,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QGraphicsOpacityEffect, QSizePolicy,
    QMessageBox, QFileDialog, QDialog,
)

from src.gui.theme import ColorThemeManager, t
from src.gui.ios.components import _auto_retheme
from src.controllers.preset_manager import PresetManager
from src.controllers.hotload import HotLoad, confirm_flagged

# _ = translate
_T = QCoreApplication.translate

ANIM_MS = 170
POPUP_WIDTH = 340
MAX_VISIBLE_ROWS = 6
# one preset row plus the gap below it
ROW_H = 56
SLIDE_PX = 8


def restart_app():
    """Relaunch the app so freshly loaded settings take effect."""
    os.execl(sys.executable, sys.executable, *sys.argv)


# ---------------------------------------------------------------------------
# display helpers
# ---------------------------------------------------------------------------

def preset_subtitle(meta: dict) -> str:
    """One-line secondary text for a preset row: device, iOS, tags."""
    if not meta:
        return ""
    model = meta.get("device_model") or "Unknown"
    ios = meta.get("ios_version") or "Unknown"
    text = _T("Nugget", "{0} • iOS {1}").format(model, ios)
    tags = meta.get("tags") or []
    if tags:
        text += "  #" + " #".join(tags)
    return text


def _major_version(ver: str):
    try:
        return int(str(ver).split(".")[0])
    except (ValueError, TypeError, IndexError):
        return None


def _device_type(model: str) -> str:
    model = str(model or "")
    if model.lower().startswith("iphone"):
        return "iPhone"
    if model.lower().startswith("ipad"):
        return "iPad"
    return ""


def daemon_compat_warning(name: str, meta, window) -> Optional[str]:
    """Warn when a preset's daemons were saved for a different device/iOS."""
    pm = PresetManager()
    if not pm.preset_has_daemon_changes(name):
        return None
    dm = window.device_manager
    cur_ver = dm.get_current_device_version() or ""
    cur_model = dm.get_current_device_model() or ""
    pr_ver = (meta.get("ios_version") or "") if meta else ""
    pr_model = (meta.get("device_model") or "") if meta else ""

    mismatches = []
    pr_major, cur_major = _major_version(pr_ver), _major_version(cur_ver)
    if pr_major is not None and cur_major is not None and pr_major != cur_major:
        mismatches.append(
            _T("Nugget", "iOS {0}x vs current iOS {1}x").format(pr_major, cur_major))
    pr_type, cur_type = _device_type(pr_model), _device_type(cur_model)
    if pr_type and cur_type and pr_type != cur_type:
        mismatches.append(
            _T("Nugget", "{0} vs current {1}").format(pr_type, cur_type))
    if not mismatches:
        return None
    return (
        _T("Nugget",
           "This preset contains daemon modifications that were saved for a "
           "different device:\n\n")
        + "\n".join("• " + m for m in mismatches)
        + "\n\n"
        + _T("Nugget",
             "Daemons are sensitive to the iOS version and device type, and "
             "applying incompatible ones can bootloop your device. "
             "Proceed with caution.")
    )


# ---------------------------------------------------------------------------
# actions (shared by the Settings page and the popup)
# ---------------------------------------------------------------------------

def load_preset_flow(parent, window, pm: PresetManager, name: str,
                     display_name: str = None) -> bool:
    """Confirm, safety-check, load *name*, then restart. True if loaded."""
    shown_name = display_name or name
    meta = pm.get_preset_metadata(name)
    desc = meta.get("description", "") if meta else ""
    model = meta.get("device_model", "Unknown") if meta else "Unknown"
    ios = meta.get("ios_version", "Unknown") if meta else "Unknown"
    confirm = QMessageBox.question(
        parent, _T("Nugget", "Load Preset"),
        _T("Nugget",
           "Load preset \"{0}\"?\n\nDescription: {1}\nDevice: {2} • iOS {3}"
           "\n\nThis will replace your current configuration.").format(
               shown_name, desc, model, ios))
    if confirm != QMessageBox.StandardButton.Yes:
        return False

    dm = window.device_manager
    hotload = HotLoad(getattr(window, "settings", None))
    hidden_feats = pm.preset_hidden_feature_names(
        name, hotload,
        device_version=dm.get_current_device_version(),
        device_model=dm.get_current_device_model())
    if hidden_feats:
        QMessageBox.warning(
            parent, _T("Nugget", "Hidden Features Skipped"),
            _T("Nugget",
               "This preset contains features that are currently hidden by "
               "the safety rules for this device:\n\n• {0}\n\n"
               "They will NOT be loaded, so applying may not match the "
               "preset's intended state.").format("\n• ".join(hidden_feats)))

    compat_msg = daemon_compat_warning(name, meta, window)
    if compat_msg:
        reply = QMessageBox.warning(
            parent, _T("Nugget", "Daemon Compatibility"), compat_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if reply != QMessageBox.StandardButton.Yes:
            return False

    if pm.preset_has_daemon_changes(name):
        rule = hotload.rule_for(
            "Daemons",
            device_version=dm.get_current_device_version(),
            device_model=dm.get_current_device_model())
        if rule is not None and not confirm_flagged(rule, parent):
            return False

    if not pm.load_preset(name):
        QMessageBox.critical(
            parent, _T("Nugget", "Load Preset"),
            _T("Nugget", "Failed to load the preset."))
        return False

    window.settings.setValue("last_loaded_preset", name)
    window._sync_settings()
    QMessageBox.information(
        parent, _T("Nugget", "Load Preset"),
        _T("Nugget",
           "Preset \"{0}\" loaded.\n\nGoldenNugget will now restart to "
           "apply the changes.").format(shown_name))
    restart_app()
    return True


def rollback_preset_flow(parent, window, pm: PresetManager) -> bool:
    """Load the snapshot captured before the last successful apply."""
    name = "__Rollback"
    if not os.path.isfile(pm.get_preset_path(name)):
        QMessageBox.information(
            parent, _T("Nugget", "Rollback Last Apply"),
            _T("Nugget", "There is no previous successful apply to roll back yet."))
        return False
    return load_preset_flow(
        parent, window, pm, name,
        display_name=_T("Nugget", "Previous applied state"))


def save_preset_flow(parent, window, pm: PresetManager,
                     name: str, desc: str = "") -> bool:
    name = (name or "").strip()
    if not name:
        QMessageBox.warning(
            parent, _T("Nugget", "Save Preset"),
            _T("Nugget", "Enter a name for this preset."))
        return False
    dm = window.device_manager
    if not pm.save_preset(
            name, desc, tags=[],
            device_model=dm.get_current_device_model() or "",
            ios_version=dm.get_current_device_version() or ""):
        QMessageBox.critical(
            parent, _T("Nugget", "Save Preset"),
            _T("Nugget", "Failed to save the preset."))
        return False
    return True


def delete_preset_flow(parent, pm: PresetManager, name: str) -> bool:
    if not name:
        QMessageBox.warning(
            parent, _T("Nugget", "Delete Preset"),
            _T("Nugget", "Select a preset to delete first."))
        return False
    confirm = QMessageBox.question(
        parent, _T("Nugget", "Delete Preset"),
        _T("Nugget", "Delete preset \"{0}\"?").format(name))
    if confirm != QMessageBox.StandardButton.Yes:
        return False
    if not pm.delete_preset(name):
        QMessageBox.critical(
            parent, _T("Nugget", "Delete Preset"),
            _T("Nugget", "Failed to delete the preset."))
        return False
    return True


def export_preset_flow(parent, pm: PresetManager, name: str) -> bool:
    if not name:
        QMessageBox.warning(
            parent, _T("Nugget", "Export Preset"),
            _T("Nugget", "Select a preset to export first."))
        return False
    file_path, _ = QFileDialog.getSaveFileName(
        parent, _T("Nugget", "Export Preset"), f"{name}.json",
        _T("Nugget", "JSON Files (*.json)"))
    if not file_path:
        return False
    if not pm.export_preset(name, file_path):
        QMessageBox.critical(
            parent, _T("Nugget", "Export Preset"),
            _T("Nugget", "Failed to export preset."))
        return False
    QMessageBox.information(
        parent, _T("Nugget", "Export Preset"),
        _T("Nugget", "Preset exported to:\n{0}").format(file_path))
    return True


def partial_export_preset_flow(parent, pm: PresetManager, name: str) -> bool:
    if not name:
        QMessageBox.warning(
            parent, _T("Nugget", "Partial Export"),
            _T("Nugget", "Select a preset to export first."))
        return False
    from src.gui.dialogs.preset_partial_export import PartialExportDialog
    dialog = PartialExportDialog(parent=parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    selected = dialog.selected_tweaks()
    if not selected:
        QMessageBox.warning(
            parent, _T("Nugget", "Partial Export"),
            _T("Nugget", "Select at least one tweak to export."))
        return False
    file_path, _ = QFileDialog.getSaveFileName(
        parent, _T("Nugget", "Partial Export"), f"{name}.json",
        _T("Nugget", "JSON Files (*.json)"))
    if not file_path:
        return False
    if not pm.export_preset(name, file_path, include=selected):
        QMessageBox.critical(
            parent, _T("Nugget", "Partial Export"),
            _T("Nugget", "Failed to export preset."))
        return False
    QMessageBox.information(
        parent, _T("Nugget", "Partial Export"),
        _T("Nugget", "Preset exported to:\n{0}").format(file_path))
    return True


def import_preset_flow(parent, pm: PresetManager) -> Optional[str]:
    """Import a preset file. Returns the new preset name, or None."""
    file_path, _ = QFileDialog.getOpenFileName(
        parent, _T("Nugget", "Import Preset"), "",
        _T("Nugget", "JSON Files (*.json)"))
    if not file_path:
        return None
    success, result = pm.import_preset(file_path)
    if not success:
        QMessageBox.critical(
            parent, _T("Nugget", "Import Preset"),
            _T("Nugget", "Failed to import preset:\n{0}").format(result))
        return None
    QMessageBox.information(
        parent, _T("Nugget", "Import Preset"),
        _T("Nugget", "Preset \"{0}\" imported successfully.").format(result))
    return result


# ---------------------------------------------------------------------------
# the popup
# ---------------------------------------------------------------------------

class _PresetRow(QPushButton):
    """One selectable preset: name on top, device/iOS line underneath.

    A plain click selects it; a double click applies it. ``QAbstractButton`` has
    no ``doubleClicked`` signal in this Qt version, so it is declared here and
    emitted from ``mouseDoubleClickEvent``.
    """

    doubleClicked = Signal()

    def __init__(self, name: str, meta: dict, active: bool, parent=None):
        super().__init__(parent)
        self.preset_name = name
        self.setObjectName("presetRow")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setFixedHeight(52)


        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(1)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)

        check = QLabel("✓" if active else "")
        check.setObjectName("presetRowCheck")
        self._check = check
        title_row.addWidget(check)

        title = QLabel(name)
        title.setObjectName("presetRowTitle")
        self._title = title
        title_row.addWidget(title, 1)
        layout.addLayout(title_row)

        sub_text = preset_subtitle(meta)
        sub = QLabel(sub_text)
        sub.setObjectName("presetRowSub")
        sub.setVisible(bool(sub_text))
        self._sub = sub
        layout.addWidget(sub)

        self._retheme()
        _auto_retheme(self)

    def set_active(self, active: bool):
        self._check.setText("✓" if active else "")

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(t("preset_row"))
        self._check.setStyleSheet(
            f"color: {c.accent}; font-size: 14px; font-weight: 700;")
        self._title.setStyleSheet(
            f"color: {c.text_primary}; font-size: 15px; font-weight: 600;"
            "background-color: transparent;")
        self._sub.setStyleSheet(
            f"color: {c.text_secondary}; font-size: 12px;"
            "background-color: transparent;")


class _MiniButton(QPushButton):
    """Small flat action button used in the popup footer."""

    def __init__(self, text: str, danger: bool = False, parent=None):
        super().__init__(text, parent)
        self.setObjectName("presetMiniButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(30)
        self._danger = danger
        self._retheme()
        _auto_retheme(self)

    def _retheme(self):
        self.setStyleSheet(t("preset_mini_danger" if self._danger
                             else "preset_mini_button"))


class PresetPopup(QFrame):
    """The preset list that slides out of the *Manage* button.

    It is a plain **child widget** of the main window, not a top-level window:
    the OS gives no separate window its own decorations, the taskbar, or a
    task entry, and it cannot be dismissed by an outside click before it is
    even drawn. It hangs **below** the button and is drawn over the rest of the
    window with ``raise_()``.

    It is deliberately minimal: a list of presets where a single click selects
    and a double click applies, plus *Delete* pinned to the far right. The full
    preset toolkit (save/import/export/partial export) lives on the Settings
    page, which owns the same shared action flows.
    """

    closed = Signal()

    def __init__(self, window, anchor, parent=None):
        super().__init__(parent)
        self.window = window
        self.anchor = anchor
        self.pm = PresetManager()
        self.setObjectName("presetPopup")
        # never steal focus from whatever the user was doing
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # the panel is pinned to the button, so it has to go away if the
        # window moves or resizes under it
        if parent is not None:
            parent.installEventFilter(self)

        # The popup content lives in an inner widget: the slide-in animation
        # moves that child, so the panel edge stays put while the list rises
        # out of the button. The extra SLIDE_PX of top margin is the room the
        # body needs for that offset.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10 + SLIDE_PX, 10, 10)
        outer.setSpacing(0)
        self._body = QWidget(self)
        outer.addWidget(self._body)
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)

        # scrollable preset list
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(4)
        self._rows.addStretch(1)
        self._scroll.setWidget(self._rows_host)
        body.addWidget(self._scroll, 1)

        self._empty = QLabel(_T("Nugget", "No presets yet."))
        self._empty.setObjectName("presetPopupEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rows.insertWidget(0, self._empty)

        # Delete sits alone on the last row, pinned to the far right
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(6)
        footer.addStretch(1)
        self._delete_btn = _MiniButton(_T("Nugget", "Delete"), danger=True)
        self._delete_btn.clicked.connect(self._on_delete)
        footer.addWidget(self._delete_btn)
        body.addLayout(footer)

        self._retheme()
        _auto_retheme(self)

        self._selected: Optional[str] = None
        self._active_name = ""
        self._row_widgets: list[_PresetRow] = []
        self._closing = False
        self._allow_close = False
        # The popup's fade is driven by a QGraphicsOpacityEffect: a plain
        # QWidget has no "opacity" property, so the animation targets the
        # effect, not the frame.
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.finished.connect(self._on_anim_finished)
        self._slide = QPropertyAnimation(self._body, b"pos", self)

    # ---- appearance ----------------------------------------------------

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        self.setStyleSheet(t("preset_popup"))
        self._empty.setStyleSheet(
            f"color: {c.text_secondary}; font-size: 13px; padding: 10px;"
            "background-color: transparent;")
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background-color: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {c.scrollbar};"
            "border-radius: 3px; min-height: 24px; }"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical"
            " {{ height: 0px; }}")

    # ---- list ----------------------------------------------------------

    def current_preset_name(self) -> str:
        try:
            return self.window.settings.value(
                "last_loaded_preset", "", type=str) or ""
        except Exception:
            return ""

    def refresh(self):
        """Rebuild the preset rows, keeping the current selection."""
        self._active_name = self.current_preset_name()
        for row in self._row_widgets:
            self._rows.removeWidget(row)
            row.deleteLater()
        self._row_widgets.clear()

        metas = [meta for meta in self.pm.list_presets_with_metadata()
                 if not meta["name"].startswith("__")]
        self._empty.setVisible(not metas)
        for meta in metas:
            name = meta["name"]
            row = _PresetRow(name, meta, active=(name == self._active_name))
            # single click selects, double click applies
            row.clicked.connect(lambda _=False, n=name: self._select(n))
            row.doubleClicked.connect(lambda n=name: self._apply(n))
            self._rows.insertWidget(self._rows.count() - 1, row)
            self._row_widgets.append(row)

        # keep a valid selection: the active preset if it is still there
        keep = self._selected if self._selected in [
                m["name"] for m in metas] else None
        if keep is None and self._active_name:
            keep = self._active_name
        if keep is None and metas:
            keep = metas[0]["name"]
        self._select(keep)

    def _select(self, name: Optional[str]):
        self._selected = name
        for row in self._row_widgets:
            row.setChecked(row.preset_name == name)
        self._delete_btn.setEnabled(bool(name))

    def _apply(self, name: str):
        self._select(name)
        if load_preset_flow(self, self.window, self.pm, name):
            return
        self.refresh()

    # ---- actions -------------------------------------------------------

    def _on_delete(self):
        if not self._selected:
            return
        deleted = self._selected
        if delete_preset_flow(self, self.pm, deleted):
            self._selected = None
            self.refresh()

    # ---- show / hide with animation ------------------------------------

    def show_popup(self):
        self.refresh()
        self.setFixedWidth(POPUP_WIDTH)
        # clear any height cap left over from a previous open, then measure the
        # panel at its natural (capped) height
        self._scroll.setMinimumHeight(0)
        self._scroll.setMaximumHeight(MAX_VISIBLE_ROWS * ROW_H)
        self.adjustSize()
        self._fit_below_anchor()

        self.move(*self._panel_pos())
        self.raise_()

        self._closing = False
        self._effect.setOpacity(0.0)
        self.show()

        # the body starts SLIDE_PX lower and slides up into place, so the list
        # looks like it grows out from under the button
        rest_y = self._body.y()
        self._slide.stop()
        self._slide.setDuration(ANIM_MS)
        self._slide.setStartValue(QPoint(0, rest_y + SLIDE_PX))
        self._slide.setEndValue(QPoint(0, rest_y))
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._body.move(self._slide.startValue())
        self._slide.start()

        self._anim.stop()
        self._anim.setDuration(ANIM_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def _space_below_anchor(self) -> int:
        """How much vertical room the panel has under the button."""
        parent = self.parentWidget()
        if parent is None:
            return self.height()
        bottom = self.anchor.mapTo(
            parent, QPoint(0, self.anchor.height())).y()
        return parent.rect().bottom() - bottom

    def _fit_below_anchor(self):
        """Shrink the list (never the panel position) so the list stays visible.

        The panel always opens **downwards**, so if the button sits low enough
        that the full list would not fit under it, the scroll area is pinned to
        a smaller height and the list scrolls. ``setFixedHeight`` is used rather
        than ``setMaximumHeight`` because ``QScrollArea.sizeHint()`` keeps
        reporting the full content height, so a maximum alone would not shrink
        the panel.
        """
        full = self.height()
        room = self._space_below_anchor()
        if room <= 0 or room >= full:
            return
        # everything in the panel that is not the list: frame margins, the gap
        # above the footer row and the footer button itself
        chrome = full - self._scroll.height()
        # keep at least one row so the list is never a sliver
        list_h = max(ROW_H, room - chrome)
        self._scroll.setFixedHeight(list_h)
        # resize explicitly: the box layout's sizeHint() keeps reporting the
        # scroll area's full content height, so adjustSize() would not shrink
        # the panel
        self.resize(self.width(), chrome + list_h)

    def _panel_pos(self) -> tuple[int, int]:
        """Top-left of the panel, in parent-widget coordinates.

        The panel is right-aligned to the *Manage* button (like a native menu
        under a right-hand item) and hangs 6px below it. It always opens
        downwards -- ``_fit_below_anchor`` shrinks the list instead, so the
        panel never flips up or overflows the window.

        Everything here stays in the parent's coordinate system: ``move()`` is
        parent-relative, and mixing in global coordinates would offset the panel
        by the window's frame (title bar + border).
        """
        parent = self.parentWidget()
        if parent is None:
            screen = self.window.screen() if self.window is not None else None
            if screen is None:
                return 0, 0
            return (POPUP_WIDTH // 2, 40)

        anchor_top = self.anchor.mapTo(parent, QPoint(0, 0))
        anchor_bottom = self.anchor.mapTo(
            parent, QPoint(0, self.anchor.height()))

        width = POPUP_WIDTH
        bounds = parent.rect()

        gap = 6
        x = anchor_top.x() + self.anchor.width() - width
        y = anchor_bottom.y() + gap
        x = max(bounds.left(), min(x, bounds.right() - width))
        return (x, y)

    def closeEvent(self, event):
        """Fade out, then really close.

        The first close request is ignored and only honoured once the fade-out
        animation has run, so the popup never disappears with a hard cut.
        ``_allow_close`` is what lets the second (real) close pass through --
        without it the recursive close from ``super().close()`` would start
        another fade-out and the window would stay open forever.
        """
        if self._allow_close:
            event.accept()
            return
        if self._closing:
            # a fade-out is already running
            event.ignore()
            return
        if not self.isVisible():
            event.accept()
            return

        self._closing = True
        self._anim.stop()
        self._anim.setDuration(90)
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()
        event.ignore()

    def _on_anim_finished(self):
        """The fade-out animation is the only thing that may really close."""
        if self._closing:
            self._finish_close()

    def _finish_close(self):
        self._closing = False
        self._effect.setOpacity(1.0)
        self.closed.emit()
        self._allow_close = True
        try:
            super().close()
        finally:
            self._allow_close = False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move,
                            QEvent.Type.WindowStateChange):
            if self.isVisible():
                self.close()
        return False


class _DismissOnOutsideClick(QObject):
    """Closes the open preset popup when the user clicks anywhere else.

    Installed once on the QApplication; ``popup`` is set while a popup is
    open and cleared when it closes. An open ``Qt.Tool`` window does not
    dismiss itself, so this is what gives the menu its click-away behaviour.
    """

    def __init__(self, app):
        super().__init__(app)
        # a weakref, so a popup that gets destroyed without emitting `closed`
        # (e.g. its parent window is closed) can never leave a dangling target
        self._popup_ref = None
        app.installEventFilter(self)

    def eventFilter(self, obj, event):
        ref = self._popup_ref
        popup = ref() if ref is not None else None
        if popup is None:
            if ref is not None:
                self._popup_ref = None
            return False
        try:
            if not popup.isVisible():
                return False
            if event.type() == QEvent.Type.KeyPress:
                # the tool window does not take focus (WA_ShowWithoutActivating),
                # so Escape arrives at the anchor, not at the popup
                if event.key() == Qt.Key.Key_Escape:
                    popup.close()
                return False
            if event.type() == QEvent.Type.MouseButtonPress:
                try:
                    global_pos = event.globalPosition().toPoint()
                except AttributeError:  # QMouseEvent on older bindings
                    global_pos = event.globalPos()
                # a plain child widget has no frame, so map its rect instead
                top_left = popup.mapToGlobal(QPoint(0, 0))
                panel_rect = QRect(top_left, popup.size())
                if not panel_rect.contains(global_pos):
                    popup.close()
        except RuntimeError:
            # the popup's C++ side is already gone (parent closed, or the
            # interpreter is shutting down): stop tracking it
            self._popup_ref = None
        return False


_dismiss_filter = None


def _dismiss_hook() -> Optional[_DismissOnOutsideClick]:
    global _dismiss_filter
    if _dismiss_filter is None:
        app = QApplication.instance()
        if app is not None:
            _dismiss_filter = _DismissOnOutsideClick(app)
    return _dismiss_filter


def show_preset_popup(window, anchor, parent=None) -> PresetPopup:
    """Open the animated preset popup under *anchor* (a *Manage* button)."""
    hook = _dismiss_hook()
    popup = PresetPopup(window, anchor, parent)
    if hook is not None:
        hook._popup_ref = weakref.ref(popup)
        popup.closed.connect(lambda: setattr(hook, "_popup_ref", None))
    popup.show_popup()
    return popup
