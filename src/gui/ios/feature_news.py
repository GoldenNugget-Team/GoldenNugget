"""Shared presentation for recently added controls."""
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel

from src.controllers.feature_news import FeatureNews


def control_title(title):
    return re.sub(r'\s*\((?:Unverified )?Experiment(?:al)?\)\s*', ' ', title, flags=re.IGNORECASE).strip()


def add_new_badge(layout, key, parent=None, index=None):
    remaining = FeatureNews.instance().remaining(key)
    if not remaining:
        return
    badge = QLabel('NEW', parent)
    badge.setAlignment(Qt.AlignCenter)
    badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    badge.setFixedHeight(22)
    badge.setStyleSheet('QLabel { background: #c62828; color: white; font-size: 10px; '
                       'font-weight: 700; border-radius: 5px; padding: 2px 7px; }')
    badge.setAccessibleName(badge.tr('Added within the last three days'))
    if index is None:
        layout.addWidget(badge)
    else:
        layout.insertWidget(index, badge)
    expiry = QTimer(badge)
    expiry.setSingleShot(True)
    expiry.timeout.connect(badge.hide)
    expiry.start(max(1, int(remaining * 1000)))
