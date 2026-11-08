"""Bounded ZIP inspection shared by portable presets and wallpaper reports."""
import stat
from pathlib import PurePosixPath

MAX_FILES = 20000
MAX_FILE_BYTES = 512 * 1024 ** 2
MAX_TOTAL_BYTES = 2 * 1024 ** 3


def safe_member(name):
    parts = name.rstrip('/').split('/')
    return (bool(name) and not name.startswith('/') and '\\' not in name
            and '\x00' not in name and ':' not in name
            and all(part not in ('', '.', '..') for part in parts)
            and not PurePosixPath(name).is_absolute())


def checked_members(archive):
    """Reject ambiguous paths, links, encryption and unreasonable expansion."""
    members = archive.infolist()
    if len(members) > MAX_FILES:
        raise ValueError('Archive contains too many entries.')
    seen, total = set(), 0
    for info in members:
        name = info.filename
        canonical = name.rstrip('/').casefold()
        if not safe_member(name) or '\x00' in info.orig_filename or canonical in seen:
            raise ValueError(f'Unsafe or duplicate archive path: {name}')
        seen.add(canonical)
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
            raise ValueError(f'Unsupported archive entry: {name}')
        if info.flag_bits & 1:
            raise ValueError('Encrypted ZIP entries are not supported.')
        total += info.file_size
        if info.file_size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError('Archive exceeds the supported unpacked size.')
        if info.file_size > 16 * 1024 ** 2 and info.file_size > max(info.compress_size, 1) * 1000:
            raise ValueError(f'Excessive archive expansion: {name}')
    return members


def package_path(root, relative):
    """Resolve an untrusted package path, including wildcard patterns."""
    from pathlib import Path
    if not isinstance(relative, str) or not safe_member(relative):
        raise ValueError(f"Unsafe template path: {relative!r}")
    base = Path(root).resolve()
    target = base.joinpath(*relative.split('/')).resolve()
    if not target.is_relative_to(base) or target == base:
        raise ValueError(f"Template path escapes its package: {relative!r}")
    return str(target)


def package_matches(root, relative):
    """Validate the pattern and every match before the caller mutates files."""
    import glob
    from pathlib import Path
    pattern = package_path(root, relative)
    base = Path(root).resolve()
    matches = glob.glob(pattern, recursive=True)
    for match in matches:
        target = Path(match).resolve()
        if not target.is_relative_to(base) or target == base:
            raise ValueError(f"Template path escapes its package: {relative!r}")
    return matches
