"""Standalone page for imported .batter tweak templates."""
from PySide6.QtCore import QCoreApplication, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from src.gui.theme import ColorThemeManager, t
from src.gui.widgets import IOSCard, IOSPrimaryButton
from src.tweaks.tweaks import TweakID, tweaks

BATTER_BUILDER_URL = "https://github.com/GoldenNugget-Team/GoldenNugget-TemplateBuilder/releases/latest"


class IOSTemplatesPage(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._create_content())
        ColorThemeManager.instance().theme_changed.connect(self._retheme)
        self._retheme()

    def _retheme(self):
        self.setStyleSheet(t("page_bg"))
        self._templates_scroll.setStyleSheet(t("page_bg"))
        self.templates_placeholder.setStyleSheet(t("templates_caption"))
        self._builder_icon.setStyleSheet(t("templates_builder_icon"))
        self._builder_title.setStyleSheet(t("templates_builder_title"))
        self._builder_subtitle.setStyleSheet(t("templates_caption"))
        self._builder_chevron.setStyleSheet(t("templates_builder_chevron"))

    def _create_content(self) -> QWidget:
        self._templates_scroll = QScrollArea()
        self._templates_scroll.setWidgetResizable(True)
        self._templates_scroll.setFrameStyle(QScrollArea.NoFrame)

        content = QWidget()
        self.templates_layout = QVBoxLayout(content)
        self.templates_layout.setContentsMargins(16, 16, 16, 32)
        self.templates_layout.setSpacing(12)
        self.templates_layout.setAlignment(Qt.AlignTop)
        self._templates_scroll.setWidget(content)

        import_btn = IOSPrimaryButton(QCoreApplication.translate("Nugget", "  Import Templates (.batter)"))
        import_btn.clicked.connect(self.show_add_templates_dialog)
        self.templates_import_btn = import_btn
        self.templates_layout.addWidget(import_btn)

        self.templates_builder_card = self._create_builder_card()
        self.templates_layout.addWidget(self.templates_builder_card)

        self.templates_placeholder = QLabel(QCoreApplication.translate("Nugget", "No templates added yet"))
        self.templates_placeholder.setAlignment(Qt.AlignCenter)
        self.templates_layout.addWidget(self.templates_placeholder)

        self._load_templates_list()

        return self._templates_scroll

    def _create_builder_card(self) -> QWidget:
        """A row that opens Batter Builder's download page, for people who
        want to make a template of their own instead of writing JSON."""
        card = IOSCard()
        card.setCursor(Qt.PointingHandCursor)
        card.setMinimumHeight(88)
        card.mousePressEvent = lambda e: self.open_batter_builder()

        inner = QHBoxLayout(card)
        inner.setContentsMargins(16, 12, 16, 12)
        inner.setSpacing(12)

        self._builder_icon = QLabel()
        self._builder_icon.setFixedSize(48, 48)
        self._builder_icon.setAlignment(Qt.AlignCenter)
        self._builder_icon.setText("\u270E")
        inner.addWidget(self._builder_icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._builder_title = QLabel(QCoreApplication.translate("Nugget", "Create Your Own Template"))
        text_col.addWidget(self._builder_title)
        self._builder_subtitle = QLabel(QCoreApplication.translate(
            "Nugget", "Batter Builder makes switches, sliders and lists without writing JSON"))
        self._builder_subtitle.setWordWrap(True)
        text_col.addWidget(self._builder_subtitle)
        inner.addLayout(text_col, 1)

        self._builder_chevron = QLabel("\u203A")
        inner.addWidget(self._builder_chevron)

        return card

    def open_batter_builder(self):
        QDesktopServices.openUrl(QUrl(BATTER_BUILDER_URL))

    def show_add_templates_dialog(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        selected_files, _ = QFileDialog.getOpenFileNames(
            self.window, QCoreApplication.translate("Nugget", "Select Nugget Template Files"), "", "Zip Files (*.batter)"
        )
        if selected_files:
            templates_tweak = tweaks[TweakID.Templates]
            try:
                device_version = self.window.device_manager.get_current_device_version()
            except Exception:
                device_version = None
            for file in selected_files:
                try:
                    templates_tweak.add_template(file, device_version)
                except Exception as e:
                    QMessageBox.warning(self.window, QCoreApplication.translate("Nugget", "Import Failed"), QCoreApplication.translate("Nugget", "Failed to load template:\n{0}\n\n{1}").format(file, str(e)))
            self._load_templates_list()

    def _load_templates_list(self):
        templates = tweaks[TweakID.Templates].templates
        for i in reversed(range(self.templates_layout.count())):
            widget = self.templates_layout.itemAt(i).widget()
            if widget is not None and widget not in (self.templates_placeholder, self.templates_import_btn,
                                                     self.templates_builder_card):
                self.templates_layout.takeAt(i)
                widget.deleteLater()

        self.templates_placeholder.setVisible(not templates)

        widgets = {}
        for template in templates:
            template.loaded = False  # its old card was just removed
            template.create_ui(self.window, tweaks[TweakID.Templates], widgets, self.templates_layout)
