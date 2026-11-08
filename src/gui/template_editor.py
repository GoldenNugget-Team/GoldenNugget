"""Qt editor for template selections; archive metadata stays in the model."""
from PySide6 import QtCore, QtGui, QtWidgets

from src.gui.liquid.choice_editor import GlassComboBox
from src.gui.template_option_editors import (
    bind_previews as bind_option_previews,
)
from src.gui.template_option_editors import (
    create_interface as create_option_interface,
)
from src.gui.template_option_editors import (
    update_preview as update_option_preview,
)
from src.qt.custom_elements.resizable_image_label import ResizableImageLabel
from src.tweaks.posterboard.community_tweaks import CommunityTweak


class TemplateEditor:
    def __init__(self, model):
        self.model = model

    def __getattr__(self, name):
        return getattr(self.model, name)

    def get_chevron_icon(self, is_up: bool):
        if is_up:
            return QtGui.QIcon(":/icon/chevron.up.svg")
        return QtGui.QIcon(":/icon/chevron.down.svg")


    def update_bundle_id(self, new_id: str):
        self.model.bundle_id = new_id
        self.domain_lbl.setText(f" (AppDomain-{self.bundle_id})")


    def create_ui(self, window, tweak, widgets: dict, templateLayout: QtWidgets.QVBoxLayout):
        if self.loaded:
            return
        widget = QtWidgets.QWidget()
        widgets[self.model] = widget
        options_widget = QtWidgets.QWidget(widget)

        # create the icon/label + delete button
        left_widget = QtWidgets.QWidget(widget)
        title_widget = QtWidgets.QWidget(left_widget)
        title_layout = QtWidgets.QVBoxLayout()
        if self.domain == "com.apple.PosterBoard":
            titleBtn = QtWidgets.QToolButton(title_widget)
            titleBtn.setIcon(QtGui.QIcon(self.get_icon()))
            titleBtn.setIconSize(QtCore.QSize(20, 20))
            titleBtn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            titleBtn.setText(f"   {self.name}")
            titleBtn.setStyleSheet("QToolButton {\n    background-color: transparent;\n	icon-size: 20px; text-align:left;\n}")
            titleBtn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            title_layout.addWidget(titleBtn)
        else:
            title_lbl = QtWidgets.QLabel(title_widget)
            title_lbl.setText(self.name)
            title_layout.addWidget(title_lbl)
        # author label
        auth_lbl = QtWidgets.QLabel(title_widget)
        auth_lbl.setText(f"by {self.author}")
        auth_lbl.setStyleSheet("QLabel { font-size: 12px; }")
        title_layout.addWidget(auth_lbl)
        title_widget.setLayout(title_layout)
        # domain label
        self.domain_lbl = QtWidgets.QLabel(left_widget)
        self.domain_lbl.setText(f" ({self.domain})" if self.domain else "")
        chevron = QtWidgets.QToolButton(left_widget)
        chevron.setIcon(self.get_chevron_icon(is_up=True)) # for opening/closing the options
        chevron.setStyleSheet("QToolButton {\n    background-color: transparent;\n	icon-size: 20px;\n}")
        chevron.clicked.connect(lambda _, get_chev=self.get_chevron_icon: (
            options_widget.setVisible(not options_widget.isVisible()),
            chevron.setIcon(get_chev(options_widget.isVisible()))
        ))
        spacer = QtWidgets.QSpacerItem(40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        delBtn = QtWidgets.QToolButton(left_widget)
        delBtn.setIcon(QtGui.QIcon(":/icon/trash.svg"))
        delBtn.clicked.connect(lambda _, file=self.model: (
            widgets[file].deleteLater(),
            file.clean_files(),
            tweak.templates.remove(file)
        ))
        # align to top layout
        left_layout = QtWidgets.QHBoxLayout()
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.addWidget(title_widget)
        left_layout.addWidget(self.domain_lbl)
        left_layout.addItem(spacer)
        left_layout.addWidget(chevron)
        left_layout.addWidget(delBtn)
        left_widget.setLayout(left_layout)
        left_widget.setMinimumHeight(60)
        left_widget.setMaximumHeight(60)

        # main layout
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(left_widget)
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Shadow.Plain)
        line.setStyleSheet("QFrame {\n	color: #414141;\n}")
        layout.addWidget(line)

        # create options
        # options_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        opt_layout = QtWidgets.QVBoxLayout()
        opt_layout.setContentsMargins(3, 0, 0, 0)

        # create previews
        prevs: dict[str, QtWidgets.QLabel] = {}
        if len(self.previews) > 0:
            prev_widget = QtWidgets.QWidget(options_widget)
            prev_widget.setMinimumHeight(250)
            prev_widget.setMaximumHeight(250)
            prev_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
            if self.preview_layout == "stacked":
                prev_layout = QtWidgets.QStackedLayout()
                prev_layout.setStackingMode(QtWidgets.QStackedLayout.StackAll)
            else:
                prev_layout = QtWidgets.QHBoxLayout()
            prev_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            for prev in self.previews.keys():
                new_prev = ResizableImageLabel(prev_widget)
                new_prev.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
                pixmap = QtGui.QPixmap(self.previews[prev])
                new_prev.setPixmap(pixmap)
                # new_prev.setScaledContents(True)
                prev_layout.addWidget(new_prev)
                prevs[prev] = new_prev
            prev_widget.setLayout(prev_layout)
            opt_layout.addWidget(prev_widget)

        # make banner
        if self.banner_text != None:
            banner = QtWidgets.QLabel(options_widget)
            banner.setText(self.banner_text)
            banner.setAlignment(QtCore.Qt.AlignCenter)
            if self.banner_stylesheet != None:
                banner.setStyleSheet(self.banner_stylesheet)
            opt_layout.addWidget(banner)
        # make description
        if self.description != None:
            descr = QtWidgets.QLabel(options_widget)
            descr.setText(self.description)
            opt_layout.addWidget(descr)

        # bundle id changing
        if self.change_bundle_id:
            # textbox input
            bx_widget = QtWidgets.QWidget(options_widget)
            bx_layout = QtWidgets.QVBoxLayout(bx_widget)
            bx_layout.setContentsMargins(0, 2, 0, 2)
            bx_lbl = QtWidgets.QLabel(bx_widget)
            bx_lbl.setText(QtCore.QCoreApplication.translate("Nugget", "App bundle id:"))
            bx_layout.addWidget(bx_lbl)
            textbox = QtWidgets.QLineEdit(bx_widget)
            textbox.setPlaceholderText(QtCore.QCoreApplication.tr("Bundle id (default: {0})").format(self.domain.removeprefix('AppDomain-')))
            textbox.setText(self.bundle_id)
            textbox.textEdited.connect(self.update_bundle_id)
            bx_layout.addWidget(textbox)
            bx_widget.setLayout(bx_layout)
            opt_layout.addWidget(bx_widget)

        for option in self.options:
            create_option_interface(option, options_widget, opt_layout, window)
            # attach the preview labels and show the current value
            bind_option_previews(option, prevs)
            update_option_preview(option)

        if self.tweaks:
            self.create_tweaks_ui(window, options_widget, opt_layout)

        options_widget.setLayout(opt_layout)

        # finish the main layout
        layout.addWidget(options_widget)
        # Add the widget to the mainLayout
        widget.setLayout(layout)
        templateLayout.addWidget(widget)
        self.model.loaded = True


    def create_tweaks_ui(self, window, parent: QtWidgets.QWidget, layout: QtWidgets.QVBoxLayout):
        """A switch per community tweak, with its control and the files it writes."""
        try:
            version = window.device_manager.get_current_device_version()
        except Exception:
            version = None
        header = QtWidgets.QLabel(QtCore.QCoreApplication.translate("CommunityTweaks", "Tweaks"), parent)
        header.setStyleSheet("QLabel { font-weight: 600; margin-top: 6px; }")
        layout.addWidget(header)
        for tweak in self.tweaks:
            box = QtWidgets.QWidget(parent)
            box_layout = QtWidgets.QVBoxLayout(box)
            box_layout.setContentsMargins(0, 2, 0, 6)
            box_layout.setSpacing(2)
            check = QtWidgets.QCheckBox(tweak.label, box)
            check.setChecked(tweak.enabled)
            box_layout.addWidget(check)
            notes = [tweak.description] if tweak.description else []
            if not tweak.supports(version):
                notes.append(QtCore.QCoreApplication.translate(
                    "CommunityTweaks", "Not applied on iOS {0}.").format(version))
            notes.append(QtCore.QCoreApplication.translate("CommunityTweaks", "Writes: {0}").format(
                ", ".join(tweak.paths())))
            note = QtWidgets.QLabel("\n".join(notes), box)
            note.setWordWrap(True)
            note.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            note.setStyleSheet("QLabel { font-size: 11px; color: gray; }")
            box_layout.addWidget(note)
            control = self._tweak_control(tweak, box)
            if control is not None:
                control.setEnabled(tweak.enabled)
                box_layout.addWidget(control)
            check.toggled.connect(lambda checked, item=tweak, widget=control: (
                setattr(item, "enabled", checked),
                widget is not None and widget.setEnabled(checked)))
            layout.addWidget(box)


    @staticmethod
    def _tweak_control(tweak: CommunityTweak, parent: QtWidgets.QWidget):
        control = tweak.control
        if control is None:
            return None
        if control.type == "text":
            edit = QtWidgets.QLineEdit(parent)
            edit.setMaxLength(control.max_length)
            edit.setText(tweak.value or "")
            edit.textEdited.connect(lambda text, item=tweak: setattr(item, "value", text))
            return edit
        if control.type == "choice":
            combo = GlassComboBox(parent)
            for label, value in control.choices:
                combo.addItem(label)
            values = [value for _, value in control.choices]
            combo.setCurrentIndex(values.index(tweak.value) if tweak.value in values else 0)
            combo.currentIndexChanged.connect(lambda index, item=tweak: setattr(item, "value", values[index]))
            return combo
        # slider: QSlider works in integer steps
        row = QtWidgets.QWidget(parent)
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        steps = max(1, round((control.max - control.min) / control.step))
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, row)
        slider.setRange(0, steps)
        slider.setValue(round((tweak.value - control.min) / control.step))
        value_lbl = QtWidgets.QLabel(str(tweak.value), row)
        value_lbl.setMinimumWidth(48)

        def moved(position, item=tweak):
            item.value = control.clamp(round(control.min + position * control.step, 6))
            value_lbl.setText(str(item.value))
        slider.valueChanged.connect(moved)
        row_layout.addWidget(slider, 1)
        row_layout.addWidget(value_lbl)
        return row
