#!/usr/bin/env python3
"""Verify GoldenNugget plist tweaks against an iOS simulator.

================================================================================
WHAT THE SIMULATOR CAN AND CANNOT PROVE -- read this before trusting a result
================================================================================

CAN prove
    * a key is really read by the system (write it, restart the consumer,
      observe a change);
    * which preference *domain* owns the key (``defaults read <domain> <key>``);
    * the value type the consumer expects -- write the wrong type and the key is
      normally ignored;
    * for a numeric key that drives a UI picker, which stop a given number
      selects.

CANNOT prove
    * GoldenNugget's actual write path. Nugget writes
      ``/var/Managed Preferences/mobile/*.plist`` (``FileLocation.springboard``,
      ``.globalPreferences``, ``.uikit`` ...) == the ManagedPreferencesDomain.
      **The simulator does not implement Managed Preferences at all.** An
      overlay placed at the corresponding host path is silently ignored, while
      the identical key in HomeDomain is honoured. This tool therefore
      translates every Managed-Preferences destination to its HomeDomain
      equivalent and tests *key semantics*, not overlay semantics.
      (Measured 2026-09-12 on iOS 27 / 24A5380i.)
    * the three-phase restore and protective-backup exclusion logic.

So: a pass here means "iOS 27 really reacts to this key". It does NOT mean
"Nugget's backup will deliver it". The write path is verified separately
against a real device backup.

================================================================================
MEASURED NOISE FLOORS (iOS 27 sim, iPhone 18 Pro Max) -- these drive the rules
================================================================================
    consecutive frames, no action ........... 0.000%   (0 differing pixels)
    respring + wait-for-render .............. 0.000%   (0 differing pixels)
    full device reboot ..................... 35.688%   (!! unusable)

Two consequences, both enforced below:
    1. Always freeze the status bar, or the clock alone creates ~9% of noise.
    2. Never diff across a *reboot* -- the live widgets (Map, Calendar)
       re-render and swamp everything. Diff across a **respring**, which is
       bit-for-bit reproducible.
    3. Wait for SpringBoard to actually render before capturing. A screenshot
       taken too early is a black frame, and black-vs-black makes every A/B
       look like "no effect" -- this produced a false negative once already.

Rolling "today" widgets (Calendar with a date, Map tiles) can still move
between two resprings *if the minute rolls over*. The tool re-checks and warns.

================================================================================
LIMITS OF A PIXEL DIFF, HONESTLY
================================================================================
"Screen did not change" != "key does nothing". A fresh simulator renders app
icons as grey placeholders, so any key whose effect is *icon appearance* cannot
be observed there at all; a key may also only affect an app you never opened.
A pixel diff is a cheap smoke test, and the strongest *positive* signal
available for free. For keys where a negative result matters, either install
real apps on the sim or verify on hardware.

Usage
    python tools/sim_tweak_verify.py --list
    python tools/sim_tweak_verify.py --calibrate
    python tools/sim_tweak_verify.py --tweaks SBDisableDockSpecular SBExcludeDockShadow
    python tools/sim_tweak_verify.py --key com.apple.UIKit/UIViewGlassTintAmount=0.0
    python tools/sim_tweak_verify.py --control dark

Requires Pillow (for screenshot comparison).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------- sim helpers

STATUS_BAR = [
    "--time", "9:41", "--dataNetwork", "wifi", "--wifiMode", "active",
    "--wifiBars", "3", "--cellularMode", "active", "--cellularBars", "4",
    "--batteryState", "charged", "--batteryLevel", "100",
]

# Region to compare: drop the status bar (top 6%) and the home indicator.
CROP_TOP, CROP_BOTTOM = 0.06, 0.94

# Frames must differ by at least this share of pixels to count as a signal.
# The measured respring floor is 0.000%, so anything above a fraction of a
# percent is real; 0.5% leaves room for antialiasing on a rolling widget.
SIGNAL_THRESHOLD_PCT = 0.5


def simctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["xcrun", "simctl", *args], capture_output=True, text=True)


def booted_udids() -> list[str]:
    out = simctl("list", "devices", "booted").stdout
    return re.findall(r"\(([0-9A-F-]{36})\)\s*\(Booted\)", out)


def pick_udid(explicit: str | None) -> str:
    if explicit:
        return explicit
    live = booted_udids()
    if live:
        return live[0]
    out = simctl("list", "devices", "available").stdout
    # simctl prints the name OUTSIDE the parentheses:
    #     iPhone 18 Pro Max (2990A9E7-...) (Shutdown)
    # An earlier pattern expected "(iPhone ...)" and therefore never matched,
    # which made this whole fallback dead code: with no booted device the
    # tool exited with "no usable simulator found" instead of booting one.
    candidates = []
    for line in out.splitlines():
        m = re.search(r"iPhone[^)]*\(([0-9A-F-]{36})\)\s*\(Shutdown\)", line)
        if m:
            candidates.append(m.group(1))
    if not candidates:
        raise SystemExit("no usable simulator found")
    if len(candidates) == 1:
        return candidates[0]
    # Several iPhones installed. Measurements (luminance bands, fingerprints)
    # only reproduce on the same screen, so pick the device with the most
    # on-disk state -- the one that has actually been used. CoreSimulator
    # exposes nothing better: neither device.plist nor `simctl list -j` carry
    # lastBootedAt (both verified None). Not perfect, but the working device
    # sits at ~3 GB vs 17 MB for a freshly created one, and `--udid` is always
    # there for an explicit override.
    def data_kb(udid: str) -> int:
        data = Path.home() / "Library/Developer/CoreSimulator/Devices" / udid / "data"
        r = subprocess.run(["du", "-sk", str(data)], capture_output=True, text=True)
        try:
            return int(r.stdout.split()[0])
        except (IndexError, ValueError):
            return 0
    candidates.sort(key=data_kb, reverse=True)
    return candidates[0]


# Light/dark is stored as an integer in its own domain -- NOT
# NSGlobalDomain/AppleInterfaceStyle, which is the macOS mechanism and does
# nothing here (measured 0.000% change).
APPEARANCE_DOMAIN = "com.apple.uikitservices.userInterfaceStyleMode"
APPEARANCE_KEY = "UserInterfaceStyleMode"
APPEARANCE_VALUE = {"Light": 1, "Dark": 2}
APPEARANCE_NAME = {v: k for k, v in APPEARANCE_VALUE.items()}


def current_appearance(udid: str) -> str:
    raw = pref_read(udid, APPEARANCE_DOMAIN, APPEARANCE_KEY)
    try:
        return APPEARANCE_NAME.get(int(raw), f"<{raw}>")
    except (TypeError, ValueError):
        return f"<{raw}>"


def pin_appearance(udid: str, mode: str) -> None:
    """Force light/dark before every capture.

    Without this a run can straddle an appearance change (an earlier run left
    the device in light mode) and every sample reads identical -- the glass
    simply renders differently in light mode, so the comparison is meaningless.
    """
    pref_write(udid, APPEARANCE_DOMAIN, APPEARANCE_KEY, APPEARANCE_VALUE[mode])


def freeze_status_bar(udid: str) -> None:
    simctl("status_bar", udid, "override", *STATUS_BAR)


def shoot(udid: str, dest: Path) -> bool:
    simctl("io", udid, "screenshot", str(dest))
    return dest.exists() and dest.stat().st_size > 0


def _nonblack_ratio(path: Path) -> float:
    from PIL import Image

    im = Image.open(path).convert("L")
    w, h = im.size
    px = im.load()
    hit = sum(1 for y in range(0, h, 8) for x in range(0, w, 8) if px[x, y] > 20)
    tot = (h // 8 + 1) * (w // 8 + 1)
    return hit / tot


def wait_ready(udid: str, probe: Path, timeout: float = 240.0,
               min_ratio: float = 0.05, stable_frames: int = 3,
               require_loaded: bool = True) -> float:
    """Wait until the screen has settled *and* its assets have arrived.

    Three traps this closes, all of which produced a wrong conclusion here:

    * SpringBoard returns as a black screen with a spinner and needs ~50 s.
    * An app relaunched via ``simctl launch`` shows its black launch screen
      for several seconds. A fixed ``sleep`` is neither enough nor
      deterministic; the ratio floor keeps us from "settling" on it.
    * **SpringBoard paints the home screen before its assets are ready.**
      Early frames show the wallpaper as plain black and every app icon as a
      grey rounded square. That state is *stable*, so a plain 2-frame settle
      check accepts it -- and then a whole A/B runs half-loaded vs half-loaded,
      reading as a flawless 0.000% that looks like proof the key does nothing.

    Requires the frozen status bar, otherwise a one-pixel clock change means
    two consecutive frames are never equal.
    """
    t0 = time.time()
    prev: bytes | None = None
    streak = 0
    ratio = 0.0
    while time.time() - t0 < timeout:
        if shoot(udid, probe):
            blob = probe.read_bytes()
            ratio = _nonblack_ratio(probe)
            if ratio >= min_ratio:
                streak = streak + 1 if blob == prev else 1
                prev = blob
                if streak >= stable_frames and (
                        not require_loaded or _home_assets_loaded(probe)):
                    return time.time() - t0
        else:
            streak = 0
        time.sleep(2)
    raise SystemExit(
        f"screen never settled (last non-black ratio {ratio:.3f}, "
        f"streak {streak}/{stable_frames}, timeout {timeout:.0f}s)")


# Above this mean saturation the app-icon grid is showing real, colourful icons
# rather than the grey "asset not loaded yet" placeholders.
# Measured: placeholders 0.0, loaded home screen 66.0.
LOADED_SATURATION = 20.0


def _home_assets_loaded(path: Path) -> bool:
    """Cheap proxy for 'SpringBoard finished loading wallpaper and icons'.

    Samples the icon-grid band and measures hue/saturation: the placeholder
    squares are neutral grey (saturation 0), real icons are not. A unique-colour
    count does *not* work here -- antialiasing gives the grey placeholders
    50 000+ distinct colours.
    """
    from PIL import Image

    im = Image.open(path).convert("RGB")
    w, h = im.size
    band = im.crop((int(w * 0.05), int(h * 0.33), int(w * 0.95),
                    int(h * 0.50))).convert("HSV")
    px = band.load()
    vals = [px[x, y][1] for y in range(0, band.height, 3)
            for x in range(0, band.width, 3)]
    if not vals:
        return True
    return (sum(vals) / len(vals)) >= LOADED_SATURATION


# Set from --appearance in main(); applied before every capture so light/dark
# cannot drift mid-run.
_APPEARANCE: str | None = None


def respring(udid: str, probe: Path, relaunch: str | None = None) -> float:
    """Respring (not reboot -- a reboot re-runs asset loading and costs ~36%
    of noise) and wait for a fully painted, fully loaded screen."""
    if _APPEARANCE:
        pin_appearance(udid, _APPEARANCE)
    freeze_status_bar(udid)
    simctl("spawn", udid, "launchctl", "kickstart", "-k", "system/com.apple.SpringBoard")
    dt = wait_ready(udid, probe, require_loaded=relaunch is None)
    if relaunch:
        # App-level prefs (UIKit, Settings ...) are read at launch, so the
        # consumer has to be restarted too, not just SpringBoard -- and then
        # waited for, because its launch screen is black.
        simctl("terminate", udid, relaunch)
        simctl("launch", udid, relaunch)
        time.sleep(4)
        wait_ready(udid, probe, require_loaded=False)
    freeze_status_bar(udid)
    time.sleep(2)
    return dt


def capture(udid: str, dest: Path, probe: Path, relaunch: str | None = None) -> float:
    dt = respring(udid, probe, relaunch)
    shoot(udid, dest)
    return dt


# --------------------------------------------------------------- prefs access

DOMAIN_FOR_BASENAME = {
    ".GlobalPreferences": "NSGlobalDomain",
    "Global": None,          # FeatureFlags: not a preferred-domain store
    "disabled": None,        # launchd
    "SharedDeviceConfiguration": None,
}


def domain_for_path(path: str | None) -> str | None:
    """Map a device-side plist path to the `defaults` domain to use in the sim.

    Path-derived rather than a hand table, so a new FileLocation works without
    touching this file.
    """
    if not path:
        return None
    name = os.path.basename(path)
    if not name.endswith(".plist"):
        return None
    stem = name[:-len(".plist")]
    if stem in DOMAIN_FOR_BASENAME:
        return DOMAIN_FOR_BASENAME[stem]
    if stem.startswith("com.apple."):
        return stem
    return None


def pref_read(udid: str, domain: str, key: str):
    r = simctl("spawn", udid, "defaults", "read", domain, key)
    return r.stdout.strip() if r.returncode == 0 else None


def pref_write(udid: str, domain: str, key: str, value) -> None:
    """Go through cfprefsd; never edit the plist behind its back."""
    if isinstance(value, bool):
        args = ["-bool", "true" if value else "false"]
    elif isinstance(value, int):
        args = ["-int", str(value)]
    elif isinstance(value, float):
        args = ["-float", repr(value)]
    elif isinstance(value, str):
        args = ["-string", value]
    else:
        raise TypeError(f"unsupported value {value!r} ({type(value).__name__})")
    r = simctl("spawn", udid, "defaults", "write", domain, key, *args)
    if r.returncode != 0:
        raise SystemExit(f"defaults write failed: {r.stderr.strip()}")


def pref_delete(udid: str, domain: str, key: str) -> None:
    simctl("spawn", udid, "defaults", "delete", domain, key)


# ------------------------------------------------------- registry translation

def load_specs():
    """Import the registry under a minimal Qt stub (PySide6 is not installed)."""
    import types

    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.QT_TRANSLATE_NOOP = lambda ctx, text: text
    pyside = types.ModuleType("PySide6")
    pyside.QtCore = qtcore
    sys.modules.setdefault("PySide6", pyside)
    sys.modules.setdefault("PySide6.QtCore", qtcore)

    from src.tweaks.registry import SPECS

    return SPECS


def build_tweak(spec, value_override=None):
    """Instantiate a spec exactly like tweak_loader._build_spec does.

    Going through the real object matters: a CompanionKeyTweak carries extra
    keys beyond spec.key, which a naive `write(spec.key, spec.value)` would
    silently drop.
    """
    from src.tweaks.tweak_classes import BasicPlistTweak

    if spec.factory is not None:
        tweak = spec.factory()
    else:
        tweak = BasicPlistTweak(spec.location, spec.key, value=spec.value)
    if value_override is not None and hasattr(tweak, "value"):
        tweak.value = value_override
    tweak.set_enabled(True)
    return tweak


def payload_for(spec, value_override=None) -> list[tuple[str, str, object]]:
    """(domain, key, value) triples the tweak would write, sim-translated."""
    tweak = build_tweak(spec, value_override)
    out: list[tuple[str, str, object]] = []
    for location, body in tweak.apply_tweak({}).items():
        domain = domain_for_path(getattr(location, "value", None))
        if domain is None:
            print(f"    ! {location.name} 无模拟器映射，跳过")
            continue
        if isinstance(body, dict):
            for k, v in body.items():
                out.append((domain, k, v))
        else:
            out.append((domain, tweak.key, body))
    return out


def specs_matching(words: list[str]):
    specs = load_specs()
    chosen = []
    for w in words:
        wl = w.lower()
        hit = None
        for s in specs:
            if s.key and (s.key.lower() == wl or s.key.lower().endswith(wl)):
                hit = s
                break
        if hit is None:
            for s in specs:
                if wl in s.id.name.lower():
                    hit = s
                    break
        if hit is None:
            print(f"!! 找不到 {w!r}")
        else:
            chosen.append(hit)
    return chosen


# ------------------------------------------------------------------ reporting

def band_report(a_path: Path, b_path: Path, label: str) -> float:
    from PIL import Image, ImageChops

    A = Image.open(a_path).convert("RGB")
    B = Image.open(b_path).convert("RGB")

    # Guard against the nastiest failure mode: comparing a *blank* frame
    # (launch screen / SpringBoard still starting) against a rendered one. That
    # shows up as a huge, entirely bogus change -- measured once at 67.8%,
    # which was nothing but "black vs Settings".
    #
    # Note it cuts both ways: an all-white frame is just as invalid as an
    # all-black one, and near-black-only checks let a white launch screen
    # through, producing three "identical" readings of a screen that is not the
    # one being tested.
    for name, im in (("before", A), ("after", B)):
        g = im.convert("L")
        w, h = g.size
        px = g.load()
        vals = [px[x, y] for y in range(0, h, 8) for x in range(0, w, 8)]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        # A rendered page always has structure (text, cards, icons) -> large
        # variance. A blank launch screen -- black *or* white -- has almost
        # none. Mean is only a loose sanity bound; variance is the real test.
        if var < 100 or mean < 8 or mean > 250:
            print(f"\n!! {label}: {name} 截图不是可用画面"
                  f"（平均亮度 {mean:.0f}，方差 {var:.0f}）")
            print("   说明采集时进程还没渲染完 / 截到了空白页，本次对比无效 ——"
                  " 不要据此下任何结论。")
            return -1.0

    w, h = A.size
    y0, y1 = int(h * CROP_TOP), int(h * CROP_BOTTOM)
    a, b = A.crop((0, y0, w, y1)), B.crop((0, y0, w, y1))

    d = ImageChops.difference(a, b).convert("L")
    hh = d.histogram()
    tot = sum(hh)
    pct = sum(hh[8:]) / tot * 100
    print(f"\n{label}")
    print(f"  全屏变化(>8): {pct:.3f}%")
    # getbbox() is threshold-free: one pixel differing by 1/255 extends the
    # box, and respring jitter produces exactly that along every glass edge.
    # Measured 2026-09-13: the raw bbox covered the whole icon row
    # (x[128,1205] y[935,1334]) while the >8 count was 0.02%, all of it
    # antialiasing on icon edges. Threshold before boxing so the reported
    # region means "pixels that actually changed", and say so in the label.
    bbox = d.point(lambda v: 255 if v >= 8 else 0).getbbox()
    if bbox:
        print(f"  变化区域(仅>8像素): x[{bbox[0]},{bbox[2]}] y[{bbox[1] + y0},{bbox[3] + y0}]"
              f"  (占屏 {bbox[2]-bbox[0]}x{bbox[3]-bbox[1]})")

    rows = 10
    print("  分带：")
    for r in range(rows):
        by0, by1 = r * (y1 - y0) // rows, (r + 1) * (y1 - y0) // rows
        bd = ImageChops.difference(a.crop((0, by0, w, by1)), b.crop((0, by0, w, by1))).convert("L")
        bh = bd.histogram()
        bpct = sum(bh[8:]) / sum(bh) * 100
        bar = "█" * min(40, int(bpct))
        print(f"    y {(y0+by0)/h*100:5.1f}%–{(y0+by1)/h*100:5.1f}%  {bpct:6.2f}%  {bar}")
    return pct


# ------------------------------------------------------------------ commands

def cmd_list() -> int:
    specs = load_specs()
    rows = [s for s in specs if s.key]
    print(f"{len(specs)} specs, {len(rows)} with a plist key\n")
    print(f"{'TweakID':36s} {'FileLocation':18s} {'sim domain':24s} key")
    print("-" * 118)
    for s in rows:
        loc = s.location.name if s.location else "-"
        dom = domain_for_path(getattr(s.location, "value", None)) if s.location else None
        print(f"{s.id.name:36s} {loc:18s} {dom or '— (no sim mapping)':24s} {s.key}")
    return 0


def cmd_calibrate(udid: str, tmp: Path) -> int:
    """Measure the respring noise floor on this machine, right now."""
    print("校准 respring 噪声底（不做任何偏好改动）...")
    probe = tmp / "_probe.png"
    a, b = tmp / "cal_a.png", tmp / "cal_b.png"
    dt = capture(udid, a, probe)
    print(f"  第一帧完成（respring 到渲染 {dt:.0f}s）")
    dt = capture(udid, b, probe)
    print(f"  第二帧完成（respring 到渲染 {dt:.0f}s）")
    pct = band_report(a, b, "噪声底（两次纯 respring）")
    print()
    if pct < SIGNAL_THRESHOLD_PCT:
        print(f"✓ 噪声底 {pct:.3f}% < 判据阈值 {SIGNAL_THRESHOLD_PCT}% —— 方法可用。")
        return 0
    print(f"✗ 噪声底 {pct:.3f}% 过高，结果不可信。可能有动画/小组件在滚动，重跑一次。")
    return 1


# Positive control: a preference the simulator definitely honours, with a
# screen-wide visible effect. `AppleInterfaceStyle` in NSGlobalDomain is the
# macOS mechanism and does nothing here (measured: 0.000% change) -- iOS 26/27
# keeps the appearance in its own domain with an integer mode:
#     1 = Light, 2 = Dark   (measured 88.54% of the screen, luminance 145 -> 59)
# Found by reversing the problem: flip the setting through `simctl ui
# appearance`, then diff every plist in the device's preference store to learn
# the real key name. That trick generalises -- see docs/LiquidGlass_Keys.md.
CONTROL_DOMAIN = "com.apple.uikitservices.userInterfaceStyleMode"
CONTROL_KEY = "UserInterfaceStyleMode"
CONTROL_VALUE = {"Light": 1, "Dark": 2}


def cmd_control(udid: str, which: str, tmp: Path) -> int:
    """Positive control: prove write -> read -> render works at all.

    Run this first. If it fails, every 'no effect' result elsewhere is
    meaningless -- you would be blaming the keys for a broken pipeline.
    """
    domain, key, value = CONTROL_DOMAIN, CONTROL_KEY, CONTROL_VALUE[which]
    probe = tmp / "_probe.png"
    before, after = tmp / "control_before.png", tmp / "control_after.png"

    # Force the baseline to the *opposite* mode first. Capturing "whatever it
    # currently is" silently produces 0.000% whenever the device already sits
    # in the target mode -- which reads exactly like a broken pipeline. That
    # false alarm cost an hour here; never compare a value against itself.
    other = CONTROL_VALUE["Light" if which == "Dark" else "Dark"]
    other_name = "Light" if which == "Dark" else "Dark"
    original = pref_read(udid, domain, key)
    print(f"[control] 当前 {domain}/{key} = {original!r}"
          f"（{current_appearance(udid)}）；基线强制设为 {other_name}")
    pref_write(udid, domain, key, other)
    capture(udid, before, probe)
    pref_write(udid, domain, key, value)
    print(f"[control] 写入 {domain}/{key} = {value!r}（{which}）")
    capture(udid, after, probe)

    pct = band_report(before, after, f"阳性对照 {which}")
    if pct < 0:
        print("\n✗ 本次采集无效（截图未渲染）。重跑；连续出现说明 --foreground/渲染等待需要调。")
        return 1
    ok = pct > SIGNAL_THRESHOLD_PCT
    print()
    print("✓ 管线通：偏好写入确实被系统读取并影响渲染。" if ok else
          "✗ 管线有问题：连系统明暗都推不动，先修这个，别信其它结论。")
    if original is not None:
        pref_write(udid, domain, key, int(original))
        print(f"[control] 已还原 {key} = {original}")
    return 0 if ok else 1


def cmd_verify(udid: str, words: list[str], value_override, tmp: Path,
               keep: bool, relaunch: str | None = None) -> int:
    specs = specs_matching(words)
    if not specs:
        return 2

    probe = tmp / "_probe.png"
    before, after = tmp / "verify_before.png", tmp / "verify_after.png"

    print(f"模拟器 {udid}\n待验 {len(specs)} 条\n")

    print("--- 写入前 ---")
    planned: list[tuple[str, str, object]] = []
    for s in specs:
        triples = payload_for(s, value_override)
        if not triples:
            print(f"  {s.id.name}: 无可用目标域，跳过")
            continue
        planned.extend(triples)
        for d, k, v in triples:
            print(f"  {s.id.name}: {d}/{k}  (现值 {pref_read(udid, d, k)!r})")

    if not planned:
        return 2

    # Baseline must be a *clean* state. If a key is already present, writing it
    # again produces an identical screen and the A/B silently reports "no
    # effect" -- a false negative caused purely by leftover state.
    print("\n--- 清除基线状态 ---")
    for d, k, _ in planned:
        existed = pref_read(udid, d, k) is not None
        pref_delete(udid, d, k)
        print(f"  {d}/{k} {'已清除' if existed else '本就缺失'}")

    print("\n采集基线（respring + 等待渲染）...")
    dt = capture(udid, before, probe, relaunch)
    print(f"  基线完成 {dt:.0f}s -> {before}")

    print("\n--- 写入 ---")
    for d, k, v in planned:
        pref_write(udid, d, k, v)
        print(f"  {d}/{k} = {v!r}")

    print("\n重启 SpringBoard 并采集...")
    dt = capture(udid, after, probe, relaunch)
    print(f"  后帧完成 {dt:.0f}s -> {after}")

    pct = band_report(before, after, "A/B 结果")
    print()
    if pct < 0:
        print("✗ 本次采集无效（截图未渲染完），结果不可用。重跑。")
    elif pct > SIGNAL_THRESHOLD_PCT:
        print("★ 画面有变化 —— 至少有一个 key 被系统读取了（回看分带定位是哪个区域）。")
    else:
        print("· 画面无变化。这**不等于** key 无效：")
        print("  - 全新模拟器的 app 图标是灰占位符，任何「改图标外观」的 key 在此不可见；")
        print("  - 效果可能只出现在你没打开过的界面/进程里；")
        print("  - 部分 key 只在 Managed Preferences 覆盖层下被读（模拟器没有该层）。")
        print("  要下结论，需装真实 app 或在真机验证。")

    if not keep:
        print("\n--- 回滚 ---")
        for d, k, _ in planned:
            pref_delete(udid, d, k)
            print(f"  已删 {d}/{k}")
    else:
        print("\n(--keep: 保留已写入的值)")
    return 0


def _parse_pair(item: str) -> tuple[str, str, object] | None:
    if "=" not in item or "/" not in item.split("=", 1)[0]:
        print(f"!! 格式应为 DOMAIN/KEY=VALUE，收到 {item!r}")
        return None
    lhs, rhs = item.split("=", 1)
    domain, key = lhs.split("/", 1)
    low = rhs.lower()
    if low in ("true", "false"):
        value: object = low == "true"
    else:
        try:
            # Keep it a Float when it was written as one. `-int 0` happens to
            # read back as 0.0 through floatValue, but the plist then holds the
            # wrong type and other consumers (isKindOfClass checks, Swift Float
            # bridging) can behave differently.
            value = float(rhs) if any(c in rhs for c in ".eE") else int(rhs)
        except ValueError:
            value = rhs
    return domain, key, value


def cmd_raw(udid: str, pairs: list[str], tmp: Path, keep: bool,
            relaunch: str | None = None, clear: list[str] | None = None) -> int:
    """Test a raw DOMAIN/KEY=VALUE hypothesis, bypassing the registry.

    ``clear`` holds DOMAIN/KEY entries that must be *absent* for the whole run.
    That is not cosmetic: UIViewGlassTintAmount non-nil short-circuits the
    legibility branch entirely (see the sync routine at 0x33ca8 in
    DisplayAndBrightnessSettings), so a legibility test run while the amount
    key is still set measures the amount instead and looks like "legibility
    does nothing".
    """
    planned: list[tuple[str, str, object]] = []
    for item in pairs:
        parsed = _parse_pair(item)
        if parsed:
            planned.append(parsed)
    if not planned:
        return 2

    blocked: list[tuple[str, str]] = []
    for item in (clear or []):
        if "/" not in item:
            print(f"!! --clear 格式应为 DOMAIN/KEY，收到 {item!r}")
            continue
        d, k = item.split("/", 1)
        blocked.append((d, k))

    probe = tmp / "_probe.png"
    before, after = tmp / "raw_before.png", tmp / "raw_after.png"

    print("--- 清除基线状态 ---")
    for d, k in blocked:
        existed = pref_read(udid, d, k) is not None
        pref_delete(udid, d, k)
        print(f"  [屏蔽] {d}/{k} {'已清除' if existed else '本就缺失'}")
    for d, k, _ in planned:
        existed = pref_read(udid, d, k) is not None
        pref_delete(udid, d, k)
        print(f"  {d}/{k} {'已清除' if existed else '本就缺失'}")

    print("\n采集基线...")
    dt = capture(udid, before, probe, relaunch)
    print(f"  基线完成 {dt:.0f}s")

    print("\n--- 写入 ---")
    for d, k, v in planned:
        pref_write(udid, d, k, v)
        print(f"  {d}/{k} = {v!r}")

    print("\n重启并采集...")
    dt = capture(udid, after, probe, relaunch)
    print(f"  后帧完成 {dt:.0f}s")

    pct = band_report(before, after, "A/B 结果")
    print()
    if pct < 0:
        print("✗ 采集无效（截图未渲染完），重跑。")
    elif pct > SIGNAL_THRESHOLD_PCT:
        print("★ 画面有变化 —— 该域下这些 key 有效。")
    else:
        print("· 画面无变化。")

    if not keep:
        print("\n--- 回滚 ---")
        for d, k, _ in planned:
            pref_delete(udid, d, k)
        for d, k in blocked:
            pref_delete(udid, d, k)
            print(f"  [屏蔽] {d}/{k} 保持清除")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--udid")
    ap.add_argument("--list", action="store_true", help="列出 registry 全部 spec 及其模拟器域")
    ap.add_argument("--calibrate", action="store_true", help="测量 respring 噪声底")
    ap.add_argument("--tweaks", nargs="+", help="TweakID 名 或 plist key")
    ap.add_argument("--value", help="覆盖写入值（number/true/false/字符串）")
    ap.add_argument("--foreground", metavar="BUNDLE_ID",
                    help="截图前把该 app 拉到前台并重启它（应用级偏好用，如 com.apple.Preferences）")
    ap.add_argument("--control", choices=["Dark", "Light"],
                    help="阳性对照：验证 写入->读取->渲染 管线")
    ap.add_argument("--appearance", choices=["Dark", "Light"],
                    help="把浅/深色钉死后再采集。不钉的话设备可能停在上一轮"
                         "遗留的模式里，glass 在浅色下渲染不同，前后帧会"
                         "读数相同 —— 2026-09-12 就栽过一次")
    ap.add_argument("--keep", action="store_true", help="不自动回滚")
    ap.add_argument("--key", action="append", metavar="DOMAIN/KEY=VALUE",
                    help="直接指定偏好（可重复）。用于测假说，例如 "
                         "--key com.apple.springboard/SBDisableDockSpecular=true "
                         "（registry 把这条写到 NSGlobalDomain，这里换域试）")
    ap.add_argument("--clear", action="append", metavar="DOMAIN/KEY",
                    help="整轮保持缺失的偏好（可重复）。测 legibility 时必须屏蔽 "
                         "com.apple.UIKit/UIViewGlassTintAmount —— 它非 nil 会直接"
                         "短路 legibility 分支")
    args = ap.parse_args()

    if args.list:
        return cmd_list()

    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("需要 Pillow：/Users/jason/.workbuddy/binaries/python/envs/default/bin/pip install Pillow")
        return 3

    value = args.value
    if value is not None:
        low = value.lower()
        if low in ("true", "false"):
            value = low == "true"
        else:
            try:
                value = float(value)
                value = int(value) if value.is_integer() else value
            except ValueError:
                pass

    udid = pick_udid(args.udid)
    tmp = Path("/tmp/nugget_sim")
    tmp.mkdir(parents=True, exist_ok=True)

    global _APPEARANCE
    _APPEARANCE = args.appearance

    if udid not in booted_udids():
        print(f"启动 {udid} ...")
        simctl("boot", udid)
        simctl("bootstatus", udid, "-b")

    if args.control:
        # The control *is* an appearance change, so it must not be pinned.
        _APPEARANCE = None
        return cmd_control(udid, args.control, tmp)
    if _APPEARANCE:
        print(f"外观钉定为 {_APPEARANCE}（当前 {current_appearance(udid)}）")
    if args.calibrate:
        return cmd_calibrate(udid, tmp)
    if args.tweaks:
        return cmd_verify(udid, args.tweaks, value, tmp, args.keep, args.foreground)
    if args.key:
        return cmd_raw(udid, args.key, tmp, args.keep, args.foreground, args.clear)

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
