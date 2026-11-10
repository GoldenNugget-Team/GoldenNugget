#!/usr/bin/env python3
"""Offline test for the protective backup keep-set filters (no device needed).

Exercises both HomeDomain filter paths — _is_protective_file (prune /
clean_backup_for_restore) and is_protective_device_file (mid-stream capture):
Shortcuts, WebClips (incl. PWA .webclip/Storage payloads), WebApp and
WebKit/WebsiteData web-app data, SpringBoard, ControlCenter. Also asserts the
non-kept droppings stay dropped. Run: python tools/test_protective_filters.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.restore.protective import (
    WEB_APP_PATH_PREFIXES,
    WEB_CLIPS_PATH_PREFIXES,
    WEBKIT_WEBSITE_DATA_PATH_PREFIXES,
    _is_protective_file,
    is_protective_device_file,
)
from src.tweaks.registry import managed_pref_app_plists

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAILED: {name}"
    PASS += 1
    print(f"  ok: {name}")


def pwa_webclip_file(rel):
    """A path inside a <.webclip>/Storage tree (kept via Library/WebClips)."""
    return f"Library/WebClips/{rel}"


def both_filters_fail_check(label, rel):
    check(f"{label}: _is_protective_file", _is_protective_file("HomeDomain", rel))
    check(f"{label}: is_protective_device_file",
          is_protective_device_file(f"HomeDomain/{rel}"))


print("== WebClips + PWA storage (already kept) ==")
for rel in (
    "A1B2.webclip/Info.plist",
    "A1B2.webclip/icon.png",
    "A1B2.webclip/ApplicationManifest",
    "A1B2.webclip/Storage/___IndexedDB/leveldb/CURRENT",
    "A1B2.webclip/Storage/Default/salt",
    "A1B2.webclip/Storage/default-abc123/LocalStorage/localstorage.sqlite3",
    "A1B2.webclip/Storage/Cookies/Cookies.binarycookies",
    "A1B2.webclip/Storage/MediaCache/CachedMedia-x1",
):
    both_filters_fail_check(f"WebClips {os.path.basename(rel)}", pwa_webclip_file(rel))

print("== WebApp + WebKit/WebsiteData PWA data (newly kept) ==")
for rel in (
    "Library/WebApp/WebAppLocalStorage/A1B2.webclip/0000000000000002.sqlite3",
    "Library/WebApp/WebAppCache/A1B2.webclip",
    "Library/WebKit/WebsiteData/Default/org.example.pwa/ServiceWorkers/..."
    "/ServiceWorkerRegistrations.sqlite3",
    "Library/WebKit/WebsiteData/Default/org.example.pwa/IndexedDB/.../"
    "indexeddb.sqlite3",
    "Library/WebKit/WebsiteData/Default/org.example.pwa/SuspendedState.db",
    "Library/WebKit/WebsiteData/salt",
):
    both_filters_fail_check(f"PWA data {os.path.basename(rel)}", rel)

print("== Ensure constants cover what they claim ==")
check("WEB_APP prefix", any("Library/WebApp" in p for p in WEB_APP_PATH_PREFIXES))
check("WEB_CLIPS prefix", any("Library/WebClips" in p for p in WEB_CLIPS_PATH_PREFIXES))
check("WEBKIT WebsiteData prefix", any("Library/WebKit/WebsiteData" in p for p in WEBKIT_WEBSITE_DATA_PATH_PREFIXES))

print("== Non-kept files stay dropped ==")
for label, rel in (
    ("Safari home page", "Library/Safari/StartPage.html"),
    ("WebCache", "Library/Caches/com.apple.WebKit/NetworkCache/xxx"),
    ("Notes", "Library/Notes/accounts.sqlite"),
    ("Mail", "Library/Mail/Protected/protected cloud.mail"),
):
    if "Safari" in label or "WebCache" in label:
        check(f"drop {label}", not _is_protective_file("HomeDomain", rel))
        check(f"drop-device {label}", not is_protective_device_file(f"HomeDomain/{rel}"))

print("== Preference baselines are retained for keyed merging ==")
for rel in sorted(managed_pref_app_plists()):
    check(f"baseline retained: {rel}", _is_protective_file("HomeDomain", rel))
# neighbouring user prefs in the same directory are untouched
check("IconState prefs kept",
      _is_protective_file("HomeDomain", "Library/Preferences/IconState.plist"))
check("com.apple.Preferences kept",
      _is_protective_file("HomeDomain", "Library/Preferences/com.apple.Preferences.plist"))

print("== Status bar override files stay out of the backup (both spellings) ==")
# Phase 3 restores Library/SpringBoard AFTER the sparse reset rewrote the
# status bar override, handing the stale value straight back — the reset looked
# like it did nothing. The classic struct (lowercase "s") and the iOS 27
# archive (capital "S", which the lowercase prefix does NOT match) must both be
# excluded; the same directory's other SpringBoard state is still kept.
check("classic statusBarOverrides dropped",
      not _is_protective_file("HomeDomain", "Library/SpringBoard/statusBarOverrides"))
check("iOS 27 StatusBarOverrides.archive dropped",
      not _is_protective_file("HomeDomain", "Library/SpringBoard/StatusBarOverrides.archive"))
check("neighbouring SpringBoard state kept",
      _is_protective_file("HomeDomain", "Library/SpringBoard/IconState.plist"))

print(f"\nAll {PASS} checks passed")