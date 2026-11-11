"""Card that shows a RiskReport: the verdict and its most serious reasons."""
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from src.controllers.risk_assessment import RiskLevel
from src.gui.theme import ColorThemeManager
from src.gui.theme.theme_manager import connect_visible_theme

_SLOTS = {RiskLevel.LOW: "success", RiskLevel.MEDIUM: "warning", RiskLevel.HIGH: "error"}


class RiskPanel(QFrame):
    MAX_ROWS = 4

    def __init__(self, report, parent=None):
        super().__init__(parent)
        self.setObjectName("riskPanel")
        self.report = report
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        self._dot = QLabel("●")
        self._title = QLabel(report.level.label())
        self._title.setObjectName("riskTitle")
        head.addWidget(self._dot)
        head.addWidget(self._title, 1)
        layout.addLayout(head)

        factors = report.sorted_factors()
        if not factors:
            factors_text = [QCoreApplication.translate(
                "RiskAssessment", "Nothing in this selection is known to cause problems.")]
        else:
            factors_text = ["• " + factor.text for factor in factors[:self.MAX_ROWS]]
            if len(factors) > self.MAX_ROWS:
                factors_text.append(QCoreApplication.translate(
                    "RiskAssessment", "…and {0} more").format(len(factors) - self.MAX_ROWS))
        self._rows = []
        for text in factors_text:
            row = QLabel(text)
            row.setWordWrap(True)
            row.setTextFormat(Qt.PlainText)
            layout.addWidget(row)
            self._rows.append(row)
        self.setToolTip("\n".join("• " + factor.text for factor in factors))
        self._retheme()
        connect_visible_theme(self)

    def _retheme(self):
        c = ColorThemeManager.instance().colors
        color = getattr(c, _SLOTS[self.report.level])
        self.setStyleSheet(f"""
            QFrame#riskPanel {{ background-color: {c.bg_secondary};
                border: 1px solid {c.border}; border-left: 4px solid {color};
                border-radius: 10px; }}
            QLabel {{ background-color: transparent; border: none;
                color: {c.text_secondary}; font-size: 13px; }}
            QLabel#riskTitle {{ color: {c.text_primary}; font-size: 15px; font-weight: 700; }}
        """)
        self._dot.setStyleSheet(f"color: {color}; font-size: 15px;")
