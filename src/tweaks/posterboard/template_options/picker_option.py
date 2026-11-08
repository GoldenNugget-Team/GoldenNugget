import os
from shutil import move, rmtree
from typing import Optional

from src.controllers.archive_safety import package_path, safe_member

from . import TemplateOption


class PickerElement:
    label: str  # label to show for the picker
    files: list[str]  # list of files to include with the picker
    associated_preview: Optional[str] = None
    # Attached by the GUI editor when the element maps to a preview label.
    preview_lbl: object = None

    def __init__(self, option_data: dict):
        self.files = []
        self.label = option_data['label']
        if 'files' in option_data:
            self.files = option_data['files']
            if not isinstance(self.files, list) or any(
                    not isinstance(name, str) or not safe_member(name) for name in self.files):
                raise ValueError('Unsafe picker file paths')
        if 'associated_preview' in option_data:
            self.associated_preview = option_data['associated_preview']
        self.preview_lbl = None


class PickerOption(TemplateOption):
    options: list[PickerElement]  # list of elements inside the picker
    allow_multiple_selection: bool = False  # allow choosing multiple options
    rename: bool = False  # whether or not to rename the chosen files (allow_multiple_selection must be False)
    names: list[str]  # list of names to rename to

    selection: int | list[str]  # chosen user selection
    default_val: int | list[int]  # default index or indices

    def __init__(self, data: dict):
        super().__init__(data=data)
        # get the list of options
        self.options = []
        self.names = []
        opts = data['options']
        for opt in opts:
            self.options.append(PickerElement(opt))

        # add the other options
        if 'allow_multiple_selection' in data:
            self.allow_multiple_selection = data['allow_multiple_selection']
        if not self.allow_multiple_selection:
            self.selection = 0
            if 'rename' in data:
                self.rename = data['rename']
                if self.rename:
                    self.names = data['names']  # only require if rename is true
                    if not isinstance(self.names, list) or any(
                            not isinstance(name, str) or not safe_member(name) for name in self.names):
                        raise ValueError('Unsafe picker destination paths')
                    # apply() renames files[i] -> names[i] for the chosen option,
                    # so an option may carry fewer files (e.g. a "None" choice)
                    if any(len(opt.files) > len(self.names) for opt in self.options):
                        raise ValueError('Picker rename needs a name for each option’s files')
        # default value(s)
        self.default_val = data.get('default_value', data.get(
            'default_values', [] if self.allow_multiple_selection else 0))
        indices = self.default_val if self.allow_multiple_selection else [self.default_val]
        if not isinstance(indices, list) or any(
                type(index) is not int or not 0 <= index < len(self.options)
                for index in indices):
            raise ValueError('Picker defaults must reference existing options')
        self.selection = ([self.options[index].label for index in indices]
                          if self.allow_multiple_selection else self.default_val)

    def onPickerUpdate(self, selection):
        """Record a selection coming from the GUI (index or list of labels)."""
        self.selection = selection

    def apply(self, container_path: str):
        # get the list of files
        sel_options: list[PickerElement] = []
        if self.allow_multiple_selection:
            for opt in self.options:
                if opt.label in self.selection:
                    sel_options.append(opt)
        else:
            sel_options.append(self.options[self.selection])
        # delete the files that are not in use
        for opt in self.options:
            if opt not in sel_options:
                for file in opt.files:
                    # delete files or directories
                    path = package_path(container_path, file)
                    if os.path.isdir(path):
                        rmtree(path=path, ignore_errors=True)
                    else:
                        os.remove(path=path)
        # rename the files if needed
        if self.rename:
            for i in range(len(self.options[self.selection].files)):
                # rename files or directories
                old_path = package_path(container_path, self.options[self.selection].files[i])
                new_path = package_path(container_path, self.names[i])
                if os.path.isdir(old_path):
                    # rename whole directory
                    move(old_path, new_path)
                else:
                    os.rename(old_path, new_path)
