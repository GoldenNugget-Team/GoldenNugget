"""Batch ordered XML/plist edits without rereading the same document."""
import os
import plistlib
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_current = ContextVar("template_patch_session", default=None)


class PatchSession:
    def __init__(self):
        self.documents = {}

    def xml(self, path):
        key = Path(path), "xml"
        if key not in self.documents:
            self.documents[key] = ET.parse(path)
        return self.documents[key]

    def plist(self, path):
        key = Path(path), "plist"
        if key not in self.documents:
            with open(path, "rb") as stream:
                self.documents[key] = plistlib.load(stream)
        return self.documents[key]

    def flush(self):
        staged = []
        try:
            # Serialize every document before replacing any of them. A bad
            # patch/serialization never exposes half-written XML or plist.
            for (path, kind), document in self.documents.items():
                with tempfile.NamedTemporaryFile(dir=path.parent,
                                                prefix=".patch-", delete=False) as stream:
                    staged.append((Path(stream.name), path))
                    if kind == "xml":
                        document.write(stream, encoding="UTF-8", xml_declaration=True)
                    else:
                        plistlib.dump(document, stream)
            for temporary, destination in staged:
                os.replace(temporary, destination)
            self.documents.clear()
        finally:
            for temporary, _ in staged:
                temporary.unlink(missing_ok=True)


def current_patch_session():
    return _current.get()


@contextmanager
def patch_batch():
    session = PatchSession()
    token = _current.set(session)
    try:
        yield session
        session.flush()
    finally:
        _current.reset(token)
