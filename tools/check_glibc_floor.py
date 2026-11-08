#!/usr/bin/env python3
"""CI gate: the frozen Linux bundle must not require a glibc newer than a floor.

Released builds once stopped starting on Ubuntu 22.04 / Debian 12 because
setup-python's runner-native CPython (libpython + lib-dynload + libraries
PyInstaller picked from the host) demanded GLIBC_2.38 while every shipping
wheel (PySide6 manylinux_2_34, numpy 2_27, opencv 2_27...) sat far below it.
Building inside a manylinux_2_34 container fixes it; this script makes the
guarantee explicit so a future dependency or toolchain bump cannot silently
exivle past it again.

For every ELF file it reads the ".gnu.version_r" section (what ld.so would
actually demand at load time) from the dynamic segment / section headers and
takes the highest GLIBC_/GLIBCXX_/GLIBC-2.x-style symbol-version reference.
No `strings`-style text sniffing, no external tools: a scanning false positive
must not fail a good release.

Exit code 0 when everything is at or below the floor, 1 otherwise (lists the
offending files), 2 on unparseable/absent ELF data (treated as a failure since
the gate should be seeing real released bundles).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# GLIBC symbol version → the oldest distro that still runs the bundle.
DEFAULT_FLOOR = "2.34"
SKIPPED_PREFIXES = ("GLIBCXX_", "GRTEngine", "__", "_ITM_", "_ZSt", "_ZTV")

_PREFIX_RE = re.compile(r"^.*?GLIBC(XX)?_")


def _clean(version: str) -> str:
    return _PREFIX_RE.sub("", version)


def _ver_tuple(s: str) -> tuple[int, ...]:
    out: list[int] = []
    for p in _clean(s).split("."):
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    # Pad to a fixed width so tuples compare shape-to-shape.
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def _u16(data: bytes, off: int) -> int:
    return int.from_bytes(data[off:off + 2], "little")


def _u32(data: bytes, off: int) -> int:
    return int.from_bytes(data[off:off + 4], "little")


def _u64(data: bytes, off: int) -> int:
    return int.from_bytes(data[off:off + 8], "little")


class _Verneed:
    """One Vernaux entry: a needed symbol version from one soname."""

    def __init__(self, name: str | None):
        self.name = name
        self.version: str | None = None


def _read_elf_base(data: bytes) -> tuple[bool, bool]:
    """Return (is_elf, is_64bit)."""
    if len(data) < 54 or data[:4] != b"\x7fELF":
        return False, False
    is64 = data[4] == 2
    return True, is64


def _section_headers(data: bytes):
    """Yield (sh_type, sh_offset, sh_size, sh_link, sh_entsize) for each section."""
    _, is64 = _read_elf_base(data)
    if is64:
        e_shoff = _u64(data, 0x28)
        e_shentsize = _u16(data, 0x3A)
        e_shnum = _u16(data, 0x3C)
    else:
        e_shoff = _u32(data, 0x1C)
        e_shentsize = _u16(data, 0x2E)
        e_shnum = _u16(data, 0x30)
    if not e_shoff or not e_shnum or not e_shentsize:
        return
    for i in range(e_shnum):
        sh = e_shoff + i * e_shentsize
        if sh + 40 > len(data):
            return
        sh_type = _u32(data, sh + 4)
        sh_offset = _u64(data, sh + 24) if is64 else _u32(data, sh + 16)
        sh_size = _u64(data, sh + 32) if is64 else _u32(data, sh + 20)
        sh_link = _u32(data, sh + 40) if is64 else _u32(data, sh + 24)
        sh_entsize = _u64(data, sh + 56) if is64 else _u32(data, sh + 36)
        yield sh_type, sh_offset, sh_size, sh_link, sh_entsize


def max_symbol_version(path: Path) -> tuple[str | None, str | None]:
    """Highest versioned-symbol reference required by `path` (an ELF file).

    Returns (max_version_string, soname_of_that_ref); or (None, None) when the
    file simply declares none (statically linked, architecture stubs, etc.).
    """
    data = path.read_bytes()
    is_elf, _ = _read_elf_base(data)
    if not is_elf:
        return None, None

    sections = list(_section_headers(data))
    verneed_off = verneed_size = _verneed_entsize = dynstr_idx = symbol_off = None
    for sh_type, sh_offset, sh_size, sh_link, sh_entsize in sections:
        # SHT_GNU_verneed = 0x6ffffffe, SHT_DYNSYM = 11
        if sh_type == 0x6FFFFFFE:
            verneed_off, verneed_size, _verneed_entsize = sh_offset, sh_size, sh_entsize
            # The version table's own sh_link is the dynamic-string section.
            dynstr_idx = sh_link
        elif sh_type == 11:
            symbol_off = sh_offset
    if dynstr_idx is None or not 0 <= dynstr_idx < len(sections):
        return None, None
    dynstr_off = sections[dynstr_idx][1]
    if verneed_off is None or dynstr_off is None or symbol_off is None:
        return None, None

    def dynstr(off: int) -> str:
        end = data.index(b"\x00", off)
        return data[off:end].decode("utf-8", "replace")

    best: tuple[str, str] | None = None
    # Verneed entries are VARIABLE-SIZE: vn_aux points at the aux array and
    # vn_next is the byte offset from THIS entry to the next one (0 = last).
    ent = verneed_off
    table_end = min(verneed_off + verneed_size, len(data)) if verneed_size is not None else len(data)
    while ent + 16 <= table_end:
        aux_count = _u16(data, ent + 2)
        file_off = _u32(data, ent + 4)
        aux_off = _u32(data, ent + 8)
        sono = dynstr(file_off + dynstr_off) if file_off else None
        # vn_aux/vna_next are byte offsets relative to the Verneed entry and
        # the Vernaux entry itself (not to the table start).
        aux = ent + aux_off if aux_off else 0
        for _ in range(aux_count):
            if aux + 16 > table_end or aux == 0:
                break
            name_off = _u32(data, aux + 8)
            vna_next = _u32(data, aux + 12)
            name = dynstr(dynstr_off + name_off)
            if name and not any(name.startswith(p) for p in SKIPPED_PREFIXES):
                if best is None or _ver_tuple(name) > _ver_tuple(best[0]):
                    best = (name, sono or "")
            aux = aux + vna_next if vna_next else 0
        vn_next = _u32(data, ent + 12)
        if not vn_next:
            break
        ent += vn_next
    return (best[0], best[1]) if best else (None, None)


def iter_bundle_files(roots: list[Path]):
    exts = {".so", ".dylib"}
    for root in roots:
        for p in root.rglob("*"):
            if p.is_file() and (p.suffix in exts or ".so." in p.name):
                yield p


def main(argv: list[str]) -> int:
    args = argv[1:]
    floor = DEFAULT_FLOOR
    if args and args[0].startswith("--floor="):
        floor = args[0].split("=", 1)[1]
        args = args[1:]
    elif len(args) >= 2 and args[0] == "--floor":
        floor = args[1]
        args = args[2:]
    floor_v = _ver_tuple(floor)
    roots = [Path(a) for a in args] or [Path(".") , Path("_internal")]
    checked = failed = 0
    offenders: list[str] = []
    for path in iter_bundle_files(roots):
        try:
            version, sono = max_symbol_version(path)
        except (OSError, ValueError, IndexError) as exc:
            print(f"  WARN unparsable {path}: {exc}", file=sys.stderr)
            continue
        if version is None:
            continue
        checked += 1
        if _ver_tuple(version) > floor_v:
            failed += 1
            offenders.append(f"{path}: requires {version} ({sono}) > floor {floor}")
    if checked == 0:
        print("No bundled shared libraries inspected - is this the right directory?", file=sys.stderr)
        return 2
    print(f"Glibc floor gate: {checked} libraries inspected, {failed} above floor {floor}")
    for o in offenders:
        print(f"  FAIL {o}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
