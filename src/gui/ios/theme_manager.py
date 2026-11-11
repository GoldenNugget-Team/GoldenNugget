from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QStackedWidget, QWidget


class ThemeManager:
    CLASSIC = 0
    IOS = 1

    def __init__(self, parent: QWidget):
        self.parent = parent
        self.settings = QSettings("GoldenNugget", "GoldenNugget")
        self.stack = QStackedWidget(parent)
        # Classic container will be inserted by integration
        # IOS container will be added by screens

        self.current_theme = self.load_theme()

    def load_theme(self) -> int:
        # TEMP: Classic UI removed — always load the iOS-style interface.
        # Revert to the persisted ``ui/theme`` once Classic is back.
        return self.IOS

    def save_theme(self, theme: int):
        val = "ios" if theme == self.IOS else "classic"
        self.settings.setValue("ui/theme", val)
        self.current_theme = theme

    def set_classic_widget(self, widget: QWidget):
        if self.stack.count() == 0:
            self.stack.addWidget(widget)
        else:
            self.stack.insertWidget(0, widget)

    def set_ios_widget(self, widget: QWidget):
        # Replace existing iOS index or add at 1
        if self.stack.count() > 1:
            self.stack.removeWidget(self.stack.widget(1))
        self.stack.addWidget(widget)
        self.stack.setCurrentIndex(1 if self.current_theme == self.IOS else 0)

    def switch_to(self, theme: int):
        # container switching is handled by MainWindow.apply_theme()
        self.save_theme(theme)
