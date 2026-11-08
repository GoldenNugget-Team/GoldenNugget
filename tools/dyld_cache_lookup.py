#!/usr/bin/env python3
"""Attribute strings in a dyld shared cache to the dylib that contains them.

A plain ``grep`` over a shared cache tells you a symbol *exists*; it does not
tell you *who references it*. On this project that distinction mattered: it is
the difference between "these SpringBoard glass keys exist somewhere on the
system" and "they are defined in SpringBoardFoundation.framework", which is the
statement that decides whether a tweak can possibly work.

The cache is one 2 GB blob. The header points at two tables we need:

    dyld_cache_header
        char   magic[16]
        uint32 mappingOffset      @0x10
        uint32 mappingCount       @0x14
        uint32 imagesOffsetOld    @0x18   (0 in the iOS 27 caches -- unusable)
        uint32 imagesCountOld     @0x1C
        ...
        uint64 imagesTextOffset   @0x88   <- the one that works
        uint64 imagesTextCount    @0x90

    dyld_cache_mapping_info         (32 bytes)  file offset -> vm address
        uint64 address; uint64 size; uint64 fileOffset; uint32 maxProt; uint32 initProt

    dyld_cache_image_text_info      (32 bytes)  vm address -> image path
        uint8 uuid[16]; uint64 loadAddress; uint32 textSegmentSize; uint32 pathOffset

So: file offset --[mappings]--> vm address --[imagesText]--> dylib path.

Usage
    # who owns a known file offset?
    python tools/dyld_cache_lookup.py <cache> --at 808933125

    # where do these symbols live?
    python tools/dyld_cache_lookup.py <cache> SBDisableDockSpecular SBUseFlatIconsEverywhere

Locating the simulator cache
    <RuntimeRoot>/System/Library/Caches/com.apple.dyld/dyld_sim_shared_cache_arm64
where RuntimeRoot is
    /Library/Developer/CoreSimulator/Volumes/<vol>/Library/Developer/CoreSimulator/
        Profiles/Runtimes/iOS 27.0.simruntime/Contents/Resources/RuntimeRoot

Note: the ``imagesText`` table only describes images mapped by *this* file
(1484 of them in the iOS 27 sim cache). Symbols that live in the sibling
``dyld_sim_shared_cache_arm64.01`` are still found -- the byte scan sees them --
but cannot be attributed, so they print as ``<?>``. Run the tool on each file
if you need a name for those. (Observed: UIKitCore is in the first file and
attributes fine; DisplayAndBrightnessSettings is not, and comes back ``<?>``.)

A plain byte scan is the right primitive here; ``imagesText`` is only used to
put a name on a hit, and a missing name never invalidates the hit itself.
"""
from __future__ import annotations

import argparse
import struct
from pathlib import Path

CHUNK = 64 * 1024 * 1024
OVERLAP = 256


def parse_header(path: Path):
    with open(path, "rb") as fh:
        head = fh.read(0x200)
        magic = head[:16].rstrip(b"\0").decode("ascii", "replace")
        mapping_off, mapping_cnt, _io, _ic = struct.unpack_from("<IIII", head, 0x10)
        text_off, text_cnt = struct.unpack_from("<QQ", head, 0x88)

        fh.seek(mapping_off)
        raw = fh.read(mapping_cnt * 32)
        mappings = []
        for i in range(mapping_cnt):
            addr, size, foff, _m, _ip = struct.unpack_from("<QQQII", raw, i * 32)
            mappings.append((addr, size, foff))

        fh.seek(text_off)
        raw = fh.read(text_cnt * 32)
        infos = []
        paths: dict[int, str] = {}
        for i in range(text_cnt):
            load_addr, text_size, poff = struct.unpack_from("<QII", raw, i * 32 + 16)
            infos.append((load_addr, text_size))
            fh.seek(poff)
            buf = bytearray()
            while True:
                c = fh.read(1)
                if not c or c == b"\0":
                    break
                buf += c
            paths[load_addr] = buf.decode("utf-8", "replace")

    infos.sort()
    return magic, mappings, infos, paths


def owner_of(mappings, infos, paths, file_offset: int) -> str | None:
    addr = None
    for m_addr, m_size, m_foff in mappings:
        if m_foff <= file_offset < m_foff + m_size:
            addr = m_addr + (file_offset - m_foff)
            break
    if addr is None:
        return None
    best = None
    for load_addr, text_size in infos:
        if load_addr <= addr < load_addr + text_size:
            best = load_addr
        elif load_addr > addr:
            break
    return paths.get(best)


def find(needles: list[str], mappings, infos, paths, cache: Path):
    hits: dict[str, list[tuple[int, str]]] = {n: [] for n in needles}
    longest = max(len(n) for n in needles)

    with open(cache, "rb") as fh:
        base = 0
        tail = b""
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            buf = tail + chunk
            start = base - len(tail)
            for n in needles:
                needle = n.encode()
                pos = 0
                while True:
                    i = buf.find(needle, pos)
                    if i < 0:
                        break
                    foff = start + i
                    if foff >= base:      # dedupe the overlap region
                        hits[n].append((foff, owner_of(mappings, infos, paths, foff) or "<?>"))
                    pos = i + 1
            tail = buf[-(longest - 1):]
            base += len(chunk)
    return hits


def string_pool(cache: Path, offset: int, span: int) -> list[tuple[int, str, bool]]:
    """Walk NUL-separated printable C strings around ``offset``.

    This is the mode that earns its keep. ``__cstring`` keeps related literals
    *adjacent*, so dumping the neighbourhood of one hit often hands you the
    whole table it belongs to. On this project that is how the UIKit glass
    preference keys fell out in one shot: searching ``UIViewGlassLegibilitySetting``
    in UIKitCore and widening the view produced

        UIViewGlassLegibilitySetting
        UIViewGlassLegibilityDidChangeNotification
        UIViewGlassTintAmount
        UIViewGlassBuddyTintAmount
        UIViewGlassEverEditedInBuddy
        UIViewGlassEverEditedInSettings
        UIViewGlassTintAmountDidChangeNotification
        UIViewGlassLegibilityUpdateNotification
        UIViewGlassTintAmountUpdateNotification

    -- i.e. the sibling keys and the change notifications, none of which appear
    in any public documentation.
    """
    lo = max(0, offset - span // 3)
    with open(cache, "rb") as fh:
        fh.seek(lo)
        blob = fh.read(span)
    out: list[tuple[int, str, bool]] = []
    i = 0
    while i < len(blob):
        j = blob.find(b"\0", i)
        if j < 0:
            break
        raw = blob[i:j]
        if len(raw) >= 3 and all(32 <= c < 127 for c in raw):
            s = raw.decode("ascii")
            # mark only the string the offset actually lands *inside* -- a naive
            # `offset <= lo + j` marks everything after the needle as well.
            out.append((lo + i, s, lo + i <= offset < lo + j))
        i = j + 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cache", type=Path)
    ap.add_argument("needles", nargs="*", help="要查找的字符串")
    ap.add_argument("--at", type=int, action="append", default=[],
                    help="已知文件偏移，直接反查所属 dylib（可重复）")
    ap.add_argument("--pool", nargs="?", type=int, const=700, default=0,
                    metavar="BYTES",
                    help="对每个命中点 dump 周围的 C 字符串池（默认 700 字节）。"
                         "用来把「找到一个 key」升级成「看到整张键表」")
    args = ap.parse_args()

    magic, mappings, infos, paths = parse_header(args.cache)
    print(f"cache : {args.cache.name}")
    print(f"magic : {magic}   mappings={len(mappings)}  images={len(infos)}\n")

    for off in args.at:
        print(f"  offset {off:>12,}  ->  {owner_of(mappings, infos, paths, off)}")

    if args.needles:
        hits = find(args.needles, mappings, infos, paths, args.cache)
        width = max(len(n) for n in args.needles)
        for n in args.needles:
            rows = hits[n]
            if not rows:
                print(f"  MISS  {n:<{width}}  （本分片内没有）")
                continue
            by_img: dict[str, list[int]] = {}
            for off, img in rows:
                by_img.setdefault(img, []).append(off)
            for img, offs in sorted(by_img.items(), key=lambda kv: -len(kv[1])):
                loc = ", ".join(f"@{o}" for o in offs[:4])
                print(f"  HIT   {n:<{width}}  x{len(offs):<3} {img}   {loc}")

        if args.pool:
            for n in args.needles:
                for off, img in hits[n]:
                    print(f"\n=== {n}  @{off}  字符串池 ±{args.pool} ===")
                    for addr, s, is_hit in string_pool(args.cache, off, args.pool):
                        mark = "  <<<<<" if is_hit else ""
                        print(f"   {addr:#012x}  {s}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
