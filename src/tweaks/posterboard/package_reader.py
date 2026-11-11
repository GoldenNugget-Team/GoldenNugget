"""Indexed archive resources with bounded extraction and validated destinations."""
import fnmatch
import os
import re
from bisect import bisect_left
from pathlib import Path
from shutil import copyfileobj

from src.controllers.archive_safety import package_path
from src.utils.cancellation import check_cancelled


class PackageReader:
    def __init__(self, archive):
        self.archive = archive
        names = archive.namelist()
        self.order = {name: index for index, name in enumerate(names)}
        self.names = sorted((os.path.normcase(name), name) for name in names)
        self.keys = [key for key, _ in self.names]

    def matches(self, patterns, base=""):
        extracted = set()
        for pattern in patterns:
            check_cancelled()
            pattern = base + pattern
            prefix = re.split(r"[\[*?]", pattern, maxsplit=1)[0]
            normalized = os.path.normcase(prefix)
            candidates = []
            for index in range(bisect_left(self.keys, normalized), len(self.keys)):
                key, name = self.names[index]
                if not key.startswith(normalized) or (prefix == pattern and key != normalized):
                    break
                candidates.append(name)
            candidates.sort(key=self.order.__getitem__)
            for name in fnmatch.filter(candidates, pattern):
                if name not in extracted:
                    extracted.add(name)
                    yield name

    def extract_resource(self, member, root):
        check_cancelled()
        destination = Path(package_path(root, member))
        info = self.archive.getinfo(member)
        if info.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.archive.open(info) as source, destination.open("wb") as output:
            copyfileobj(source, output, length=1024 * 1024)
        if destination.stat().st_size != info.file_size:
            raise OSError(f"Incomplete template resource: {member}")
        return str(destination)
