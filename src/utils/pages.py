"""Shared page-identifier enum used by both the GUI and the backend reset flow.

Historically defined in ``src/gui/pages/pages_list.py``; it moved here so the
backend (``device_manager`` reset pass) no longer imports the GUI package.
``src/gui/pages/pages_list.py`` re-exports both symbols for the GUI side.
"""

from enum import Enum


class Page(Enum):
    Home = 0
    Gestalt = 1
    EUEnabler = 2
    StatusBar = 3
    Springboard = 4
    InternalOptions = 5
    LiquidGlass = 6
    Daemons = 7
    Posterboard = 8
    Templates = 9
    Passcode = 10
    RiskyTweaks = 11
    Tweaks = 12
    Apply = 13
    Settings = 14

    def getPageName(self) -> str:
        name_map = [
            "Home",
            "Mobile Gestalt",
            "Eligibility",
            "Status Bar",
            "Springboard",
            "Internal",
            "Liquid Glass",
            "Daemons",
            "PosterBoard",
            "Templates",
            "Passcode",
            "Resolution Modifications",
            "Tweaks",
            "Apply",
            "Settings"
        ]
        return name_map[self.value]

def get_resettable_pages(device_manager) -> list[Page]:
    # Status Bar is resettable on every supported version. On iOS 27 the
    # carrier override lives in StatusBarOverrides.archive and the reset record
    # SpringBoard unlinks brings the stock carrier name back, so the old
    # "no write permissions for Speakeasy flags" exclusion is stale. The
    # parameter is kept for callers (GUI/CLI) that still pass a device manager.
    pages = [Page.StatusBar, Page.Springboard, Page.LiquidGlass, Page.InternalOptions, Page.Daemons]
    # Templates: only once community tweaks from .batter templates have
    # written something to this iPhone (see community_tweaks.write_record).
    try:
        from src.tweaks.posterboard.community_tweaks import load_record
        if load_record(device_manager.get_current_device_udid()):
            pages.append(Page.Templates)
    except Exception:
        pass
    return pages
