"""Build a post-prune protective-backup fixture from the REAL iTunes backup.

真实数据来源：本机 iPad16,2 / iOS 27.0 的 MobileSync 备份 Manifest.db（34,914 行）。
剪枝谓词**机械抽取**自 src/restore/protective.py（不手抄、不重写），
确保 fixture 的状态 == Phase 1 注入循环真正看到的状态。
"""
import ast
import hashlib
import os
import plistlib
import shutil
import sqlite3
from pathlib import Path

REAL_DB = os.path.expanduser(
    "~/Library/Application Support/MobileSync/Backup/00008130-001431082E40001C/Manifest.db")
PROTECTIVE_PY = os.environ.get(
    "GN_PROTECTIVE_PY", "/Users/jason/GoldenNugget/src/restore/protective.py")

# 构成 protective backup 的域（HomeDomain 是剪枝行为最微妙的那个：
# 它的 '' 与 'Library' 目录行会被剪掉，而 Library/SpringBoard 等保留）
FIXTURE_DOMAINS = (
    "HomeDomain",
    "AppDomain-com.apple.PosterBoard",
    "SystemPreferencesDomain",
)

SCHEMA = [
    "CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, "
    "flags INTEGER, file BLOB)",
    "CREATE INDEX FilesRelativePathIdx ON Files(relativePath)",
    "CREATE INDEX FilesFlagsIdx ON Files(flags)",
    "CREATE TABLE Properties (key TEXT PRIMARY KEY, value BLOB)",
    "CREATE INDEX FilesDomainsRelativePathIdx ON Files(domain, relativePath)",
]


def load_predicates():
    """从 protective.py 机械抽取剪枝谓词（AST 切片，不复制粘贴）。"""
    src = Path(PROTECTIVE_PY).read_text()
    tree = ast.parse(src)
    want_fn = {"_is_protective_file", "_keep_protective_entry", "_media_tree_scope"}

    def is_plain_assign(n):
        return (isinstance(n, ast.Assign)
                and all(isinstance(t, ast.Name) for t in n.targets))

    nodes = [n for n in tree.body
             if is_plain_assign(n)
             or (isinstance(n, ast.FunctionDef) and n.name in want_fn)]
    chunk = "\n\n".join(ast.get_source_segment(src, n) for n in nodes)
    ns = {}
    exec(compile(chunk, "<extracted:protective.py>", "exec"), ns)
    return ns["_is_protective_file"], ns["_keep_protective_entry"]


def build(dst: Path, *, drop_payload_rows: int = 3, domains=None) -> dict:
    """在 dst/device 下生成 Manifest.db + payload 树，返回统计信息。

    domains=None 表示用真实备份的**全部**域（post-prune 规模接近生产）。
    """
    dev = dst / "device"
    if dev.exists():
        shutil.rmtree(dev)
    dev.mkdir(parents=True)

    is_protective, keep_entry = load_predicates()
    src = sqlite3.connect(f"file:{REAL_DB}?mode=ro&immutable=1", uri=True)
    if domains is None:
        rows = src.execute(
            "SELECT fileID, domain, relativePath, flags, file FROM Files").fetchall()
    else:
        rows = src.execute(
            "SELECT fileID, domain, relativePath, flags, file FROM Files "
            f"WHERE domain IN ({','.join('?' * len(domains))})", domains).fetchall()
    src.close()

    # 1) 剪枝谓词（与 clean_backup_for_restore 一致：file/dir 行同一个谓词）
    survivors = [r for r in rows if keep_entry(r[1], r[2])]
    # 2) 真实剪枝还会丢掉「payload 缺失」的 flags=1 行 —— 故意留几条来复现它
    file_rows = [r for r in survivors if r[3] == 1]
    drop_ids = {r[0] for r in file_rows[:drop_payload_rows]}
    survivors = [r for r in survivors if r[0] not in drop_ids]

    db = dev / "Manifest.db"
    conn = sqlite3.connect(str(db))
    for stmt in SCHEMA:
        conn.execute(stmt)
    conn.executemany(
        "INSERT INTO Files (fileID, domain, relativePath, flags, file) VALUES (?,?,?,?,?)",
        [(r[0], r[1], r[2], r[3], r[4]) for r in survivors])

    # 3) 为存活行写 payload（真实布局 <aa>/<fileID>），内容确定可复现。
    #    真实设备行永远「行描述的 Size/Digest == payload」，所以合成 payload 之后
    #    必须把这两个字段一起改成自洽的值，否则 fixture 本身是坏数据。
    payloads = 0
    updates = []
    for file_id, _domain, _rel, flags, blob in survivors:
        if flags != 1:
            continue
        data = b"PRISTINE:" + file_id.encode()
        p = dev / file_id[:2] / file_id
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        obj = plistlib.loads(blob)
        info = obj["$objects"][1]
        info["Size"] = len(data)
        if "Digest" in info:
            obj["$objects"][info["Digest"]] = hashlib.sha1(data).digest()
        updates.append((plistlib.dumps(obj, fmt=plistlib.FMT_BINARY), file_id))
        payloads += 1
    conn.executemany("UPDATE Files SET file = ? WHERE fileID = ?", updates)
    conn.commit()
    conn.close()

    return {
        "real_rows_scanned": len(rows),
        "rows_after_prune": len(survivors),
        "payload_files": payloads,
        "dropped_missing_payload": len(drop_ids),
        "home_domain_dirs": sorted(
            r[2] for r in survivors
            if r[1] == "HomeDomain" and r[3] == 2 and "/" not in r[2]),
    }


def pristine_bytes(dev: Path, domain: str, rel: str) -> bytes:
    fid = hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()
    return (dev / fid[:2] / fid).read_bytes()
