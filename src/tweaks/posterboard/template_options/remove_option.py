import os
from shutil import rmtree
from typing import Optional

from src.controllers.archive_safety import package_matches
from src.controllers.xml_handler import delete_xml_value

from . import TemplateOption


class RemoveOption(TemplateOption):
    inverted: bool = False  # if set to true, the files will only be deleted if the checkbox is unchecked
    value: bool = False  # whether or not to delete the file
    identifier: Optional[str] = None  # nuggetId for properties in caml
    use_ca_id: bool = False  # whether or not to use the ca id over nuggetId

    def __init__(self, data: dict):
        super().__init__(data=data)
        if 'inverted' in data:
            self.inverted = data['inverted']
        if 'default_value' in data:
            self.value = data['default_value']
        if 'identifier' in data:
            self.identifier = data['identifier']
        if 'use_ca_id' in data:
            self.use_ca_id = data['use_ca_id']

    def set_option(self, checked: bool):
        self.value = checked

    def is_hidden(self) -> bool:
        """Preview visibility rule (the GUI applies it to the preview label)."""
        return (self.inverted and not self.value) or (not self.inverted and self.value)

    def apply(self, container_path: str):
        if (self.inverted and not self.value) or (not self.inverted and self.value):
            for file in self.files:
                for full_path in package_matches(container_path, file):
                    if self.identifier != None:
                        # delete properties in xml
                        # TODO: make sure it isn't a directory
                        delete_xml_value(file=full_path, id=self.identifier, use_ca_id=self.use_ca_id)
                    else:
                        # delete files or directories
                        if os.path.isdir(full_path):
                            rmtree(path=full_path, ignore_errors=True)
                        else:
                            os.remove(path=full_path)
