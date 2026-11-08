"""A bounded, byte-offset log tail independent of Qt and logging handlers."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TailSnapshot:
    text: str
    offset: int
    available: bool


class LogTailReader:
    def __init__(self, path, limit=1024 * 1024):
        self.path, self.limit = path, limit
        self.reset()

    def reset(self):
        self.text, self.offset, self.identity = "", 0, None

    def poll(self):
        try:
            # Use metadata from the same open file that is read: rotation
            # between stat(path) and open(path) must not mix two files.
            with open(self.path, "rb") as stream:
                stat = os.fstat(stream.fileno())
                identity = (stat.st_dev, stat.st_ino)
                if not stat.st_ino:
                    identity = (stat.st_dev, getattr(stat, "st_birthtime", stat.st_ctime_ns))
                if identity != self.identity or stat.st_size < self.offset:
                    self.text, self.offset = "", 0
                self.identity = identity
                start = max(self.offset, stat.st_size - self.limit)
                stream.seek(start)
                data = stream.read(self.limit)
                if start > self.offset:
                    self.text = ""
                    # The bounded suffix may start in the middle of a line.
                    first = data.find(b"\n")
                    if first >= 0:
                        start += first + 1
                        data = data[first + 1:]
                end = data.rfind(b"\n")
                self.offset = start
                if end >= 0:
                    self.offset += end + 1
                    self.text = (self.text + data[:end + 1].decode(
                        "utf-8", errors="replace"))[-self.limit:]
            return TailSnapshot(self.text, self.offset, True)
        except OSError:
            self.reset()
            return TailSnapshot("", 0, False)
