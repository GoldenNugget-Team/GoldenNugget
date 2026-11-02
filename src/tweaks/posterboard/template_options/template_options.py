"""Template option model (Qt-free).

The option classes hold *data* and know how to apply it to a template
container. Everything that renders them (widgets, file pickers, colour
dialogs) lives in ``src.gui.template_option_editors`` so presets, the CLI and
the apply path never need a GUI toolkit.
"""

from enum import Enum
from typing import Optional

from src.controllers.archive_safety import safe_member


class OptionType(Enum):
    replace = "replace"
    remove = "remove"
    set = "set"
    picker = "picker"
    bundle_id = "bundle_id"


class TemplateOption:
    type: OptionType
    label: str
    files: list[str]
    associated_preview: Optional[str]
    # Filled in by the GUI editor (``src.gui.template_option_editors``); the
    # backend never touches it and it stays None on headless runs.
    preview_lbl: object = None

    def __init__(self, data: dict):
        self.type = OptionType[data['type']]
        self.label = data['label']
        if self.type == OptionType.picker:
            # picker should not have files
            self.files = []
        else:
            self.files = data['files']
            if not isinstance(self.files, list) or any(
                    not isinstance(name, str) or not safe_member(name) for name in self.files):
                raise ValueError('Unsafe template file paths')
        if 'associated_preview' in data:
            self.associated_preview = data['associated_preview']
        else:
            self.associated_preview = None
        self.preview_lbl = None

    def apply(self, container_path: str):
        raise NotImplementedError
