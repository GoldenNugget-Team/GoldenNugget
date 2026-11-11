"""Community preset catalog: a moderated list of share codes kept on GitHub.

The catalog lives in its own repository (CATALOG_REPO). Each preset is one
``presets/<id>.json`` file holding a share code plus a title, author and iOS
range; maintainers review every pull request, and a GitHub Actions check
(``tools/preset_catalog.py check``) runs the same validation as this module.
After a merge, ``tools/preset_catalog.py build`` turns the folder into one
``index.json`` that GitHub Pages serves at INDEX_URL.

The app only ever reads that index. Every entry is validated again here and
its share code is decoded locally, so a bad or tampered index can at worst
show fewer presets. Importing an entry stores a preset; it never applies it.
Submitting opens GitHub in the browser with the file already filled in.

The catalog also holds ``.batter`` templates (``templates/<id>.batter``).
``build`` copies each one next to index.json and lists its title, the files
its tweaks write and its SHA-256. The app downloads a template only from
TEMPLATES_URL by id, checks its size and hash, then loads it like any other
template file; adding it never applies anything either.
"""
import hashlib
import json
import os
import re
import time
import zipfile
from dataclasses import dataclass, field
from urllib.parse import quote

from PySide6.QtCore import QT_TRANSLATE_NOOP, QStandardPaths

from src.controllers import share_code

CATALOG_REPO = "GoldenNugget-Team/GoldenNugget-Presets"
INDEX_URL = "https://goldennugget-team.github.io/GoldenNugget-Presets/index.json"
REPO_URL = f"https://github.com/{CATALOG_REPO}"
TEMPLATES_URL = INDEX_URL.rsplit("/", 1)[0] + "/templates/"
TEMPLATES_DIR_NAME = "catalog_templates"
MAX_TEMPLATE_BYTES = 25 * 1024 * 1024
MAX_TEMPLATE_WRITES = 64
FORMAT_VERSION = 1
MAX_INDEX_BYTES = 4 * 1024 * 1024
MAX_PRESETS = 2000
MAX_SUBMIT_URL = 7500          # longer prefilled URLs get cut by GitHub or the browser
CACHE_FILENAME = "preset_catalog.json"

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")
VERSION_PATTERN = re.compile(r"^\d{1,2}(\.\d{1,2}){0,2}$")
TEXT_LIMITS = {"name": 60, "author": 40, "description": 500}
MAX_TAGS = 8
MAX_TAG_CHARS = 24


class CatalogError(ValueError):
    pass


def version_tuple(version) -> tuple:
    parts = []
    for part in str(version or "").split("."):
        digits = re.match(r"\d+", part)
        parts.append(int(digits.group()) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


@dataclass
class CatalogEntry:
    id: str
    name: str
    author: str
    code: str
    description: str = ""
    ios_min: str = ""
    ios_max: str = ""
    tags: list = field(default_factory=list)
    tweak_count: int = 0
    untested: bool = False           # the author has not tried it on an iPhone

    def supports(self, ios_version) -> bool:
        """True when no iOS range is given or ``ios_version`` is inside it.

        ``ios_max`` "18" covers every 18.x release."""
        if not ios_version:
            return True
        version = version_tuple(ios_version)
        if self.ios_min and version < version_tuple(self.ios_min):
            return False
        if self.ios_max:
            limit = list(version_tuple(self.ios_max))
            depth = len(self.ios_max.split("."))
            if version[:depth] > tuple(limit[:depth]):
                return False
        return True

    def ios_range(self) -> str:
        if self.ios_min and self.ios_max:
            return f"{self.ios_min} – {self.ios_max}"
        if self.ios_min:
            return f"{self.ios_min}+"
        if self.ios_max:
            return f"≤ {self.ios_max}"
        return ""

    def matches(self, text: str) -> bool:
        text = (text or "").strip().casefold()
        if not text:
            return True
        haystack = " ".join([self.name, self.author, self.description, *self.tags]).casefold()
        return all(word in haystack for word in text.split())

    def to_file(self) -> dict:
        data = {"format": FORMAT_VERSION, "name": self.name, "author": self.author,
                "description": self.description, "ios_min": self.ios_min,
                "ios_max": self.ios_max, "tags": list(self.tags), "untested": self.untested,
                "code": self.code}
        return {key: value for key, value in data.items() if value or key in ("format", "code")}


@dataclass
class TemplateEntry(CatalogEntry):
    """A .batter template in the catalog; ``code`` is unused."""
    size: int = 0
    sha256: str = ""
    domain: str = ""
    writes: list = field(default_factory=list)   # (tweak label, [paths])

    @property
    def url(self) -> str:
        return f"{TEMPLATES_URL}{self.id}.batter"

    @property
    def filename(self) -> str:
        return f"{self.id}.batter"

    def to_row(self) -> dict:
        row = {"id": self.id, "name": self.name, "author": self.author, "description": self.description,
               "ios_min": self.ios_min, "ios_max": self.ios_max, "tags": list(self.tags),
               "untested": self.untested, "size": self.size, "sha256": self.sha256, "domain": self.domain,
               "tweaks": [{"label": label, "writes": list(paths)} for label, paths in self.writes]}
        return {key: value for key, value in row.items() if value or key in ("id", "size", "sha256")}


def _text(raw, key, required=False):
    value = raw.get(key, "")
    if not isinstance(value, str):
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "A text field has the wrong type."))
    value = " ".join(value.split()) if key != "description" else value.strip()
    if required and not value:
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "The name and author are required."))
    if len(value) > TEXT_LIMITS[key]:
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "A text field is too long."))
    return value


def _version(raw, key):
    value = raw.get(key, "")
    if not isinstance(value, str) or (value and not VERSION_PATTERN.match(value)):
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "iOS versions look like 18 or 18.4."))
    return value


def _untested(raw) -> bool:
    value = raw.get("untested", False)
    if not isinstance(value, bool):
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "untested must be true or false."))
    return value


def validate_entry(raw, entry_id: str, validate=None) -> CatalogEntry:
    """Check one catalog file (or index row) and decode its share code.

    ``validate`` is the preset structure check (PresetManager._valid_import_structure)."""
    if not isinstance(raw, dict) or raw.get("format", FORMAT_VERSION) != FORMAT_VERSION:
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "Unsupported catalog entry format."))
    if not isinstance(entry_id, str) or not ID_PATTERN.match(entry_id):
        raise CatalogError(QT_TRANSLATE_NOOP(
            "PresetCatalog", "File names use lowercase letters, digits and dashes (2–48 characters)."))
    tags = raw.get("tags", [])
    if not isinstance(tags, list) or len(tags) > MAX_TAGS or not all(
            isinstance(tag, str) and 0 < len(tag.strip()) <= MAX_TAG_CHARS for tag in tags):
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "Up to 8 tags of at most 24 characters."))
    code = raw.get("code")
    if not isinstance(code, str):
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "The entry has no share code."))
    entry = CatalogEntry(
        id=entry_id, name=_text(raw, "name", True), author=_text(raw, "author", True),
        description=_text(raw, "description"), code=code.strip(),
        ios_min=_version(raw, "ios_min"), ios_max=_version(raw, "ios_max"),
        tags=[tag.strip().lower() for tag in tags], untested=_untested(raw))
    if entry.ios_min and entry.ios_max and version_tuple(entry.ios_min) > version_tuple(entry.ios_max):
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "The minimum iOS version is above the maximum."))
    if not entry.code.startswith(share_code.PREFIX) or share_code.extract(entry.code) != entry.code:
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "The share code must be the whole value."))
    entry.tweak_count = share_code.decode(entry.code, validate)["shared_count"]
    if not entry.tweak_count:
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "The share code turns on no known tweaks."))
    return entry


def validate_template_row(raw) -> TemplateEntry:
    """Check one ``templates`` row of index.json (display data only: the
    downloaded file is checked by hash and loaded with the full rules)."""
    if not isinstance(raw, dict):
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "Unsupported catalog entry format."))
    entry_id = raw.get("id")
    if not isinstance(entry_id, str) or not ID_PATTERN.match(entry_id):
        raise CatalogError(QT_TRANSLATE_NOOP(
            "PresetCatalog", "File names use lowercase letters, digits and dashes (2–48 characters)."))
    tags = raw.get("tags", [])
    if not isinstance(tags, list) or len(tags) > MAX_TAGS or not all(
            isinstance(tag, str) and 0 < len(tag.strip()) <= MAX_TAG_CHARS for tag in tags):
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "Up to 8 tags of at most 24 characters."))
    size, digest, domain = raw.get("size"), raw.get("sha256"), raw.get("domain", "")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_TEMPLATE_BYTES \
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) \
            or not isinstance(domain, str) or len(domain) > 200:
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "The template entry is damaged."))
    writes, count = [], 0
    for tweak in raw.get("tweaks", []) if isinstance(raw.get("tweaks", []), list) else [None]:
        paths = tweak.get("writes") if isinstance(tweak, dict) else None
        label = tweak.get("label") if isinstance(tweak, dict) else None
        if not isinstance(label, str) or not isinstance(paths, list) \
                or not all(isinstance(path, str) and len(path) <= 1024 for path in paths):
            raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "The template entry is damaged."))
        count += len(paths)
        writes.append((label[:80], paths))
    if count > MAX_TEMPLATE_WRITES:
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "The template entry is damaged."))
    entry = TemplateEntry(
        id=entry_id, name=_text(raw, "name", True), author=_text(raw, "author", True),
        description=_text(raw, "description"), code="",
        ios_min=_version(raw, "ios_min"), ios_max=_version(raw, "ios_max"),
        tags=[tag.strip().lower() for tag in tags], size=size, sha256=digest, domain=domain, writes=writes,
        untested=_untested(raw))
    entry.tweak_count = len(writes)
    return entry


def parse_index(data: bytes, validate=None) -> tuple[list, int]:
    """Return (valid entries, number of rejected rows) from index.json bytes."""
    entries, _templates, rejected = parse_catalog(data, validate)
    return entries, rejected


def parse_catalog(data: bytes, validate=None) -> tuple[list, list, int]:
    """Return (presets, templates, number of rejected rows) from index.json bytes."""
    if len(data) > MAX_INDEX_BYTES:
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "The catalog is too large."))
    try:
        payload = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "The catalog could not be read.")) from error
    if not isinstance(payload, dict) or payload.get("format") != FORMAT_VERSION \
            or not isinstance(payload.get("presets"), list):
        raise CatalogError(QT_TRANSLATE_NOOP(
            "PresetCatalog", "The catalog needs a newer version of GoldenNugget."))
    entries, rejected, seen = [], 0, set()
    for row in payload["presets"][:MAX_PRESETS]:
        try:
            entry = validate_entry(row, row.get("id") if isinstance(row, dict) else None, validate)
        except (CatalogError, share_code.ShareCodeError):
            rejected += 1
            continue
        if entry.id in seen:
            rejected += 1
            continue
        seen.add(entry.id)
        entries.append(entry)
    templates, seen = [], set()
    rows = payload.get("templates", [])
    for row in rows[:MAX_PRESETS] if isinstance(rows, list) else []:
        try:
            entry = validate_template_row(row)
        except CatalogError:
            rejected += 1
            continue
        if entry.id in seen:
            rejected += 1
            continue
        seen.add(entry.id)
        templates.append(entry)
    return entries, templates, rejected


def build_index(entries, generated=None, templates=()) -> dict:
    rows = []
    for entry in sorted(entries, key=lambda item: item.name.casefold()):
        row = entry.to_file()
        row["id"] = entry.id
        rows.append(row)
    index = {"format": FORMAT_VERSION, "generated": int(generated if generated is not None else time.time()),
             "presets": rows}
    if templates:
        index["templates"] = [entry.to_row() for entry in sorted(templates, key=lambda item: item.name.casefold())]
    return index


def template_entry(path, entry_id: str, data: bytes = None) -> TemplateEntry:
    """Catalog entry for a .batter file; loads it with the app's template rules.

    Raises CatalogError (or the template's own error) when it is unusable."""
    from src.tweaks.posterboard.template_file import TemplateFile
    if not isinstance(entry_id, str) or not ID_PATTERN.match(entry_id):
        raise CatalogError(QT_TRANSLATE_NOOP(
            "PresetCatalog", "File names use lowercase letters, digits and dashes (2–48 characters)."))
    if data is None:
        with open(path, "rb") as file:
            data = file.read(MAX_TEMPLATE_BYTES + 1)
    if len(data) > MAX_TEMPLATE_BYTES:
        raise CatalogError(QT_TRANSLATE_NOOP("PresetCatalog", "The template is larger than 25 MB."))
    template = TemplateFile(str(path))
    try:
        with zipfile.ZipFile(str(path)) as archive:
            config = json.loads(archive.read(template.json_path))
        raw = {"name": template.name or "", "author": template.author or "",
               "description": template.description or "", "ios_min": template.min_version or "",
               "ios_max": template.max_version or "", "tags": config.get("tags", []),
               "untested": config.get("untested", False)}
        for key in ("name", "author", "description", "ios_min", "ios_max"):
            if not isinstance(raw[key], str):
                raw[key] = ""
        row = dict(raw, id=entry_id, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                   domain=template.domain or "",
                   tweaks=[{"label": tweak.label, "writes": tweak.paths()} for tweak in template.tweaks])
        return validate_template_row(row)
    finally:
        template.clean_files()


# --- what is already installed ------------------------------------------

INSTALLED, UPDATE = "installed", "update"


def code_digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def catalog_mark(entry: CatalogEntry) -> dict:
    """Preset metadata linking an imported preset to its catalog entry."""
    return {"id": entry.id, "sha256": code_digest(entry.code)}


def installed_items(pm, folder=None) -> dict:
    """{("preset" | "template", id): (sha256, preset name or file path)}."""
    result = {}
    for name in pm.list_presets():
        meta = pm.get_preset_metadata(name) or {}
        mark = meta.get("catalog")
        if isinstance(mark, dict) and isinstance(mark.get("id"), str) and isinstance(mark.get("sha256"), str):
            result[("preset", mark["id"])] = (mark["sha256"], name)
    try:
        folder = folder or templates_dir()
        for file in os.listdir(folder):
            if file.endswith(".batter") and ID_PATTERN.match(file[:-len(".batter")]):
                path = os.path.join(folder, file)
                with open(path, "rb") as stream:
                    digest = hashlib.sha256(stream.read(MAX_TEMPLATE_BYTES + 1)).hexdigest()
                result[("template", file[:-len(".batter")])] = (digest, path)
    except OSError:
        pass
    return result


def entry_status(entry, installed: dict):
    """(INSTALLED | UPDATE | None, preset name or path) for a catalog entry."""
    if isinstance(entry, TemplateEntry):
        known = installed.get(("template", entry.id))
        digest = entry.sha256
    else:
        known = installed.get(("preset", entry.id))
        digest = code_digest(entry.code)
    if known is None:
        return None, None
    return (INSTALLED if known[0] == digest else UPDATE), known[1]


def count_updates(entries, installed: dict) -> int:
    return sum(entry_status(entry, installed)[0] == UPDATE for entry in entries)


# --- downloaded templates -------------------------------------------------

def templates_dir() -> str:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    path = os.path.join(base, TEMPLATES_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def save_template(entry: TemplateEntry, data: bytes) -> str:
    """Check downloaded bytes against the index and store them; returns the path."""
    if len(data) != entry.size or hashlib.sha256(data).hexdigest() != entry.sha256:
        raise CatalogError(QT_TRANSLATE_NOOP(
            "PresetCatalog", "The downloaded template does not match the catalog. Try again later."))
    path = os.path.join(templates_dir(), entry.filename)
    temporary = path + ".part"
    with open(temporary, "wb") as file:
        file.write(data)
    os.replace(temporary, path)
    return path


# --- local cache ----------------------------------------------------------

def cache_path() -> str:
    base = QStandardPaths.writableLocation(QStandardPaths.CacheLocation) \
        or QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, CACHE_FILENAME)


def read_cache():
    """(bytes, saved_at) of the last good index, or (None, 0)."""
    try:
        path = cache_path()
        with open(path, "rb") as file:
            return file.read(MAX_INDEX_BYTES + 1), os.path.getmtime(path)
    except OSError:
        return None, 0


def write_cache(data: bytes):
    try:
        with open(cache_path(), "wb") as file:
            file.write(data)
    except OSError:
        pass


# --- submitting -----------------------------------------------------------

def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").casefold()).strip("-")[:48].strip("-")
    return slug if ID_PATTERN.match(slug) else "preset-" + time.strftime("%Y%m%d%H%M%S")


def submission(name, author, code, description="", ios_min="", ios_max="", tags=(), validate=None,
               untested=False):
    """Validated (file name, file text) for a new catalog entry."""
    raw = {"format": FORMAT_VERSION, "name": name, "author": author, "description": description,
           "ios_min": ios_min, "ios_max": ios_max, "code": code, "untested": bool(untested),
           "tags": [tag.strip() for tag in tags if tag.strip()]}
    entry = validate_entry(raw, slugify(name), validate)
    text = json.dumps(entry.to_file(), ensure_ascii=False, indent=2) + "\n"
    return f"{entry.id}.json", text


def submit_url(filename: str, text: str) -> tuple[str, bool]:
    """GitHub "new file" page for the catalog; (url, prefilled).

    GitHub forks the repository and opens a pull request for people without
    write access. When the file is too long for a URL, only the name is
    filled in and the caller puts the text on the clipboard instead."""
    base = f"{REPO_URL}/new/main/presets?filename={quote(filename)}"
    url = f"{base}&value={quote(text, safe='')}"
    if len(url) <= MAX_SUBMIT_URL:
        return url, True
    return base, False
