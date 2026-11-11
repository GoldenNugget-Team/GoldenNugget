#!/usr/bin/env python3
"""Inspect a sparse backup directory (sqlite Manifest.db + plists + payloads)."""
import plistlib
import sqlite3
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/gn_sparse_debug")
db = sqlite3.connect(f"file:{root / 'Manifest.db'}?mode=ro", uri=True)

rows = list(db.execute("SELECT fileID, domain, relativePath, flags, length(file) FROM Files"))
print("Manifest.db rows:", len(rows))

def blob_info(blob):
    try:
        info = plistlib.loads(blob)["$objects"][1]
        return dict(mode=info.get("Mode"), size=info.get("Size"),
                    inode=info.get("InodeNumber"), pc=info.get("ProtectionClass"))
    except Exception:
        return {}

bad = [r for r in rows if not r[1] or not r[2]]
print("rows with empty domain/relativePath:", len(bad))
for r in bad[:8]:
    print("   BAD:", r)

domains = {}
for file_id, domain, rel, fl, _ in rows:
    domains.setdefault(domain or "<root>", 0)
    domains[domain or "<root>"] += 1
for d, c in sorted(domains.items()):
    print(f"  {c:4d}  {d}")

pb = [r for r in rows if r[1] and "PosterBoard" in r[1]]
print("\nPosterBoard rows:", len(pb))
for file_id, domain, rel, fl, _ in pb[:12]:
    kind = "DIR " if fl == 2 else "file"
    print(f"  {kind} flags={fl} {rel}")

missing = []
present = 0
for file_id, domain, rel, fl, _ in rows:
    if not domain:
        continue
    if fl != 1:
        continue
    payload = root / file_id[:2] / file_id
    if payload.is_file():
        present += 1
    else:
        missing.append((domain, rel))
print("\npayloads present:", present, "| missing:", len(missing))
for d, p in missing[:12]:
    print("  MISSING:", d, p)

for file_id, domain, rel, fl, _ in rows[:1]:
    info = blob_info(db.execute("SELECT file FROM Files WHERE fileID=?", (file_id,)).fetchone()[0])
    print(f"\nsample row {rel!r}{(' (' + domain + ')') if domain else ''}: {info}")

st = plistlib.loads((root / "Status.plist").read_bytes())
print("Status.plist Version:", st.get("Version"))

mp = root / "Manifest.plist"
m = plistlib.loads(mp.read_bytes())
print("Applications:", m.get("Applications"))