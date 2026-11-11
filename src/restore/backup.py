# PEP 810: defer operation-only dependencies on Python 3.15+; eager on older Python.
__lazy_modules__ = (
    "sqlite3",
)

import plistlib
import sqlite3
from base64 import b64decode
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from pathlib import Path
from random import randbytes
from typing import Optional

from src.restore import mbdb
from src.utils.file_to_restore import _FileMode
from src.utils.payload import copy_payload

# Default nugget file right
# RWX:RX:RX 
DEFAULT = _FileMode.S_IRUSR | _FileMode.S_IWUSR | _FileMode.S_IXUSR | _FileMode.S_IRGRP | _FileMode.S_IXGRP | _FileMode.S_IROTH | _FileMode.S_IXOTH

@dataclass
class BackupFile:
    path: str
    domain: str

    def to_record(self) -> mbdb.MbdbRecord:
        raise NotImplementedError()

@dataclass
class ConcreteFile(BackupFile):
    contents: bytes
    src_path: Optional[str] = None
    owner: int = 0
    group: int = 0
    inode: Optional[int] = None
    mode: _FileMode = DEFAULT
    key: bytes = b""
    flags: int = 4

    hash: bytes = None
    size: int = None

    def read_contents(self) -> bytes:
        contents = self.contents
        if self.contents == None:
            with open(self.src_path, "rb") as in_file:
                contents = in_file.read()
        # prepopulate hash and size
        self.hash = sha1(contents).digest()
        self.size = len(contents)
        return contents

    def write_contents(self, output=None):
        self.size, self.hash = copy_payload(
            self.contents if self.contents is not None else self.src_path, output)

    def to_record(self) -> mbdb.MbdbRecord:
        if self.inode is None:
            self.inode = int.from_bytes(randbytes(8), "big")
        if self.hash == None or self.size == None:
            self.write_contents()
        return mbdb.MbdbRecord(
            domain=self.domain,
            filename=self.path,
            link="",
            hash=self.hash,
            key=self.key,
            mode=self.mode | _FileMode.S_IFREG,
            inode=self.inode,
            user_id=self.owner,
            group_id=self.group,
            mtime=int(datetime.now().timestamp()),
            atime=int(datetime.now().timestamp()),
            ctime=int(datetime.now().timestamp()),
            size=self.size,
            flags=self.flags,
            properties=[]
        )

@dataclass
class Directory(BackupFile):
    owner: int = 0
    group: int = 0
    mode: _FileMode = DEFAULT

    def to_record(self) -> mbdb.MbdbRecord:
        return mbdb.MbdbRecord(
            domain=self.domain,
            filename=self.path,
            link="",
            hash=b"",
            key=b"",
            mode=self.mode | _FileMode.S_IFDIR,
            inode=0,
            user_id=self.owner,
            group_id=self.group,
            mtime=int(datetime.now().timestamp()),
            atime=int(datetime.now().timestamp()),
            ctime=int(datetime.now().timestamp()),
            size=0,
            flags=4,
            properties=[]
        )
    
@dataclass
class AppBundle:
    identifier: str
    path: str
    container_content_class: str
    version: str = 804

@dataclass
class Backup:
    files: list[BackupFile]
    apps: list[AppBundle]
    device_manifest: Optional[dict] = None
    # iOS 26.x mobilebackup2 speaks the legacy MBDB backup format
    # (Status.plist 2.4 / Manifest.mbdb / Manifest.plist 9.1/20.0 with an empty
    # Lockdown). iOS 27+ uses the modern sqlite format (3.3 / Manifest.db /
    # Manifest.plist 10.0/24.0 with Lockdown filled from device_manifest).
    manifest_ios27: bool = True

    def write_to_directory(self, directory: Path):
        if not self.manifest_ios27:
            # iOS 26 and below: legacy MBDB layout — every payload sits flat in
            # the backup root, named by its sha1. The device's restore daemon
            # reads the file set out of Manifest.mbdb.
            for file in self.files:
                if isinstance(file, ConcreteFile):
                    with open(directory / sha1((file.domain + "-" + file.path).encode()).digest().hex(), "wb") as f:
                        file.write_contents(f)
            with open(directory / "Manifest.mbdb", "wb") as f:
                f.write(self.generate_manifest_db().to_bytes())
        else:
            # iOS 27+: modern sqlite manifest with payloads under <xx>/<fileID>.
            for file in self.files:
                if isinstance(file, ConcreteFile):
                    file_id = sha1((file.domain + "-" + file.path).encode()).digest().hex()
                    payload = directory / file_id[:2] / file_id
                    payload.parent.mkdir(parents=True, exist_ok=True)
                    with open(payload, "wb") as f:
                        file.write_contents(f)

            self._write_manifest_db(directory)

        with open(directory / "Status.plist", "wb") as f:
            f.write(self.generate_status())
        
        with open(directory / "Manifest.plist", "wb") as f:
            f.write(self.generate_manifest())

        with open(directory / "Info.plist", "wb") as f:
            f.write(plistlib.dumps({}))
        

    def _mb_file_blob(self, relative_path: str, mode: int, size: int,
                      mtime: int, inode: int, uid: int, gid: int,
                      protection_class: int) -> bytes:
        # NSKeyedArchiver-encoded MBFile plist — the exact shape the device
        # writes into a real Manifest.db (backup format 3.3 / sqlite).
        return plistlib.dumps({
            "$version": 100000,
            "$archiver": "NSKeyedArchiver",
            "$top": {"root": plistlib.UID(1)},
            "$objects": [
                None,
                {
                    "LastModified": mtime,
                    "Flags": 0,
                    "GroupID": gid,
                    "$class": plistlib.UID(3),
                    "LastStatusChange": mtime,
                    "RelativePath": plistlib.UID(2),
                    "Birth": mtime,
                    "Size": size,
                    "InodeNumber": inode,
                    "Mode": mode,
                    "UserID": uid,
                    "ProtectionClass": protection_class,
                },
                relative_path,
                {"$classname": "MBFile", "$classes": ["MBFile", "NSObject"]},
            ],
        }, fmt=plistlib.FMT_BINARY)

    def _write_manifest_db(self, directory: Path) -> None:  # Manifest.db
        file_id_of = lambda f: sha1((f.domain + "-" + f.path).encode()).digest().hex()
        records = []
        now = int(datetime.now().timestamp())
        dir_inode = 0
        for file in self.files:
            file_id = file_id_of(file)
            if isinstance(file, ConcreteFile):
                if file.inode is None:
                    file.inode = int.from_bytes(randbytes(8), "big")
                if file.size is None:
                    file.read_contents()
                blob = self._mb_file_blob(file.path, int(_FileMode.S_IFREG | file.mode),
                                          file.size, now, file.inode,
                                          file.owner, file.group, 3)
                records.append((file_id, file.domain, file.path, 1, blob))
            else:
                # Directory row (flags=2) — no payload file, dirs are created
                # by the restore agent from the row alone. Real device rows
                # carry a unique inode (the agent dedupes by it and skips
                # rows without one), so stamp one per dir instead of 0.
                dir_inode += 1
                blob = self._mb_file_blob(file.path, int(_FileMode.S_IFDIR | file.mode),
                                          0, now, dir_inode, file.owner, file.group, 0)
                records.append((file_id, file.domain, file.path, 2, blob))

        conn = sqlite3.connect(str(directory / "Manifest.db"))
        try:
            cur = conn.cursor()
            cur.executescript("""
                CREATE TABLE Files (fileID TEXT PRIMARY KEY,
                                    domain TEXT, relativePath TEXT,
                                    flags INTEGER, file BLOB);
                CREATE TABLE Properties (key TEXT PRIMARY KEY, value BLOB);
                CREATE INDEX FilesDomainsRelativePathIdx ON Files(domain, relativePath);
                CREATE INDEX FilesFlagsIdx ON Files(flags);
                CREATE INDEX FilesRelativePathIdx ON Files(relativePath);
            """)
            # OR REPLACE: two files can share a fileID only when their
            # domain+path collide, so the payload is identical anyway — keep
            # the last row instead of aborting the whole sparse restore.
            cur.executemany(
                "INSERT OR REPLACE INTO Files (fileID, domain, relativePath, flags, file) "
                "VALUES (?, ?, ?, ?, ?)", records)
            conn.commit()
        finally:
            conn.close()
    
    def generate_manifest_db(self): # Manifest.mbdb
        records = []
        for file in self.files:
            records.append(file.to_record())
        return mbdb.Mbdb(records=records)
    
    def generate_status(self) -> bytes: # Status.plist
        return plistlib.dumps({
            "BackupState": "new",
            "Date": datetime.fromisoformat("1970-01-01T00:00:00+00:00"),
            "IsFullBackup": False,
            "SnapshotState": "finished",
            "UUID": "00000000-0000-0000-0000-000000000000",
            "Version": "3.3" if self.manifest_ios27 else "2.4"
        })
    
    def generate_manifest(self) -> bytes: # Manifest.plist
        plist = {
            "BackupKeyBag": b64decode("""
    VkVSUwAAAAQAAAAFVFlQRQAAAAQAAAABVVVJRAAAABDud41d1b9NBICR1BH9JfVtSE1D
	SwAAACgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAV1JBUAAA
	AAQAAAAAU0FMVAAAABRY5Ne2bthGQ5rf4O3gikep1e6tZUlURVIAAAAEAAAnEFVVSUQA
	AAAQB7R8awiGR9aba1UuVahGPENMQVMAAAAEAAAAAVdSQVAAAAAEAAAAAktUWVAAAAAE
	AAAAAFdQS1kAAAAoN3kQAJloFg+ukEUY+v5P+dhc/Welw/oucsyS40UBh67ZHef5ZMk9
	UVVVSUQAAAAQgd0cg0hSTgaxR3PVUbcEkUNMQVMAAAAEAAAAAldSQVAAAAAEAAAAAktU
	WVAAAAAEAAAAAFdQS1kAAAAoMiQTXx0SJlyrGJzdKZQ+SfL124w+2Tf/3d1R2i9yNj9z
	ZCHNJhnorVVVSUQAAAAQf7JFQiBOS12JDD7qwKNTSkNMQVMAAAAEAAAAA1dSQVAAAAAE
	AAAAAktUWVAAAAAEAAAAAFdQS1kAAAAoSEelorROJA46ZUdwDHhMKiRguQyqHukotrxh
	jIfqiZ5ESBXX9txi51VVSUQAAAAQfF0G/837QLq01xH9+66vx0NMQVMAAAAEAAAABFdS
	QVAAAAAEAAAAAktUWVAAAAAEAAAAAFdQS1kAAAAol0BvFhd5bu4Hr75XqzNf4g0fMqZA
	ie6OxI+x/pgm6Y95XW17N+ZIDVVVSUQAAAAQimkT2dp1QeadMu1KhJKNTUNMQVMAAAAE
	AAAABVdSQVAAAAAEAAAAA0tUWVAAAAAEAAAAAFdQS1kAAAAo2N2DZarQ6GPoWRgTiy/t
	djKArOqTaH0tPSG9KLbIjGTOcLodhx23xFVVSUQAAAAQQV37JVZHQFiKpoNiGmT6+ENM
	QVMAAAAEAAAABldSQVAAAAAEAAAAA0tUWVAAAAAEAAAAAFdQS1kAAAAofe2QSvDC2cV7
	Etk4fSBbgqDx5ne/z1VHwmJ6NdVrTyWi80Sy869DM1VVSUQAAAAQFzkdH+VgSOmTj3yE
	cfWmMUNMQVMAAAAEAAAAB1dSQVAAAAAEAAAAA0tUWVAAAAAEAAAAAFdQS1kAAAAo7kLY
	PQ/DnHBERGpaz37eyntIX/XzovsS0mpHW3SoHvrb9RBgOB+WblVVSUQAAAAQEBpgKOz9
	Tni8F9kmSXd0sENMQVMAAAAEAAAACFdSQVAAAAAEAAAAA0tUWVAAAAAEAAAAAFdQS1kA
	AAAo5mxVoyNFgPMzphYhm1VG8Fhsin/xX+r6mCd9gByF5SxeolAIT/ICF1VVSUQAAAAQ
	rfKB2uPSQtWh82yx6w4BoUNMQVMAAAAEAAAACVdSQVAAAAAEAAAAA0tUWVAAAAAEAAAA
	AFdQS1kAAAAo5iayZBwcRa1c1MMx7vh6lOYux3oDI/bdxFCW1WHCQR/Ub1MOv+QaYFVV
	SUQAAAAQiLXvK3qvQza/mea5inss/0NMQVMAAAAEAAAACldSQVAAAAAEAAAAA0tUWVAA
	AAAEAAAAAFdQS1kAAAAoD2wHX7KriEe1E31z7SQ7/+AVymcpARMYnQgegtZD0Mq2U55u
	xwNr2FVVSUQAAAAQ/Q9feZxLS++qSe/a4emRRENMQVMAAAAEAAAAC1dSQVAAAAAEAAAA
	A0tUWVAAAAAEAAAAAFdQS1kAAAAocYda2jyYzzSKggRPw/qgh6QPESlkZedgDUKpTr4Z
	Z8FDgd7YoALY1g=="""),
            "Lockdown": self.device_manifest or {},
            "SystemDomainsVersion": "24.0" if self.manifest_ios27 else "20.0",
            "Version": "10.0" if self.manifest_ios27 else "9.1"
        }
        if self.manifest_ios27:
            plist["IsEncrypted"] = False
        # add the apps
        if len(self.apps) > 0:
            plist["Applications"] = {}
            for app in self.apps:
                appInfo = {
                    "CFBundleIdentifier": app.identifier,
                    "CFBundleVersion": app.version,
                    "ContainerContentClass": app.container_content_class,
                    "Path": app.path
                }
                plist["Applications"][app.identifier] = appInfo
        return plistlib.dumps(plist)
