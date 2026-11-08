"""Template metadata parsed independently of Qt controls and mutable selection."""
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class TemplateDefinition:
    config_path: str
    title: str
    author: str
    domain: str
    format_version: int
    min_version: str | None = None
    max_version: str | None = None

    @classmethod
    def read(cls, archive):
        path = next((name for name in archive.namelist()
                     if "config.json" in name.lower()
                     and "descriptor" not in name.lower()
                     and "container" not in name.lower()), None)
        if path is None:
            return None, None
        with archive.open(path) as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ValueError("The template configuration must be an object")
        domain = data.get("domain", "")
        if domain == "com.apple.PosterBoard":
            domain = "AppDomain-com.apple.PosterBoard"
        definition = cls(path, data["title"], data["author"], domain,
                         int(data["format_version"]), data.get("min_version"), data.get("max_version"))
        return definition, data
