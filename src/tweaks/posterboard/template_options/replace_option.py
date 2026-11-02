from src.controllers.archive_safety import package_matches
from . import TemplateOption

from src.exceptions.nugget_exception import NuggetException
from src.utils.i18n import QCoreApplication

import os
from typing import Optional


class ReplaceOption(TemplateOption):
    allowed_files: str  # Qt filter string, ex. "Image Files (*.png)"
    button_label: str = "Import"
    required: bool = False
    value: Optional[str] = None  # path of file selected by user

    def __init__(self, data: dict):
        super().__init__(data=data)
        self.allowed_files = data['allowed_files']
        if 'button_label' in data:
            self.button_label = data['button_label']
        else:
            self.button_label = f"Import {self.allowed_files}"
        if 'required' in data:
            self.required = data['required']
        self.value = None

    def apply(self, container_path: str):
        if self.value == None:
            if not self.required:
                return
            raise NuggetException(QCoreApplication.tr("Error applying template:\n\nNo selected file for required option") + f" {self.label}")
        contents = None
        in_path = os.path.join(container_path, self.value)
        with open(in_path, "rb") as in_file:
            contents = in_file.read()
        for file in self.files:
            for full_path in package_matches(container_path, file):
                with open(full_path, "wb") as out_file:
                    out_file.write(contents)
        del contents
