"""Passcode keypad themes (``.passthm``) for iOS 27.

A ``.passthm`` package is a zip of TelephonyUI keypad key images. GoldenNugget
ships it to the device via the cross-platform AirLift driver (``src/airlift``)
into ``/var/mobile/Library/Caches/TelephonyUI-10``.

Staging follows AirCard-iOS (``Mak5er/AirCard``): every key image is renamed for
each configured keypad locale and bold weight to the layout the passcode keypad
expects:

* ``{lang}-{digit}---white[-bold].png``            blank variant
* ``{lang}-0-+--white[-bold].png``                 plus variant   (digit 0)
* ``{lang}-{digit}-{subtext}--white[-bold].png``   latin subtext
* ``{lang}-{digit}-{cyrillic}--white[-bold].png``  ru/uk subtext
* ``_big``                                          empty @3x indicator marker
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from typing import Optional

PASSTHME_TARGETS_ALL = (
    "/var/mobile/Library/Caches/TelephonyUI-10",
    "/var/mobile/Library/Caches/TelephonyUI-9",
    "/var/mobile/Library/Caches/TelephonyUI-8",
)

KEYPAD_LOCALES_ALL = [
    "en", "other", "ru", "uk", "es", "fr", "de", "it", "pt",
    "tr", "pl", "nl", "ja", "ko", "zh", "ar", "he",
]

CYRILLIC_RU = {
    "2": "А Б В Г",
    "3": "Д Е Ж З",
    "4": "И Й К Л",
    "5": "М Н О П",
    "6": "Р С Т У",
    "7": "Ф Х Ц Ч",
    "8": "Ш Щ Ъ Ы",
    "9": "Ь Э Ю Я",
}

CYRILLIC_UK = {
    "2": "А Б В Г",
    "3": "Д Е Ж З",
    "4": "І Ї Й К",
    "5": "Л М Н О",
    "6": "П Р С Т",
    "7": "У Ф Х Ц",
    "8": "Ч Ш Щ Ь",
    "9": "Ю Я",
}

SUBTEXTS = {
    "0": "+",
    "1": "",
    "2": "A B C",
    "3": "D E F",
    "4": "G H I",
    "5": "J K L",
    "6": "M N O",
    "7": "P Q R S",
    "8": "T U V",
    "9": "W X Y Z",
}

DIGITS = [str(index) for index in range(10)]


class PasscodeThemeError(RuntimeError):
    """Raised when a ``.passthm`` package is invalid or unreadable."""


def extract_digit(filename: str) -> Optional[str]:
    """Extract the keypad digit from a theme image file name (AirCard rules)."""
    stem = posixpath.basename(filename)
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    stem_clean = (
        stem.replace("--white", "")
        .replace("-white", "")
        .replace("@3x", "")
        .replace("@2x", "")
    )
    match = re.search(r"(?:^[a-zA-Z]+-)?([0-9*#])", stem_clean)
    if match:
        digit = match.group(1)
        if digit in "0123456789":
            return digit
    for character in stem_clean:
        if character in "0123456789":
            return character
    return None


def keypad_code_for_locale(locale: str) -> str:
    """Map a device locale to a keypad language code (default ``other``)."""
    code = (locale or "").lower().replace("_", "-").split("-")[0]
    if code in ("ru", "uk"):
        return code
    if code in KEYPAD_LOCALES_ALL:
        return code
    return "other"


def parse_passthm(theme_path: str) -> dict[str, bytes]:
    """Collect the first key image bytes per digit from a ``.passthm`` zip.

    Raises :class:`PasscodeThemeError` when the package does not look like a
    passthemes theme (no ``TelephonyUI-`` folder) or has no key images.
    """
    try:
        archive = zipfile.ZipFile(theme_path, mode="r")
    except (zipfile.BadZipFile, OSError) as error:
        raise PasscodeThemeError(f"not a valid zip: {error}") from error

    with archive:
        names = archive.namelist()
        if not any("TelephonyUI-" in name for name in names):
            raise PasscodeThemeError(
                "not a passthemes package (no 'TelephonyUI-' folder inside)"
            )
        keys: dict[str, bytes] = {}
        for name in names:
            if name.startswith(".") or "__MACOSX" in name:
                continue
            if not name.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            digit = extract_digit(name)
            if digit is None or digit in keys:
                continue
            keys[digit] = archive.read(name)
        if not keys:
            raise PasscodeThemeError("no passcode key images found in package")
        return keys


def theme_size(theme_path: str, keys: Optional[dict[str, bytes]] = None) -> int:
    """Detect the key size marker from the package (0 none, 1 small, 2 big)."""
    try:
        with zipfile.ZipFile(theme_path, mode="r") as archive:
            if any(name.endswith("_small") for name in archive.namelist()):
                return 1
            if any(name.endswith("_big") for name in archive.namelist()):
                return 2
    except (zipfile.BadZipFile, OSError):
        pass
    return 0


def stage_files(
    keys: dict[str, bytes],
    *,
    locale: str = "en",
    langs: Optional[list[str]] = None,
    bold: str = "both",
    include_big_marker: bool = True,
) -> list[tuple[str, bytes]]:
    """Stage key images into device file names for the passcode keypad.

    :param keys: digit -> raw image bytes (from :func:`parse_passthm`).
    :param locale: device locale used to pick the primary language when
        ``langs`` is not given.
    :param langs: explicit keypad language list; ``"all"`` selects every
        locale. Default: primary language + ``other`` + the device locale.
    :param bold: ``"both"`` (regular + bold), ``"regular"`` or ``"bold"``.
    :returns: list of ``(relative_file_name, bytes)`` including the empty
        ``_big`` marker when requested.
    """
    if bold == "regular":
        bold_suffixes = [""]
    elif bold == "bold":
        bold_suffixes = ["-bold"]
    else:
        bold_suffixes = ["", "-bold"]

    detected = keypad_code_for_locale(locale)

    if langs == "all":
        languages = list(KEYPAD_LOCALES_ALL)
    elif langs:
        languages = list(langs)
    else:
        languages = [detected]
        if detected != "other":
            languages.append("other")

    files: list[tuple[str, bytes]] = []
    for digit in DIGITS:
        if digit not in keys:
            continue
        image = keys[digit]
        subtext = SUBTEXTS.get(digit, "")
        for language in languages:
            for suffix in bold_suffixes:
                if digit == "0":
                    files.append((f"{language}-0---white{suffix}.png", image))
                    files.append((f"{language}-0-+--white{suffix}.png", image))
                elif digit == "1":
                    files.append((f"{language}-1---white{suffix}.png", image))
                else:
                    files.append((f"{language}-{digit}---white{suffix}.png", image))
                    if subtext:
                        files.append((f"{language}-{digit}-{subtext}--white{suffix}.png", image))
                        no_space = subtext.replace(" ", "")
                        if no_space != subtext:
                            files.append((f"{language}-{digit}-{no_space}--white{suffix}.png", image))
                    cyrillic = (
                        CYRILLIC_RU.get(digit)
                        if language == "ru"
                        else CYRILLIC_UK.get(digit)
                    )
                    if cyrillic and (language in ("ru", "uk") or languages == KEYPAD_LOCALES_ALL):
                        files.append((f"{language}-{digit}-{cyrillic}--white{suffix}.png", image))
    if include_big_marker:
        files.append(("_big", b""))
    return files


