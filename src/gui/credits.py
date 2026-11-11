"""Shared project credits for the About dialog and idle support panel."""
from pathlib import Path

from PySide6.QtCore import QT_TRANSLATE_NOOP

CREDITS = [
    (QT_TRANSLATE_NOOP("SupportPanel", "Owner / Main Developer"), "awesomenull", "https://github.com/awesomenull-dev"),
    (QT_TRANSLATE_NOOP("SupportPanel", "Co-Developer"), "Windows11Aero", "https://github.com/Wind0ws11Aero"),
    (QT_TRANSLATE_NOOP("SupportPanel", "Co-Developer"), "kik4311", "https://github.com/kik4311"),
    (QT_TRANSLATE_NOOP("SupportPanel", "Nugget Creator"), "leminlimez", "https://github.com/leminlimez"),
    (QT_TRANSLATE_NOOP("SupportPanel", "UI Designer"), "@omaw", "https://discord.com/users/1155026301791514655"),
    (QT_TRANSLATE_NOOP("SupportPanel", "Icon Artwork"), "mekabrine", "https://discord.com/users/1196529222617923660"),
    (QT_TRANSLATE_NOOP("SupportPanel", "Interface Icons"), "Lucide contributors", "https://github.com/lucide-icons"),
    (QT_TRANSLATE_NOOP("SupportPanel", "Inter Font"), "Rasmus Andersson", "https://github.com/rsms"),
    (QT_TRANSLATE_NOOP("SupportPanel", "PosterRestore Team"), "PosterRestore Discord", "https://discord.com/invite/gWtzTVhMvh"),
    (QT_TRANSLATE_NOOP("SupportPanel", "PosterBoard Help"), "dootskyre, Middo, dulark, forcequitOS, pengubow", "https://x.com/dootskyre"),
    (QT_TRANSLATE_NOOP("SupportPanel", "Wallpaper Website"), "SerStars", "https://github.com/SerStars"),
    (QT_TRANSLATE_NOOP("SupportPanel", "Global Flags"), "disfordottie", "https://x.com/disfordottie"),
    (QT_TRANSLATE_NOOP("SupportPanel", "Springboard/Internal"), "iTechExpert", "https://x.com/iTechExpert21"),
    (QT_TRANSLATE_NOOP("SupportPanel", "Quiet Daemon"), "Mikasa-san", "https://github.com/Mikasa-san"),
    (QT_TRANSLATE_NOOP("SupportPanel", "Additional Daemons"), "MiniVoidyy", "https://github.com/MiniVoidyy"),
    (QT_TRANSLATE_NOOP("SupportPanel", "pymobiledevice3"), "doronz88", "https://github.com/doronz88"),
    (QT_TRANSLATE_NOOP("SupportPanel", "PySide6"), "Qt Company", "https://github.com/qt"),
    (QT_TRANSLATE_NOOP("SupportPanel", "Video Processing"), "FFmpeg contributors", "https://github.com/FFmpeg"),
    (QT_TRANSLATE_NOOP("SupportPanel", "FFmpeg Python Bindings"), "Karl Kroening", "https://github.com/kkroening"),
    (QT_TRANSLATE_NOOP("SupportPanel", "Image & Video Decoding"), "OpenCV contributors", "https://github.com/opencv"),
    (QT_TRANSLATE_NOOP("SupportPanel", "HEIF Image Decoding"), "pillow-heif contributors", "https://github.com/bigcat88"),
    (QT_TRANSLATE_NOOP("SupportPanel", "AAR Handling"), "Snoolie", "https://github.com/0xilis"),
    (QT_TRANSLATE_NOOP("SupportPanel", "AI Eligibility"), "f1shy-dev", "https://github.com/f1shy-dev"),
    (QT_TRANSLATE_NOOP("SupportPanel", "AI Eligibility"), "mattisklein (Project Linwood)", "https://github.com/mattisklein"),
    (QT_TRANSLATE_NOOP("SupportPanel", "PosterBoard Icons"), "JJTech", "https://github.com/JJTech0130"),
    (QT_TRANSLATE_NOOP("SupportPanel", "AirLift"), "0xjohnnydev", "https://github.com/0xjohnnydev"),
    (QT_TRANSLATE_NOOP("SupportPanel", "Translations"), QT_TRANSLATE_NOOP("SupportPanel", "GoldenNugget translation contributors"), "https://github.com/GoldenNugget-Team/gNugget-i18n"),
    (QT_TRANSLATE_NOOP("SupportPanel", "Legacy Translations"), QT_TRANSLATE_NOOP("SupportPanel", "Nugget translation contributors"), "https://poeditor.com/join/project/UTqpVSE2UD"),
]

CREDIT_AVATARS = {
    "https://github.com/qt":
        str(Path(__file__).resolve().parents[1] / "qt" / "credits" / "pyside6.png"),
    "https://x.com/disfordottie":
        str(Path(__file__).resolve().parents[1] / "qt" / "credits" / "disfordottie.jpg"),
    "https://x.com/iTechExpert21":
        str(Path(__file__).resolve().parents[1] / "qt" / "credits" / "itech-expert.jpg"),
    "https://discord.com/users/1196529222617923660":
        str(Path(__file__).resolve().parents[1] / "qt" / "credits" / "mekabrine.webp"),
}

CREDIT_AVATAR_SOURCES = {
    "https://discord.com/users/1155026301791514655": "https://cdn.discordapp.com/avatars/1155026301791514655/12d356cca58336f257325c18b72b9211.webp?size=2048",
}
