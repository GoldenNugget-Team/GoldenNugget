"""Qt widgets for template options.

This is the GUI half of the template-option model. The model classes in
``src.tweaks.posterboard.template_options`` hold the values and know how to
write them into a template; everything that builds widgets, opens dialogs or
touches preview labels lives here so the backend stays toolkit-free.
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QStackedLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.gui.liquid.choice_editor import GlassComboBox
from src.tweaks.posterboard.template_options.picker_option import PickerOption
from src.tweaks.posterboard.template_options.remove_option import RemoveOption
from src.tweaks.posterboard.template_options.replace_option import ReplaceOption
from src.tweaks.posterboard.template_options.set_option import SetOption, SetterType
from src.utils.color import RgbColor

# --------------------------------------------------------------------------- #
# Colour conversion
# --------------------------------------------------------------------------- #

def to_qcolor(color: RgbColor) -> QtGui.QColor:
    return QtGui.QColor(color.red, color.green, color.blue, color.alpha)


def from_qcolor(color: QtGui.QColor) -> RgbColor:
    return RgbColor(color.red(), color.green(), color.blue(), color.alpha())


def color_stylesheet(color: RgbColor) -> str:
    return (f"background-color: rgba({color.red}, {color.green}, {color.blue}, "
            f"{color.alphaF()}); border: 2px solid #3b3b3b;")


# --------------------------------------------------------------------------- #
# Preview labels (attached by the editor)
# --------------------------------------------------------------------------- #

def bind_previews(option, previews: dict[str, QLabel]) -> None:
    """Attach the preview labels an option refers to (if any)."""
    if option.associated_preview is not None and option.associated_preview in previews:
        option.preview_lbl = previews[option.associated_preview]
        if isinstance(option, ReplaceOption):
            # Remember the template's own artwork so replacing the file can be
            # undone without losing the default preview.
            option._default_preview = option.preview_lbl.pixmap()
    if isinstance(option, PickerOption):
        for element in option.options:
            if element.associated_preview in previews:
                element.preview_lbl = previews[element.associated_preview]


def update_preview(option) -> None:
    """Re-apply the option's current value to its preview label(s)."""
    if isinstance(option, ReplaceOption):
        label = option.preview_lbl
        if label is not None:
            if option.value is None:
                label.setPixmap(getattr(option, "_default_preview", None))
            else:
                label.setPixmap(QtGui.QPixmap(option.value))
        return
    if isinstance(option, RemoveOption):
        if option.preview_lbl is not None:
            option.preview_lbl.setVisible(not option.is_hidden())
        return
    if isinstance(option, PickerOption):
        if option.allow_multiple_selection:
            for element in option.options:
                if element.preview_lbl is not None:
                    element.preview_lbl.setVisible(element.label in option.selection)
        else:
            for index, element in enumerate(option.options):
                if element.preview_lbl is not None:
                    element.preview_lbl.setVisible(option.selection == index)


# --------------------------------------------------------------------------- #
# Widget construction
# --------------------------------------------------------------------------- #

def create_interface(option, options_widget: QWidget, options_layout: QVBoxLayout,
                     window=None) -> None:
    if isinstance(option, ReplaceOption):
        _create_replace(option, options_widget, options_layout, window)
    elif isinstance(option, RemoveOption):
        _create_remove(option, options_widget, options_layout)
    elif isinstance(option, SetOption):
        _create_set(option, options_widget, options_layout)
    elif isinstance(option, PickerOption):
        _create_picker(option, options_widget, options_layout)
    else:
        raise NotImplementedError(option.type)


def _create_replace(option: ReplaceOption, options_widget: QWidget,
                    options_layout: QVBoxLayout, window) -> None:
    repl_widget = QWidget(options_widget)
    repl_layout = QHBoxLayout(repl_widget)
    repl_layout.setContentsMargins(0, 2, 0, 2)
    repl_lbl = QLabel(repl_widget)
    required = "* " if option.required else ""
    repl_lbl.setText(f"{required}{option.label}")
    repl_layout.addWidget(repl_lbl)

    imp_widget = QWidget(options_widget)
    imp_layout = QVBoxLayout(imp_widget)
    imp_widget.setLayoutDirection(QtCore.Qt.LayoutDirection.RightToLeft)
    button = QToolButton(imp_widget)
    import_icon = QtGui.QIcon(":/icon/import.svg")
    remove_icon = QtGui.QIcon(":/icon/trash.svg")
    button.setIcon(import_icon)
    button.setIconSize(QtCore.QSize(20, 20))
    button.setText(option.button_label)
    button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    path_label = QLabel(imp_widget)
    path_label.hide()
    imp_layout.addWidget(button)
    imp_layout.addWidget(path_label)
    imp_widget.setLayout(imp_layout)
    repl_layout.addWidget(imp_widget)
    repl_widget.setLayout(repl_layout)
    options_layout.addWidget(repl_widget)

    def on_click():
        if option.value is None:
            selected, _ = QtWidgets.QFileDialog.getOpenFileName(
                window, QtCore.QCoreApplication.translate("Nugget", "Select File"),
                "", option.allowed_files,
                options=QtWidgets.QFileDialog.ReadOnly)
            if selected:
                option.value = selected
                path_label.setText(selected)
                path_label.show()
                button.setText(QtCore.QCoreApplication.translate(
                    "Nugget", "Remove Selected File"))
                button.setIcon(remove_icon)
        else:
            option.value = None
            path_label.hide()
            button.setText(option.button_label)
            button.setIcon(import_icon)
        update_preview(option)

    button.clicked.connect(on_click)


def _create_remove(option: RemoveOption, options_widget: QWidget,
                   options_layout: QVBoxLayout) -> None:
    check = QCheckBox(options_widget)
    check.setText(option.label)
    check.setChecked(option.value)

    def toggled(checked: bool):
        option.set_option(checked)
        update_preview(option)

    check.toggled.connect(toggled)
    options_layout.addWidget(check)


def _create_set(option: SetOption, options_widget: QWidget,
                options_layout: QVBoxLayout) -> None:
    if option.setter_type == SetterType.toggle:
        check = QCheckBox(options_widget)
        check.setText(option.label)
        check.setChecked(option.value)
        check.toggled.connect(option.update_bool)
        options_layout.addWidget(check)
        return

    if option.setter_type == SetterType.textbox:
        box_widget = QWidget(options_widget)
        box_layout = QVBoxLayout(box_widget)
        box_layout.setContentsMargins(0, 2, 0, 2)
        box_label = QLabel(box_widget)
        box_label.setText(option.label)
        box_layout.addWidget(box_label)
        textbox = QLineEdit(box_widget)
        textbox.setPlaceholderText("Value")
        textbox.setText(str(option.convert_back(option.value)))
        textbox.textEdited.connect(option.update_value)
        box_layout.addWidget(textbox)
        box_widget.setLayout(box_layout)
        options_layout.addWidget(box_widget)
        return

    if option.setter_type == SetterType.slider:
        values = option.value
        list_len = len(values) if isinstance(values, list) else 1
        if not isinstance(values, list):
            values = [values]
        labels = []
        for index in range(list_len):
            slid_widget = QWidget(options_widget)
            slid_layout = QVBoxLayout(slid_widget)
            slid_layout.setContentsMargins(0, 2, 0, 2)
            slid_label = QLabel(slid_widget)
            slid_label.setText(f"{option.label}: {values[index]}")
            slid_layout.addWidget(slid_label)
            labels.append(slid_label)

            val_widget = QWidget(slid_widget)
            val_layout = QHBoxLayout(val_widget)
            min_label = QLabel(val_widget)
            max_label = QLabel(val_widget)

            min_fixed, min_val, max_fixed, max_val, step, value = (
                item[index] if isinstance(item, list) else item
                for item in (
                    option.min_value, option.convert_float(option.min_value),
                    option.max_value, option.convert_float(option.max_value),
                    option.convert_float(option.step), option.convert_float(option.value),
                ))
            min_label.setText(str(min_fixed))
            val_layout.addWidget(min_label)
            slider = QSlider(val_widget)
            slider.setMinimum(min_val)
            slider.setMaximum(max_val)
            slider.setTickInterval(step)
            slider.setSingleStep(step)
            slider.setValue(value)
            slider.setOrientation(QtCore.Qt.Orientation.Horizontal)
            val_layout.addWidget(slider)
            max_label.setText(str(max_fixed))
            val_layout.addWidget(max_label)

            def moved(new_value, idx=index, label=slid_label):
                option.update_value(new_value, idx)
                current = option.value[idx] if isinstance(option.value, list) else option.value
                label.setText(f"{option.label}: {current}")

            slider.valueChanged.connect(moved)
            val_widget.setLayout(val_layout)
            slid_layout.addWidget(val_widget)
            slid_widget.setLayout(slid_layout)
            options_layout.addWidget(slid_widget)
        option._ui_labels = labels
        return

    if option.setter_type == SetterType.color_picker:
        col_widget = QWidget(options_widget)
        col_layout = QHBoxLayout(col_widget)
        col_layout.setContentsMargins(0, 2, 0, 2)
        col_label = QLabel(col_widget)
        col_label.setText(option.label)
        col_layout.addWidget(col_label)
        picker_bg = QWidget(col_widget)
        picker_bg_layout = QStackedLayout(picker_bg)
        picker_bg_layout.setStackingMode(QStackedLayout.StackAll)
        picker_img = QToolButton(picker_bg)
        picker_img.setText("")
        picker_img.setStyleSheet(
            "background-image: url(:/gui/transparent.png); border-radius: 10px;")
        picker = QToolButton(picker_bg)
        picker.setText("")
        picker.setStyleSheet(color_stylesheet(option.value))
        picker_bg_layout.addWidget(picker_img)
        picker_bg_layout.addWidget(picker)
        picker_bg.setLayout(picker_bg_layout)
        picker_bg.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        col_layout.addWidget(picker_bg)
        col_widget.setLayout(col_layout)
        options_layout.addWidget(col_widget)
        option._ui_labels = [picker]

        def choose_color():
            color = QtWidgets.QColorDialog.getColor(
                initial=to_qcolor(option.value),
                options=QtWidgets.QColorDialog.ColorDialogOption.ShowAlphaChannel)
            if color.isValid():
                option.update_color(from_qcolor(color))
                picker.setStyleSheet(color_stylesheet(option.value))

        picker.clicked.connect(choose_color)
        return


def _create_picker(option: PickerOption, options_widget: QWidget,
                   options_layout: QVBoxLayout) -> None:
    picker_widget = QWidget(options_widget)
    picker_layout = QHBoxLayout(picker_widget)
    picker_label = QLabel(picker_widget)
    picker_label.setText(option.label)
    picker_layout.addWidget(picker_label)

    if option.allow_multiple_selection:
        from src.qt.custom_elements.multicombobox import MultiComboBox

        combo = MultiComboBox(picker_widget, updateAction=_on_picker_update(option))
        for element in option.options:
            combo.addItem(element.label, element.label)
        selected = list(option.selection)
        combo.selectIndices([index for index, element in enumerate(option.options)
                             if element.label in selected])
        combo.updateText()
        combo.setStyleSheet(
            "QWidget { background-color: #3b3b3b; border: 2px solid #3b3b3b; border-radius: 5px; }")
    else:
        combo = GlassComboBox(picker_widget)
        for element in option.options:
            combo.addItem(element.label)
        combo.setCurrentIndex(option.selection)
        combo.currentIndexChanged.connect(_on_picker_update(option))
    picker_layout.addWidget(combo)
    picker_widget.setLayout(picker_layout)
    options_layout.addWidget(picker_widget)


def _on_picker_update(option: PickerOption):
    def update(selection):
        option.onPickerUpdate(selection)
        update_preview(option)

    return update
