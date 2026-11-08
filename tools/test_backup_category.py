#!/usr/bin/env python3
"""Offline test for the backup progress category mapping (no device needed).

iOS 26 uploads domain-qualified names (``CameraRollDomain/Media/...``); iOS 27+
uploads the raw filesystem tree (``/.b/<n>/Media/...``). The progress label must
resolve both to the same category — an iOS 27 tree that falls through to the
generic "Device data" label is what made issue #81 look stuck on that phrase.

Run: python tools/test_backup_category.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication

from src.restore.protective import backup_category_for

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAILED: {name}"
    PASS += 1
    print(f"  ok: {name}")


def category(name):
    return backup_category_for(name).category


def label(name):
    return str(backup_category_for(name))


def main():
    app = QApplication.instance() or QApplication([])  # noqa: F841 (translate needs it)

    # --- iOS 26 domain-qualified names keep working -----------------------
    check("iOS 26 camera roll -> photos",
          category("CameraRollDomain/Media/DCIM/IMG_0001.JPG") == "photos")
    check("iOS 26 media domain -> photos",
          category("MediaDomain/Media/PhotoData/Photos.sqlite") == "photos")
    check("iOS 26 keychain -> keychain",
          category("KeychainDomain/keychain2.db") == "keychain")
    check("iOS 26 messages -> messages",
          category("MessagesDomain/Library/SMS/sms.db") == "messages")
    check("iOS 26 springboard -> home",
          category("HomeDomain/Library/Preferences/com.apple.springboard.plist") == "home")
    check("iOS 26 preferences -> settings",
          category("HomeDomain/Library/Preferences/com.apple.mobiletimer.plist") == "settings")
    check("iOS 26 accounts -> account",
          category("HomeDomain/Library/Accounts/Accounts3.sqlite") == "account")

    # --- iOS 27 physical tree resolves to the same categories -------------
    check("iOS 27 DCIM -> photos",
          category("/.b/12/Media/DCIM/100APPLE/IMG_0002.HEIC") == "photos")
    check("iOS 27 PhotoData -> photos",
          category("/.b/12/Media/PhotoData/Photos.sqlite") == "photos")
    check("iOS 27 keychains -> keychain",
          category("/.b/12/Keychains/keychain2.db") == "keychain")
    check("iOS 27 messages -> messages",
          category("/.b/12/Library/Messages/chat.db") == "messages")
    check("iOS 27 springboard plist -> home",
          category("/.b/12/Library/Preferences/com.apple.springboard.plist") == "home")
    check("iOS 27 other preferences -> settings",
          category("/.b/12/Library/Preferences/com.apple.mobiletimer.plist") == "settings")
    check("iOS 27 configuration profiles -> settings",
          category("/.b/12/Library/ConfigurationProfiles/CloudConfigurationDetails.plist") == "settings")
    check("iOS 27 accounts -> account",
          category("/.b/12/Library/Accounts/Accounts3.sqlite") == "account")
    check("iOS 27 webclips -> data",
          category("/.b/12/Library/WebClips/abc.webclip/Icon.png") == "backup")

    # --- wallpapers and the generic fallback ------------------------------
    check("posterboard container -> wallpaper",
          category("AppDomain-com.apple.PosterBoard/PRBPosterExtensionDataStoreSQLiteDatabase.sqlite3") == "wallpaper")
    check("iOS 27 posterboard container -> wallpaper",
          category("/.b/12/Containers/Data/Application/A1/Library/PosterBoard/Store/PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3") == "wallpaper")
    check("unknown name -> device data", category("SomethingElse/x.bin") == "backup")
    check("empty name -> device data", category("") == "backup")
    check("oversized generic label is Device data",
          label("SomethingElse/x.bin") == "Device data")

    # --- the label is a BackupStatus (carries the stage category) ---------
    result = backup_category_for("/.b/3/Media/DCIM/a.jpg")
    check("returns BackupStatus with category attribute",
          result.category == "photos" and str(result) == "Photos and videos")

    print(f"\n{PASS} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
