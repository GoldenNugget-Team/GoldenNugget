"""Bounded-memory payload copying and hashing for both backup formats."""
import io
import os
import tempfile
from contextlib import contextmanager
from hashlib import sha1
from pathlib import Path
from typing import TypeAlias

PayloadSource: TypeAlias = bytes | bytearray | memoryview | str | os.PathLike[str]

CHUNK_SIZE = 1024 * 1024


@contextmanager
def open_payload(source: PayloadSource):
    if isinstance(source, (bytes, bytearray, memoryview)):
        with io.BytesIO(source) as stream:
            yield stream
        return
    with open(source, "rb") as stream:
        before = os.fstat(stream.fileno())
        yield stream
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise OSError(f"Payload changed while being read: {source}")


def copy_payload(source: PayloadSource, output=None) -> tuple[int, bytes]:
    """Return (size, SHA1), optionally copying to an already open output."""
    size, digest = 0, sha1()
    with open_payload(source) as stream:
        while chunk := stream.read(CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
            if output is not None:
                output.write(chunk)
    return size, digest.digest()


def install_payload(source: PayloadSource, destination) -> tuple[int, bytes, bool]:
    """Atomically install bytes or a path, preserving equal files and hardlinks.

    At most two bounded passes over a path are needed when replacing an existing
    file. A source that changes between comparison and copying is rejected.
    Returns (size, SHA1, changed).
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    previous = None
    if destination.is_file() and not destination.is_symlink():
        digest, size, equal = sha1(), 0, True
        with open_payload(source) as stream, destination.open("rb") as existing:
            while chunk := stream.read(CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
                if equal and existing.read(len(chunk)) != chunk:
                    equal = False
            equal = equal and not existing.read(1)
        previous = size, digest.digest()
        if equal:
            return *previous, False
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".payload-",
                                         delete=False) as output:
            temporary = output.name
            info = copy_payload(source, output)
        if previous is not None and info != previous:
            raise OSError(f"Payload changed between comparison and copy: {source}")
        os.replace(temporary, destination)
        return *info, True
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
