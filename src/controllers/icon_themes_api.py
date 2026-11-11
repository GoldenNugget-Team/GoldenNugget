"""Online icon-theme pack catalog for the Icon Themes page.

Port of Cowabunga's ``CowabungaAPI`` (leminlimez/Cowabunga-explore-repo):
the repo publishes ``icon-themes.json`` at its HEAD, each entry pointing at a
``.zip`` bundle of icons named ``<bundleID>[-large|@2x|@3x].png`` plus a
preview image. The dialog does the actual HTTP through ``QNetworkAccessManager``;
these helpers only build URLs and parse bytes so the log files stay readable
and the format can change in one place.
"""

import json
from dataclasses import dataclass

# The explore repo serves raw files per-branch; "main" is always the HEAD,
# the same mechanism the wallpaper catalog uses.
ICON_THEMES_BASE = "https://raw.githubusercontent.com/leminlimez/Cowabunga-explore-repo/main/"


class IconThemesAPIError(Exception):
    pass


@dataclass
class DownloadableTheme:
    """One downloadable icon pack from the explore repo."""
    name: str
    description: str
    url: str
    preview: str
    author: str = ""
    version: str = ""

    @property
    def download_url(self) -> str:
        return ICON_THEMES_BASE + self.url

    @property
    def preview_url(self) -> str:
        return ICON_THEMES_BASE + self.preview


def catalog_url() -> str:
    return ICON_THEMES_BASE + "icon-themes.json"


def parse_catalog(data: bytes) -> list[DownloadableTheme]:
    """Parse the ``icon-themes.json`` payload into themes."""
    try:
        items = json.loads(data)
    except ValueError as e:
        raise IconThemesAPIError(f"Invalid icon-themes.json payload: {e}") from e
    themes = []
    for item in items:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        contact = item.get("contact") or {}
        try:
            author = ", ".join(str(v) for v in contact.values())
        except Exception:
            author = ""
        themes.append(DownloadableTheme(
            name=str(item["name"]),
            description=str(item.get("description", "")),
            url=str(item.get("url", "")),
            preview=str(item.get("preview", "")),
            author=author,
            version=str(item.get("version", "")),
        ))
    return themes