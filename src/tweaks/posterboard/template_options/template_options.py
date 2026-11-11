from dataclasses import dataclass
from enum import Enum
from typing import Optional

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from src.controllers.archive_safety import safe_member


class OptionType(Enum):
    replace = "replace"
    remove = "remove"
    set = "set"
    picker = "picker"
    bundle_id = "bundle_id"

@dataclass
class TemplateOption:
    type: OptionType
    label: str
    files: list[str]
    associated_preview: Optional[str]
    preview_lbl: Optional[QLabel]

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

    def add_potential_preview_lbls(self, lbls: dict[str, QLabel]):
        if self.associated_preview != None and self.associated_preview in lbls:
            self.preview_lbl = lbls[self.associated_preview]
    def update_preview(self):
        pass

    def create_interface(self, options_widget: QWidget, options_layout: QVBoxLayout):
        raise NotImplementedError

    def apply(self, container_path: str):
        raise NotImplementedError