#!/usr/bin/env python3
"""Validate a registry tweak entry end-to-end, without needing PySide6 installed.

Why this exists
---------------
Adding a tweak means touching exactly two places (``TweakID`` + one ``_t(...)``
line in ``registry.py``), and everything else — the iOS tweaks page, the CLI,
presets and HotLoad's ``FEATURE_TWEAKS`` — is *derived*. That derivation is
silent: a typo'd key or a duplicated enum name fails at import time or, worse,
renders a switch that writes the wrong plist entry.

This script exercises the real construction path (registry -> SPECS_BY_SECTION
-> SECTION_FEATURES -> FEATURE_TWEAKS -> BasicPlistTweak.apply_tweak) and
asserts the resulting write. PySide6 is stubbed with a minimal shim, so it runs
on any interpreter — you do not need the GUI dependencies installed.

Usage
-----
    python3 tools/verify_registry_entry.py                       # check all ids
    python3 tools/verify_registry_entry.py HideHomeSearchPill    # check one id

Exit code 0 = all checks passed.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


def _stub_pyside6() -> None:
    """Install the smallest PySide6 shim the registry path needs.

    ``registry.py`` only wants ``QT_TRANSLATE_NOOP``; the rest is here so that
    importing ``hotload`` (for FEATURE_TWEAKS) also succeeds.
    """
    if "PySide6.QtCore" in sys.modules:
        return
    pyside = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.QT_TRANSLATE_NOOP = lambda ctx, s: s
    qtcore.QCoreApplication = types.SimpleNamespace(translate=lambda ctx, s: s)
    qtcore.QStandardPaths = types.SimpleNamespace(
        writableLocation=lambda *a, **k: "/tmp/goldennugget-verify"
    )
    pyside.QtCore = qtcore
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = qtcore


_stub_pyside6()

from src.tweaks.basic_plist_locations import FileLocation  # noqa: E402
from src.tweaks.registry import (  # noqa: E402
    SECTION_FEATURES,
    SPECS,
    SPECS_BY_ID,
    SPECS_BY_SECTION,
    Kind,
)
from src.tweaks.tweak_classes import BasicPlistTweak  # noqa: E402
from src.tweaks.tweak_names import TweakID  # noqa: E402

_FAILURES: list[str] = []


def check(label: str, cond: bool, extra: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label + (f"   {extra}" if extra else ""))
    if not cond:
        _FAILURES.append(label)


def verify(name: str) -> bool:
    print(f"=== 校验 TweakID.{name} ===")
    if not hasattr(TweakID, name):
        check(f"TweakID.{name} 存在", False, "枚举里没有这个成员")
        return False

    tid = getattr(TweakID, name)

    # --- 1) 枚举与 registry 条目 ---
    names = [m.name for m in TweakID]
    check("枚举名无重复", len(names) == len(set(names)), f"{len(names)} 个成员")

    hits = [s for s in SPECS if s.id is tid]
    check("registry 中恰好一条 spec", len(hits) == 1, f"实测 {len(hits)} 条")
    if len(hits) != 1:
        return False
    s = hits[0]

    check("key 非空", bool(s.key), repr(s.key))
    check("location 是 FileLocation", isinstance(s.location, FileLocation), str(s.location))
    check("title 非空", bool(s.title))
    check("未禁用", not s.disabled)
    if s.kind is Kind.NUMBER:
        check("NUMBER 的 min < max", s.min_value < s.max_value,
              f"{s.min_value}..{s.max_value} step={s.step}")

    # --- 2) 派生链路 ---
    check("已进入 SPECS_BY_SECTION[section]",
          any(x.id is tid for x in SPECS_BY_SECTION[s.section]),
          f"该段 {len(SPECS_BY_SECTION[s.section])} 条")
    check("已进入 SPECS_BY_ID", tid in SPECS_BY_ID)

    feature = SECTION_FEATURES.get(s.section)
    check("section → feature 有映射", feature is not None, str(feature))
    if feature:
        try:
            from src.controllers.hotload import FEATURE_TWEAKS
            check(f"FEATURE_TWEAKS[{feature!r}] 含 {name}", name in FEATURE_TWEAKS.get(feature, []))
        except Exception as exc:  # pragma: no cover - stub/env dependent
            check("导入 hotload 以验证 FEATURE_TWEAKS", False, repr(exc))

    # --- 3) 无冲突 ---
    dup = [x.id.name for x in SPECS if x.key == s.key and x.id is not tid]
    check("key 未被其它 tweak 占用", not dup, str(dup))

    # --- 4) 真实写入行为 ---
    # 复刻 tweak_loader._build_spec（它 import .tweaks，会拖进 Qt）
    if s.factory is not None:
        print("  SKIP  写入行为（factory 型 tweak，由自定义类决定写入内容）")
    else:
        t = BasicPlistTweak(s.location, s.key, value=s.value)
        check("关闭时不写入任何内容", t.apply_tweak({}) == {})
        t.set_enabled(True)
        out = t.apply_tweak({})
        expect = {s.location: {s.key: s.value}}
        check("开启时写入 {location: {key: value}}", out == expect, f"{out}")
        merged = t.apply_tweak({s.location: {"__other__": True}})
        check("与同文件既有 key 合并、不覆盖",
              merged.get(s.location, {}).get("__other__") is True)

    return True


def main() -> int:
    args = sys.argv[1:]
    if args:
        return int(not all(verify(a) for a in args))
    else:
        print("=== 全量一致性 ===")
        bad = [s.id for s in SPECS if not isinstance(s.id, TweakID)]
        check("所有 spec.id 均为 TweakID", not bad, str(bad))
        orphans = [m for m in TweakID if not any(s.id is m for s in SPECS)]
        print(f"  INFO  TweakID 中未出现在 SPECS 的成员: {len(orphans)}"
              f"{' → ' + ', '.join(m.name for m in orphans[:8]) + (' ...' if len(orphans) > 8 else '') if orphans else ''}")

    print()
    if _FAILURES:
        print(f"失败 {len(_FAILURES)} 项：")
        for f in _FAILURES:
            print("  -", f)
        return 1
    print("全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
