import os
import uuid
import zipfile
from shutil import rmtree
from tempfile import TemporaryDirectory
from typing import Optional

from PySide6 import QtCore

from src.devicemanagement.constants import Version
from src.exceptions.posterboard_exceptions import PBTemplateException

from .community_tweaks import (
    MAX_SOURCE_BYTES,
    MAX_TOTAL_SOURCE_BYTES,
    CommunityTweak,
    parse_tweaks,
)
from .template_definition import TemplateDefinition
from .template_options import (
    OptionType,
    PickerOption,
    RemoveOption,
    ReplaceOption,
    SetOption,
    TemplateOption,
)
from .tendie_file import TendieFile

CURRENT_FORMAT = 3

class TemplateFile(TendieFile):
    options: list[TemplateOption]
    tweaks: list[CommunityTweak] # switchable tweaks (format 3), see community_tweaks.py
    json_path: str
    tmp_dir: str = None

    author: str = "" # author of template
    domain: str = "" # domain to restore to
    description: Optional[str] = None # description to go under the file

    change_bundle_id: bool = False # whether or not the user can change the bundle id
    bundle_id: str = None # bundle id of the app if changeable

    min_version: Optional[str] = None # minimum supported iOS version
    max_version: Optional[str] = None # maximum supported iOS version

    resources: list[str] # populated per selection in __init__
    previews: dict[str, str] # populated per selection in __init__
    preview_layout: str = "horizontal" # the direction to lay out the preview images

    banner_text: Optional[str] = None # text to go as a banner
    banner_stylesheet: Optional[str] = None # style sheet of the banner
    format_version: int = CURRENT_FORMAT # format version of config

    def __init__(self, path: str, device_version: str = None):
        super().__init__(path=path)
        self.options = []
        self.tweaks = []
        self.resources = []
        self.previews = {}
        self.json_path = None

        # find the config.json file
        with zipfile.ZipFile(path, mode="r") as archive:
            self.definition, data = TemplateDefinition.read(archive)
            self.json_path = self.definition.config_path if self.definition else None
            if self.json_path is not None:
                # load the options; a template with only community tweaks
                # needs neither options nor a domain
                if 'options' not in data and 'tweaks' not in data:
                    raise PBTemplateException(path, QtCore.QCoreApplication.tr("No options were found in the config. Make sure that it is in the correct format."))
                if 'domain' not in data and 'tweaks' not in data:
                    raise PBTemplateException(path, QtCore.QCoreApplication.tr("This config does not have a valid domain!"))
                self.domain = data.get('domain', "")
                # add backwards compatibility for my mistake in the v5.2 betas
                if self.domain == "com.apple.PosterBoard":
                    self.domain = "AppDomain-com.apple.PosterBoard"
                self.format_version = int(data['format_version'])
                if self.format_version > CURRENT_FORMAT:
                    raise PBTemplateException(path, QtCore.QCoreApplication.tr("This config requires a newer version of Nugget."))
                self.name = data['title']
                self.author = data['author']
                if 'description' in data:
                    self.description = data['description']

                if 'min_version' in data:
                    self.min_version = data['min_version']
                    # check the device version
                    # TODO: need to make this check also happen when connected device is updated
                    if device_version and Version(self.min_version) > Version(device_version):
                        raise PBTemplateException(path, QtCore.QCoreApplication.tr("This template requires iOS {0}.\nYour iOS version (iOS {1}) is too outdated!").format(self.min_version, device_version))
                if 'max_version' in data:
                    self.max_version = data['max_version']
                    if device_version and Version(self.max_version) < Version(device_version):
                        raise PBTemplateException(path, QtCore.QCoreApplication.tr("This template requires iOS {0}.\nYour iOS version (iOS {1}) is too new!").format(self.max_version, device_version))

                # load the previews
                prevs = []
                if 'previews' in data:
                    prevs = data['previews']
                    if 'preview_layout' in data:
                        self.preview_layout = data['preview_layout']
                # load the banner
                if 'banner_text' in data:
                    self.banner_text = data['banner_text']
                    if 'banner_stylesheet' in data:
                        self.banner_stylesheet = data['banner_stylesheet']
                # load the resources
                if 'resources' in data:
                    self.resources = data['resources']
                    # open the resources and put them in temp files
                    rcs_path = self.json_path.removesuffix("config.json")
                    from .package_reader import PackageReader
                    reader = PackageReader(archive)
                    for rc_path in reader.matches(self.resources, rcs_path):
                        if self.tmp_dir is None:
                            self.tmp_dir = TemporaryDirectory()
                        rc_full_path = reader.extract_resource(rc_path, self.tmp_dir.name)
                        if rc_full_path is None:
                            continue
                        clean_path = rc_path.replace(rcs_path, "")
                        if self.banner_stylesheet is not None:
                            self.banner_stylesheet = self.banner_stylesheet.replace(
                                f"url({clean_path})", f"url({rc_full_path})")
                        if clean_path in prevs:
                            self.previews[clean_path] = rc_full_path

                if 'tweaks' in data:
                    if self.format_version < 3:
                        raise PBTemplateException(path, QtCore.QCoreApplication.tr("Templates with tweaks need \"format_version\": \"3\"."))
                    self.tweaks = parse_tweaks(data['tweaks'], self._source_reader(archive))
                    if not self.domain and self.has_container(archive):
                        raise PBTemplateException(path, QtCore.QCoreApplication.tr("This config does not have a valid domain!"))

                for option in data.get('options', []):
                    opt_type = OptionType[option['type']]
                    if opt_type == OptionType.replace:
                        self.options.append(ReplaceOption(data=option))
                    elif opt_type == OptionType.remove:
                        self.options.append(RemoveOption(data=option))
                    elif opt_type == OptionType.set:
                        self.options.append(SetOption(data=option))
                    elif opt_type == OptionType.picker:
                        self.options.append(PickerOption(data=option))
                    elif opt_type == OptionType.bundle_id:
                        self.change_bundle_id = True
                        self.bundle_id = self.domain.removeprefix("AppDomain-") # set default value to the bundle id in the domain
                    else:
                        raise PBTemplateException(path, QtCore.QCoreApplication.tr("Invalid option type in template"))
            else:
                raise PBTemplateException(path, QtCore.QCoreApplication.tr("No config.json found in file!"))
    
    def _source_reader(self, archive: zipfile.ZipFile):
        base = self.json_path.removesuffix("config.json")
        names = set(archive.namelist())
        total = [0]

        def read(relative: str) -> bytes:
            name = base + relative
            if name not in names:
                raise PBTemplateException(self.path, QtCore.QCoreApplication.tr("Missing file in template: {0}").format(relative))
            size = archive.getinfo(name).file_size
            total[0] += size
            if size > MAX_SOURCE_BYTES or total[0] > MAX_TOTAL_SOURCE_BYTES:
                raise PBTemplateException(self.path, QtCore.QCoreApplication.tr("Template files are too large."))
            return archive.read(name)
        return read

    def has_container(self, archive: zipfile.ZipFile = None) -> bool:
        if archive is None:
            with zipfile.ZipFile(self.path, mode="r") as opened:
                return self.has_container(opened)
        return any(part.lower() == "container" for name in archive.namelist() for part in name.split("/")[:-1])

    def clean_files(self):
        if self.tmp_dir != None:
            try:
                rmtree(self.tmp_dir.name)
            except Exception as e:
                print(f"Error when removing temp dir: {str(e)}")

    def extract(self, output_dir: str):
        zip_output = os.path.join(output_dir, str(uuid.uuid4()))
        os.makedirs(zip_output)
        with zipfile.ZipFile(self.path, 'r') as zip_ref:
            zip_ref.extractall(zip_output)

        # apply the options
        parent_path = os.path.join(zip_output, os.path.dirname(self.json_path))
        from src.controllers.patch_session import patch_batch

        from .template_options.set_option import SetOption
        with patch_batch() as patches:
            for option in self.options:
                if not isinstance(option, SetOption):
                    # Delete/rename/replace can change a document previously
                    # edited by a setter. Commit before this ordering barrier.
                    patches.flush()
                option.apply(container_path=parent_path)

        return zip_output

    
    def update_bundle_id(self, new_id: str):
        self.bundle_id = new_id

    def create_ui(self, window, tweak, widgets, templateLayout):
        from src.gui.template_editor import TemplateEditor
        return TemplateEditor(self).create_ui(window, tweak, widgets, templateLayout)

    def create_tweaks_ui(self, window, parent, layout):
        from src.gui.template_editor import TemplateEditor
        return TemplateEditor(self).create_tweaks_ui(window, parent, layout)
