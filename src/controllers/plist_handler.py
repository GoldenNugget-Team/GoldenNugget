import plistlib
from typing import Any

from .patch_session import current_patch_session


def recursive_set(plist: dict, key: str, value: Any):
    new_plist: dict = plist
    for k, v in plist.items():
        if k == key:
            new_plist[k] = value
        elif isinstance(v, dict):
            new_plist[k] = recursive_set(v, key, value)
    return new_plist

def set_plist_value(file: str, key: str, value: Any, recursive: bool = True):
    with open(file, 'rb') as in_fp:
        plist = plistlib.load(in_fp)
    if recursive:
        plist = recursive_set(plist, key, value)
    else:
        plist[key] = value
    return plistlib.dumps(plist)

def write_plist_value(file: str, key: str, value: Any, recursive: bool = True):
    session = current_patch_session()
    if session is not None:
        document = session.plist(file)
        if recursive:
            recursive_set(document, key, value)
        else:
            document[key] = value
        return
    modified = set_plist_value(file, key, value, recursive)
    with open(file, "wb") as out_fp:
        out_fp.write(modified)
