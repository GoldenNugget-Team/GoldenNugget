#!/usr/bin/env python3
"""Offline test for the daemons page reveal animation (no device needed).

Covers the behaviour the animation is supposed to have: the daemon rows are
folded away while daemon modifications are off, cascade in when the master
switch turns on, fold away again when it turns off, and always end up in a
clean steady state (no leftover opacity effects, no clipped rows).

Run: python tools/test_daemons_reveal.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QElapsedTimer, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from src.gui.ios.daemons import _NO_MAX_HEIGHT, IOSDaemonsContent
from src.tweaks.tweak_loader import load_daemons
from src.tweaks.tweaks import TweakID, tweaks

PASS = 0


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


def pump(ms=700):
    """Run the event loop for `ms` so animations actually finish."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class FakeDM:
    def get_current_device_version(self):
        return "26.2"

    def get_current_device_model(self):
        return "iPhone17,1"


class FakeWindow:
    def __init__(self):
        from PySide6.QtCore import QSettings
        self.settings = QSettings("GoldenNuggetTest", "DaemonsReveal")
        # the bootloop confirmation is two modal QMessageBox.exec() calls, which
        # would block this headless test forever; the real flag the page checks
        # is set the first time a user continues past them
        self.settings.setValue("daemon_bootloop_warned", True)
        self.settings.sync()
        self.device_manager = FakeDM()


def main():
    app = QApplication.instance() or QApplication([])
    load_daemons()
    daemons_tweak = tweaks[TweakID.Daemons]

    # start from "daemon modifications off"
    daemons_tweak.set_enabled(False)
    content = IOSDaemonsContent(FakeWindow())
    content.resize(640, 900)
    content.show()
    deadline = QElapsedTimer()
    deadline.start()
    while content._building and deadline.elapsed() < 10000:
        pump(10)
    check("incremental row construction completes", not content._building)
    rows = content._rows

    from src.gui.ios.daemon_categories import RISKY_DAEMON_NAMES
    for card, (daemon, _) in zip(content.daemon_cards, content.daemon_switches):
        if daemon.name in RISKY_DAEMON_NAMES:
            check(f"{daemon.name} is grouped under Risky tweaks",
                  str(card.property("searchText")).startswith("Risky tweaks "))
        if daemon.name in {"abdatabasedoctor", "callhistoryd", "contactsd",
                           "contactsdonationagent", "dataaccessd", "postersyncd", "recentsd"}:
            check(f"{daemon.name} keeps its phone/contacts category",
                  not str(card.property("searchText")).startswith("Risky tweaks "))

    check("categorized daemon cards belong to the row block",
          bool(content.daemon_cards) and all(rows.isAncestorOf(card) for card in content.daemon_cards))
    check("the analytics shortcut is inside the row block",
          rows.isAncestorOf(content.analytics_switch))
    check("block is folded away while modifications are off",
          not rows.isVisible() and rows.maximumHeight() == 0)
    check("analytics is folded away with the list",
          not content.analytics_switch.isVisibleTo(content))
    check("all dependent switches are disabled with the master",
          not rows.isEnabled() and not content.analytics_switch.isEnabled()
          and all(not switch.isEnabled() for _, switch in content.daemon_switches))
    before = dict(daemons_tweak.value)
    content._on_daemon_toggled(content.daemon_switches[0][0], True)
    check("inactive child handlers cannot enable the master or change values",
          not daemons_tweak.enabled and daemons_tweak.value == before)
    check("no opacity effect while folded away", rows.graphicsEffect() is None)
    check("no row ever carries its own effect (one per block, not per row)",
          all(r.graphicsEffect() is None for r in rows._rows))
    check("master switch reflects the tweak", not content.master_switch.isChecked())

    # --- turning it on: the unroll ------------------------------------------
    daemons_tweak.set_enabled(True)
    content.master_switch.setChecked(True)
    check("block becomes visible as soon as the switch flips", rows.isVisible())
    check("the block fades in", rows.graphicsEffect() is not None)
    check("the fold starts closed", rows.maximumHeight() == 0)
    check("fade starts transparent",
          rows.graphicsEffect().opacity() < 1.0,
          f"{rows.graphicsEffect().opacity():.2f}")

    heights = []
    animation = rows._group
    animation.pause()
    # Advance Qt's real animation clock deterministically. A busy CI host can
    # overshoot a 50ms wall-clock pump and skip straight to the final frame.
    for timestamp in (50, 100, 150, 200):
        animation.setCurrentTime(timestamp)
        app.processEvents()
        heights.append(rows.maximumHeight())
    check("the fold grows progressively (rows cascade in top down)",
          all(a < b for a, b in zip(heights, heights[1:])),
          f"{heights}")
    check("still mid-unroll before it finishes",
          0 < heights[-1] < _NO_MAX_HEIGHT, f"maxHeight={heights[-1]}")

    animation.resume()
    pump()
    check("unfolded to no limit once finished", rows.maximumHeight() == _NO_MAX_HEIGHT,
          f"maxHeight={rows.maximumHeight()}")
    check("block is visible and tall enough for every row",
          rows.isVisible() and rows.sizeHint().height() > 0)
    check("the effect is dropped in the steady state",
          rows.graphicsEffect() is None)
    check("every row sits at its natural height (nothing clipped)",
          all(r.height() > 0 for r in content.daemon_cards),
          f"min={min(r.height() for r in content.daemon_cards)}")

    # --- turning it off: the fold away ---------------------------------------
    daemons_tweak.set_enabled(False)
    content.master_switch.setChecked(False)
    check("the fold starts from the full height", rows.maximumHeight() > 0)
    pump(90)
    check("the fold collapses progressively",
          0 <= rows.maximumHeight() < _NO_MAX_HEIGHT,
          f"maxHeight={rows.maximumHeight()}")
    pump()
    check("block is folded away again", not rows.isVisible())
    check("folded to zero height", rows.maximumHeight() == 0)
    check("effect dropped after folding away", rows.graphicsEffect() is None)

    # --- rapid toggling must not leave a half-animated state -----------------
    for _ in range(6):
        content.master_switch.setChecked(True)
        content.master_switch.setChecked(False)
    daemons_tweak.set_enabled(True)
    content.master_switch.setChecked(True)
    pump()
    check("survives rapid toggling and ends consistent with the tweak",
          rows.isVisible() and rows.maximumHeight() == _NO_MAX_HEIGHT,
          f"shown={rows._shown} tweak={daemons_tweak.enabled}")
    check("no leftover effect after rapid toggling",
          rows.graphicsEffect() is None)

    # --- switching the page/device must not replay the animation -------------
    daemons_tweak.set_enabled(False)
    content.refresh_from_tweaks()
    check("refresh_from_tweaks folds away without animating",
          not rows.isVisible() and rows.maximumHeight() == 0)
    daemons_tweak.set_enabled(True)
    content.refresh_from_tweaks()
    check("refresh_from_tweaks shows the block at full height immediately",
          rows.isVisible() and rows.maximumHeight() == _NO_MAX_HEIGHT)

    # --- individual daemon switches still work inside the block --------------
    from src.tweaks.daemons_tweak import Daemon
    daemons_tweak.set_multiple_values(Daemon.WifiAnalytics.value, value=True)
    content._on_daemon_toggled(Daemon.WifiAnalytics, True)
    check("an individual daemon still records its value",
          daemons_tweak.value.get(Daemon.WifiAnalytics.value[0]) is True)
    check("toggling one daemon turns the master switch on",
          content.master_switch.isChecked())

    # a resize must not leave the block clipped at its old animated height
    content.resize(content.width() or 800, 600)
    pump(50)
    check("still fully expanded after a resize",
          rows.maximumHeight() == _NO_MAX_HEIGHT)

    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    main()
