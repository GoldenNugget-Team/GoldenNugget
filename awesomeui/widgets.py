"""Reusable PySide6 widgets.

The module intentionally has no imports from the original application. Copy this
file into another project and import the classes directly.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class Card(QFrame):
    """A simple rounded container with optional title and subtitle."""

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setStyleSheet(
            "QFrame#Card { background: #20242b; border: 1px solid #343a46; "
            "border-radius: 12px; }"
            "QLabel { color: #f5f7fa; background: transparent; }"
            "QLabel#CardSubtitle { color: #a8b0bd; }"
        )
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(6)
        if title:
            self.title_label = QLabel(title)
            self.title_label.setObjectName("CardTitle")
            self.body.addWidget(self.title_label)
        if subtitle:
            self.subtitle_label = QLabel(subtitle)
            self.subtitle_label.setObjectName("CardSubtitle")
            self.body.addWidget(self.subtitle_label)

    def add_widget(self, widget: QWidget) -> QWidget:
        """Append a widget and return it, which is convenient in fluent layouts."""
        self.body.addWidget(widget)
        return widget


class StatusBadge(QLabel):
    """Compact status label with a consistent semantic color."""

    COLORS = {
        "success": ("#b7f7ce", "#173c28"),
        "warning": ("#ffe4a8", "#4d3510"),
        "error": ("#ffc1c1", "#4c1f25"),
        "info": ("#c5dcff", "#1d3557"),
    }

    def __init__(
        self,
        text: str,
        kind: str = "info",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(text, parent)
        self.set_kind(kind)

    def set_kind(self, kind: str) -> None:
        foreground, background = self.COLORS.get(kind, self.COLORS["info"])
        self.setStyleSheet(
            f"color: {foreground}; background: {background}; padding: 3px 8px; "
            "border-radius: 8px; font-weight: 600;"
        )


class SearchField(QLineEdit):
    """Search field that emits only after the user pauses typing."""

    searchChanged = Signal(str)

    def __init__(self, placeholder: str = "Search…", delay_ms: int = 250, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(0, delay_ms))
        self.textChanged.connect(self._restart_timer)
        self._timer.timeout.connect(lambda: self.searchChanged.emit(self.text()))

    def _restart_timer(self) -> None:
        self._timer.start()


class LoadingButton(QPushButton):
    """Button with a built-in busy state; no spinner dependency is required."""

    clickedWhileReady = Signal()

    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self._label = text
        self._busy = False
        self.clicked.connect(self._emit_if_ready)

    @property
    def is_loading(self) -> bool:
        return self._busy

    def set_loading(self, loading: bool, label: str = "Working…") -> None:
        self._busy = loading
        self.setEnabled(not loading)
        self.setText(label if loading else self._label)

    def _emit_if_ready(self) -> None:
        if not self._busy:
            self.clickedWhileReady.emit()


class EmptyState(QWidget):
    """Centered empty state with an optional action button."""

    actionRequested = Signal()

    def __init__(
        self,
        title: str,
        message: str = "",
        action_text: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        if message:
            message_label = QLabel(message)
            message_label.setStyleSheet("color: #8f99a8;")
            message_label.setWordWrap(True)
            message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(message_label)
        if action_text:
            action = QPushButton(action_text)
            action.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            action.clicked.connect(self.actionRequested)
            layout.addWidget(action, alignment=Qt.AlignmentFlag.AlignCenter)


class Toast(QFrame):
    """Non-blocking notification that disappears automatically."""

    def __init__(self, message: str, timeout_ms: int = 2500, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 8, 9)
        label = QLabel(message)
        label.setStyleSheet("color: white; background: transparent;")
        layout.addWidget(label)
        close = QToolButton()
        close.setText("×")
        close.setStyleSheet("color: #cbd5e1; background: transparent; border: 0;")
        close.clicked.connect(self.close)
        layout.addWidget(close)
        self.setStyleSheet("QFrame { background: #171a20; border: 1px solid #414957; "
                           "border-radius: 10px; }")
        QTimer.singleShot(max(0, timeout_ms), self.close)

    @classmethod
    def show_message(cls, parent: QWidget, message: str, timeout_ms: int = 2500) -> "Toast":
        toast = cls(message, timeout_ms, parent)
        toast.adjustSize()
        margin = 18
        toast.move(parent.width() - toast.width() - margin, margin)
        toast.show()
        toast.raise_()
        return toast


@dataclass
class SidebarTheme:
    """Every visual knob of :class:`Sidebar` in one place."""

    background: str = "#15181e"
    border: str = "#2a303b"
    text: str = "#e5e9f0"
    text_muted: str = "#8f99a8"
    hover_background: str = "#232834"
    active_background: str = "#2d3444"
    active_indicator: str = "#7aa2ff"
    separator: str = "#2a303b"
    item_radius: int = 8
    item_height: int = 34
    icon_size: int = 18
    padding: int = 8
    spacing: int = 2
    width: int = 232
    collapsed_width: int = 58
    animation_ms: int = 180


class SidebarItem(QToolButton):
    """One navigable entry of a :class:`Sidebar`."""

    def __init__(
        self,
        item_id: str,
        text: str,
        icon=None,
        checkable: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.item_id = item_id
        self.setText(text)
        self._label = text
        if icon is not None:
            self.setIcon(icon)
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setObjectName("SidebarItem")
        self.indicator_color: str = ""
        self._badge = QLabel(self)
        self._badge.setObjectName("SidebarBadge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.hide()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().paintEvent(event)
        if self.indicator_color and self.isChecked():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            bar_w = 3
            radius = bar_w / 2
            top = (self.height() - 16) / 2
            path.addRoundedRect(0.0, top, bar_w, 16, radius, radius)
            painter.fillPath(path, QColor(self.indicator_color))

    @property
    def label(self) -> str:
        return self._label

    def set_label(self, text: str) -> None:
        self._label = text
        self.setText(text)
        self.setToolTip(text)

    def set_badge(self, text: str) -> None:
        """Show a small pill on the right side; empty text hides it."""
        self._badge.setText(text)
        self._badge.setVisible(bool(text))
        self._badge.adjustSize()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        if not self._badge.isVisible():
            return
        margin = 8
        self._badge.move(
            self.width() - self._badge.width() - margin,
            (self.height() - self._badge.height()) // 2,
        )


class SidebarGroup(QFrame):
    """Collapsible group of sidebar items with its own header."""

    def __init__(
        self,
        group_id: str,
        title: str,
        icon=None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.group_id = group_id
        self._title = title
        self._icon = icon
        self._expanded = True
        self.setObjectName("SidebarGroup")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self.header = QToolButton()
        self.header.setObjectName("SidebarGroupHeader")
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon is not None:
            self.header.setIcon(icon)
        self.header.setText(title)
        self.header.setArrowType(Qt.ArrowType.NoArrow)
        self.header.clicked.connect(self.toggle)
        self._layout.addWidget(self.header)

        self.body = QFrame()
        self.body.setObjectName("SidebarGroupBody")
        self._body_layout = QVBoxLayout(self.body)
        self._body_layout.setContentsMargins(14, 2, 0, 2)
        self._body_layout.setSpacing(0)
        self._layout.addWidget(self.body)

    @property
    def title(self) -> str:
        return self._title

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self.body.setVisible(expanded)
        self.header.setText(("▾ " if expanded else "▸ ") + self._title)

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)


class Sidebar(QFrame):
    """Fully customizable navigation sidebar.

    Supports sections, exclusive items, collapsible groups, badges, a footer
    slot, animated collapse to icon-only mode, optional hover expansion and a
    swappable :class:`SidebarTheme`.
    """

    itemClicked = Signal(str)
    currentChanged = Signal(str)
    collapsedChanged = Signal(bool)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        theme: Optional[SidebarTheme] = None,
        collapsible: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self._theme = theme or SidebarTheme()
        self._collapsible = collapsible
        self._collapsed = False
        self._pinned_expanded = True
        self._expands_on_hover = False
        self._items: Dict[str, SidebarItem] = {}
        self._groups: Dict[str, SidebarGroup] = {}
        self._labels: list[QLabel] = []
        self._buttons = QButtonGroup(self)
        self._buttons.setExclusive(True)
        self._buttons.buttonClicked.connect(self._handle_click)
        self._animation: Optional[QParallelAnimationGroup] = None

        outer = QVBoxLayout(self)
        t = self._theme
        outer.setContentsMargins(t.padding, t.padding, t.padding, t.padding)
        outer.setSpacing(t.spacing)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: 0; }")
        outer.addWidget(self._scroll)

        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(t.spacing)
        self._layout.addStretch(1)
        self._scroll.setWidget(self._content)

        self.setFixedWidth(t.width)
        self._apply_theme()

    # ------------------------------------------------------------------
    # Content API
    # ------------------------------------------------------------------
    def add_section(self, title: str) -> QLabel:
        """Add a small muted section header above upcoming items."""
        label = QLabel(title.upper())
        label.setObjectName("SidebarSection")
        label.setContentsMargins(10, 10, 4, 2)
        self._layout.insertWidget(self._layout.count() - 1, label)
        self._labels.append(label)
        label.setVisible(not self._collapsed)
        return label

    def add_item(
        self,
        item_id: str,
        text: str,
        icon=None,
        badge: str = "",
        checkable: bool = True,
        group: str = "",
    ) -> SidebarItem:
        """Add an exclusive navigable item, optionally inside a group."""
        if item_id in self._items:
            raise ValueError(f"duplicate sidebar item id: {item_id!r}")
        item = SidebarItem(item_id, text, icon, checkable)
        item.indicator_color = self._theme.active_indicator
        item.setIconSize(QSize(self._theme.icon_size, self._theme.icon_size))
        if badge:
            item.set_badge(badge)
        self._items[item_id] = item
        self._buttons.addButton(item)
        if group:
            if group not in self._groups:
                raise KeyError(f"unknown sidebar group: {group!r}")
            self._groups[group].body.layout().addWidget(item)
        else:
            self._layout.insertWidget(self._layout.count() - 1, item)
        item.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly if self._collapsed
            else Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        item.setVisible(True)
        item.setToolTip("" if not self._collapsed else text)
        return item

    def add_group(self, group_id: str, title: str, icon=None) -> SidebarGroup:
        """Add a collapsible group; use ``group=group_id`` in :meth:`add_item`."""
        if group_id in self._groups:
            raise ValueError(f"duplicate sidebar group id: {group_id!r}")
        group = SidebarGroup(group_id, title, icon)
        group.header.setIconSize(QSize(self._theme.icon_size, self._theme.icon_size))
        self._groups[group_id] = group
        self._layout.insertWidget(self._layout.count() - 1, group)
        return group

    def add_separator(self) -> QFrame:
        line = QFrame()
        line.setObjectName("SidebarSeparator")
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        line.setContentsMargins(10, 4, 10, 4)
        self._layout.insertWidget(self._layout.count() - 1, line)
        return line

    def add_stretch(self) -> None:
        self._layout.insertStretch(self._layout.count() - 1, 1)

    def add_footer_widget(self, widget: QWidget) -> QWidget:
        """Pin an arbitrary widget (user card, version label…) to the bottom."""
        self._layout.addWidget(widget)
        return widget

    def remove_item(self, item_id: str) -> None:
        item = self._items.pop(item_id, None)
        if item is None:
            return
        self._buttons.removeButton(item)
        item.setParent(None)
        item.deleteLater()

    # ------------------------------------------------------------------
    # Selection & state
    # ------------------------------------------------------------------
    def item(self, item_id: str) -> Optional[SidebarItem]:
        return self._items.get(item_id)

    def current_item_id(self) -> Optional[str]:
        button = self._buttons.checkedButton()
        return button.item_id if isinstance(button, SidebarItem) else None

    def set_current(self, item_id: str, emit: bool = True) -> None:
        item = self._items[item_id]
        item.setChecked(True)
        if emit:
            self.currentChanged.emit(item_id)

    def set_item_badge(self, item_id: str, text: str) -> None:
        self._items[item_id].set_badge(text)

    def _handle_click(self, button) -> None:
        if isinstance(button, SidebarItem):
            self.itemClicked.emit(button.item_id)
            if button.isChecked():
                self.currentChanged.emit(button.item_id)

    # ------------------------------------------------------------------
    # Collapse behavior
    # ------------------------------------------------------------------
    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsible(self, collapsible: bool) -> None:
        self._collapsible = collapsible

    def collapse(self) -> None:
        self.set_collapsed(True)

    def expand(self) -> None:
        self.set_collapsed(False)

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        if not self._collapsible or collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._pinned_expanded = not collapsed
        self._set_text_visible(not collapsed, animate)
        self.collapsedChanged.emit(collapsed)

    def set_expands_on_hover(self, enabled: bool) -> None:
        """While collapsed, temporarily expand when the pointer enters."""
        self._expands_on_hover = enabled

    def _set_text_visible(self, visible: bool, animate: bool) -> None:
        t = self._theme
        for item in self._items.values():
            item.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                if visible
                else Qt.ToolButtonStyle.ToolButtonIconOnly
            )
            item.setToolTip("" if visible else item.label)
        for group in self._groups.values():
            group.header.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                if visible
                else Qt.ToolButtonStyle.ToolButtonIconOnly
            )
            group.header.setToolTip("" if visible else group.title)
        for label in self._labels:
            label.setVisible(visible)
        self._animate_width(t.width if visible else t.collapsed_width, animate)

    def _animate_width(self, width: int, animate: bool = True) -> None:
        if self._animation is not None:
            self._animation.stop()
        if not animate:
            self.setFixedWidth(width)
            return
        self._animation = QParallelAnimationGroup(self)
        for prop in (b"minimumWidth", b"maximumWidth"):
            anim = QPropertyAnimation(self, prop)
            anim.setDuration(self._theme.animation_ms)
            anim.setStartValue(self.width())
            anim.setEndValue(width)
            anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
            self._animation.addAnimation(anim)
        self._animation.start()

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._expands_on_hover and self._collapsed:
            self._set_text_visible(True, animate=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._expands_on_hover and not self._pinned_expanded:
            self._set_text_visible(False, animate=True)
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------
    def theme(self) -> SidebarTheme:
        return self._theme

    def set_theme(self, theme: SidebarTheme, animate: bool = False) -> None:
        self._theme = theme
        t = theme
        self._layout.setSpacing(t.spacing)
        self._content.layout().setSpacing(t.spacing)
        for item in self._items.values():
            item.setIconSize(QSize(t.icon_size, t.icon_size))
        for group in self._groups.values():
            group.header.setIconSize(QSize(t.icon_size, t.icon_size))
        self._apply_theme()
        self._set_text_visible(not self._collapsed, animate=animate)

    def with_theme(self, **overrides) -> SidebarTheme:
        """Update individual theme fields, e.g. ``sidebar.with_theme(width=280)``."""
        self._theme = replace(self._theme, **overrides)
        self.set_theme(self._theme)
        return self._theme

    def _apply_theme(self) -> None:
        t = self._theme
        for item in self._items.values():
            item.indicator_color = t.active_indicator
            item.setIconSize(QSize(t.icon_size, t.icon_size))
            item.update()
        for group in self._groups.values():
            group.header.setIconSize(QSize(t.icon_size, t.icon_size))
        self.setStyleSheet(
            f"QFrame#Sidebar {{ background: {t.background}; "
            f"border-right: 1px solid {t.border}; }}"
            "QFrame#Sidebar QLabel, QFrame#Sidebar QWidget "
            "{ background: transparent; }"
            f"QLabel#SidebarSection {{ color: {t.text_muted}; font-size: 11px; "
            "font-weight: 700; }"
            f"QToolButton#SidebarItem, QToolButton#SidebarGroupHeader {{ "
            f"color: {t.text}; text-align: left; border: 0; "
            f"border-radius: {t.item_radius}px; padding: 0 10px; "
            f"min-height: {t.item_height}px; }}"
            f"QToolButton#SidebarItem:hover, QToolButton#SidebarGroupHeader:hover "
            f"{{ background: {t.hover_background}; }}"
            f"QToolButton#SidebarItem:checked {{ background: {t.active_background}; "
            "font-weight: 600; }"
            f"QLabel#SidebarBadge {{ color: {t.text}; background: {t.active_background}; "
            "border-radius: 8px; padding: 1px 7px; font-size: 11px; }"
            f"QFrame#SidebarSeparator {{ background: {t.border}; }}"
        )

