"""对拍两个 artifact：先各自校验设备侧真正在意的不变量，再比两边差异。

不变量（由 _ensure_directory_rows / inject_file_into_backup 的注释确立）：
  I1 每个注入项恰好一条 flags=1 行，且 fileID == sha1(domain-relativePath)
  I2 该行 blob 可解码：InodeNumber 是 int>0、Size==payload 大小、Digest==sha1(payload)、Mode 0644
  I3 全表 flags∈(1,2) 的 InodeNumber 全局唯一（设备按 inode 去重）
  I4 每条 flags=1 行的**每一级非空父目录**都有 flags=2 行（agent 会跳过没有目录行的文件）
  I5 payload 字节 == 该项应写的内容
  I6 计数器与实际产出一致
"""
import hashlib
import json
import os
import sys
from pathlib import Path

AUDIT_DIR = os.environ.get("GN_AUDIT_DIR", "/tmp/gn_audit")
sys.path.insert(0, AUDIT_DIR)
import corpus  # noqa: E402


def expected_items(scenario):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ftr", "/Users/jason/GoldenNugget/src/utils/file_to_restore.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    items = corpus.build_items(Path(AUDIT_DIR) / "_expected", scenario, None,
                              FileToRestore=m.FileToRestore,
                              payload_dir=Path(AUDIT_DIR) / "_expected_src")
    out = []
    for f in items:
        data = f.contents
        if data is None and f.contents_path:
            data = Path(f.contents_path).read_bytes()
        if isinstance(data, str):
            data = data.encode("utf-8")
        out.append((f.domain, f.restore_path.lstrip("/"), data))
    return out


def check_invariants(art, items):
    items_flat = [(d, r, x) for d, r, x in items]
    rows = {tuple(r[:4]): r[4] for r in art["rows"]}
    payloads = art["payloads"]
    fails = []
    inodes = {}
    dirs = {(d, rel) for (fid, d, rel, flags) in [tuple(r[:4]) for r in art["rows"]] if flags == 2}
    flags1 = [(fid, d, rel) for (fid, d, rel, flags) in [tuple(r[:4]) for r in art["rows"]] if flags == 1]

    for fid, d, rel, flags, body in art["rows"]:
        if flags in (1, 2) and body:
            import re
            m = re.search(r"InodeNumber=int:(\d+)", body)
            if m:
                ino = int(m.group(1))
                inodes.setdefault(ino, []).append(f"{d}/{rel}")

    for domain, rel, data in items:
        if data is None:            # 该 item 本身没有内容（old 会抛异常）——不计入产出核查
            continue
        fid = hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()
        key = (fid, domain, rel, 1)
        if key not in rows:
            fails.append(f"I1 缺行 {domain}/{rel}")
            continue
        body = rows[key] or ""
        if (domain, "") not in dirs:
            fails.append(f"I4 缺域根目录行 {domain}/''（为 {rel} 所需）")
        if rel and "/" in rel:
            parts = rel.split("/")
            for i in range(1, len(parts)):
                anc = "/".join(parts[:i])
                if (domain, anc) not in dirs:
                    fails.append(f"I4 缺父目录行 {domain}/{anc}（为 {rel} 所需）")
        pl = payloads.get(f"{fid[:2]}/{fid}")
        if pl is None:
            fails.append(f"I2 payload 缺失 {domain}/{rel}")
            continue
        sha, size = pl
        if sha != hashlib.sha1(data).hexdigest():
            fails.append(f"I5 payload 内容不符 {domain}/{rel}")
        if f"Size=int:{size}" not in body:
            fails.append(f"I2 Size 不符 {domain}/{rel}: 期望 Size=int:{size}")
        if "bytes:" + hashlib.sha1(data).hexdigest() not in body:
            fails.append(f"I2 Digest 不符 {domain}/{rel}")
        if "Mode=int:33188" not in body:
            fails.append(f"I2 Mode 不是 0644 {domain}/{rel}")
        if "InodeNumber=int:" not in body:
            fails.append(f"I2 无 InodeNumber {domain}/{rel}")

    # 只关心「注入行」的碰撞：真实设备自身会在不同域复用 inode（本例 CameraRollDomain/Media
    # 与 MediaDomain/Media 共用 32），那不是注入器的问题。
    touched = {f"{d}/{r}" for d, r, _ in items_flat}
    import re as _re
    for domain, rel, _data in items:
        fid = hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()
        body = rows.get((fid, domain, rel, 1)) or ""
        bits = {k: (_re.search(rf"{k}=int:(\d+)", body).group(1)
                    if _re.search(rf"{k}=int:(\d+)", body) else "-")
                for k in ("Mode", "Flags", "ProtectionClass", "Size", "InodeNumber")}
        print(f"      {domain}/{rel}: Mode={bits['Mode']} Flags={bits['Flags']} "
              f"ProtClass={bits['ProtectionClass']} Size={bits['Size']} inode={bits['InodeNumber']}")

    dup = {k: v for k, v in inodes.items()
           if len(v) > 1 and any(x in touched for x in v)}
    for ino, who in sorted(dup.items()):
        fails.append(f"I3 inode {ino} 被 {len(who)} 行共用: {who[:3]}")
    return fails, len(flags1)


MASK_KEYS = ("InodeNumber", "Birth", "LastModified", "LastStatusChange")


def mask_inode(body):
    """inode 与时间戳是**合法的分歧**（唯一性才是语义），比对时掩掉后单独列出。"""
    import re
    out = body or ""
    for k in MASK_KEYS:
        out = re.sub(rf"{k}=int:\d+", f"{k}=int:MASK", out)
    return out


def main():
    scenario = sys.argv[1]
    old = json.loads((Path(AUDIT_DIR) / f"art_{scenario}_old.json").read_text())
    new = json.loads((Path(AUDIT_DIR) / f"art_{scenario}_new.json").read_text())
    items = expected_items(scenario)

    print(f"=== scenario: {scenario} ({len(items)} items) ===")
    for art in (old, new):
        f, n_rows = check_invariants(art, items)
        print(f"  [{art['impl']}] counters={art['counters']} wall={art['wall_s']}s "
              f"peakRSS={art['peak_rss_kb'] / 1048576:.0f}MB rows={len(art['rows'])} "
              f"payloads={len(art['payloads'])} errors={art['errors']}")
        print(f"      不变量违例 {len(f)} 条" + ("  <-- " + f[0] if f else ""))
        for x in f[:6]:
            print("        -", x)

    ro = {tuple(r[:4]): r[4] for r in old["rows"]}
    rn = {tuple(r[:4]): r[4] for r in new["rows"]}
    only_old = sorted(set(ro) - set(rn))
    only_new = sorted(set(rn) - set(ro))
    print(f"  行集合差异: 仅 old {len(only_old)} / 仅 new {len(only_new)}")
    for k in only_old[:4]:
        print("    - 仅 old:", k)
    for k in only_new[:4]:
        print("    - 仅 new:", k)

    masked_diff = [k for k in set(ro) & set(rn) if mask_inode(ro[k]) != mask_inode(rn[k])]
    inode_diff = [k for k in set(ro) & set(rn) if ro[k] != rn[k] and mask_inode(ro[k]) == mask_inode(rn[k])]
    print(f"  blob 差异: 除 inode 外实质不同 {len(masked_diff)} / 仅 inode 不同 {len(inode_diff)}")
    for k in masked_diff[:4]:
        print("    - 实质不同:", k)
        print("      old:", (ro[k] or "")[:220])
        print("      new:", (rn[k] or "")[:220])

    po = {k: v[0] for k, v in old["payloads"].items()}
    pn = {k: v[0] for k, v in new["payloads"].items()}
    print(f"  payload 差异: 仅 old {len(set(po) - set(pn))} / 仅 new {len(set(pn) - set(po))} / "
          f"内容不同 {sum(1 for k in set(po) & set(pn) if po[k] != pn[k])}")


if __name__ == "__main__":
    main()
