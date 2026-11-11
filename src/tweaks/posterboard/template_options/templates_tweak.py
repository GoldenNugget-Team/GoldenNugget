import os
import uuid

from PySide6.QtCore import QCoreApplication

from src.utils.file_to_restore import FileToRestore

from ...tweak_classes import Tweak
from .. import community_tweaks
from ..template_file import TemplateFile


class TemplatesTweak(Tweak):
    def __init__(self):
        super().__init__(key=None)
        self.templates: list[TemplateFile] = []

    def uses_domains(self):
        # TODO: figure out which templates use sparse restore
        for template in self.templates:
            if template.domain and not template.domain.startswith("Sparserestore-"):
                return True
            if getattr(template, "tweaks", None):
                return True
        return False
    
    def is_empty(self) -> bool:
        return len(self.templates) == 0

    def add_template(self, file: str, version: str = None):
        new_template = TemplateFile(path=file, device_version=version)
        self.templates.append(new_template)
        return new_template

    def community_writes(self, version: str = None) -> tuple:
        """(plists, files) from the community tweaks of every template.

        See community_tweaks.collect; tweaks that do not support ``version``
        write nothing."""
        return community_tweaks.collect(
            [(template.name, getattr(template, "tweaks", [])) for template in self.templates], version)

    def tweak_states(self) -> list:
        """Community tweak states for presets, one dict per template in order
        (portable presets rewrite template paths, so the index is the key)."""
        return [{tweak.id: tweak.state() for tweak in getattr(template, "tweaks", [])}
                for template in self.templates]

    def restore_tweak_states(self, states: list, paths: list = None):
        """Apply saved states; ``paths`` are the preset's template paths, so
        a template that failed to load does not shift the rest."""
        if not isinstance(states, list):
            return
        by_path = dict(zip(paths, states)) if paths is not None else None
        for index, template in enumerate(self.templates):
            saved = by_path.get(template.path) if by_path is not None else (
                states[index] if index < len(states) else None)
            if not isinstance(saved, dict):
                continue
            for tweak in getattr(template, "tweaks", []):
                tweak.restore_state(saved.get(tweak.id))

    def parse_path_string(self, path: str, old_domain: str, new_domain: str) -> str:
        result_path = path.replace("/hiddendot", "/.").replace("//", "/")
        if old_domain.startswith("AppDomain-"):
            result_path = result_path.replace(old_domain.removeprefix("AppDomain-"), new_domain.removeprefix("AppDomain-"))
        return result_path
        
    def recursive_add(self, old_bundle: str, domain: str,
                      files_to_restore: list[FileToRestore],
                      curr_path: str, restore_path: str = "",
                      isAdding: bool = False
        ):
        if not os.path.isdir(curr_path):
            return
        for folder in sorted(os.listdir(curr_path)):
            if folder.startswith('.') or folder == "__MACOSX":
                continue
            if isAdding:
                # randomize uuid
                # if file then add it, otherwise recursively call again
                if os.path.isfile(os.path.join(curr_path, folder)):
                    try:
                        # update plist ids if needed
                        contents_path = os.path.join(curr_path, folder)
                        # Keep the extracted package alive through apply_tweak's
                        # output_dir; restore reads this payload in bounded chunks.
                        with open(contents_path, "rb"):
                            pass
                        # handle for sparserestore
                        full_path = f"{restore_path}/{folder}"
                        restore_domain = domain
                        if domain.startswith("Sparserestore-"):
                            full_path = f"{domain.removeprefix('Sparserestore-')}{full_path}"
                            restore_domain = None
                        full_path = self.parse_path_string(full_path, old_bundle, domain)
                        files_to_restore.append(FileToRestore(
                            contents=None, contents_path=contents_path,
                            restore_path=full_path,
                            domain=restore_domain
                        ))
                    except OSError as exc:
                        raise OSError(f"Could not read template payload: {contents_path}") from exc
                else:
                    self.recursive_add(old_bundle, domain, files_to_restore, os.path.join(curr_path, folder), f"{restore_path}/{folder}", isAdding)
            else:
                # look for container folder
                if folder.lower() == "container":
                    self.recursive_add(old_bundle, domain, files_to_restore, os.path.join(curr_path, folder), restore_path="/", isAdding=True)
                else:
                    self.recursive_add(old_bundle, domain, files_to_restore, os.path.join(curr_path, folder), isAdding=False)

    def apply_tweak(self,
                    files_to_restore: list[FileToRestore], output_dir: str,
                    templates: list,
                    version: str, force_pb_refresh: bool,
                    update_label=lambda x: None):
        if len(self.templates) == 0:
            return
        update_label("Extracting templates...")
        # extract templates
        for template in self.templates:
            # A preset may be loaded before any device is connected. Check its
            # stored constraints against the actual target before restoring.
            from src.devicemanagement.constants import Version
            if ((template.min_version and Version(version) < Version(template.min_version))
                    or (template.max_version and Version(version) > Version(template.max_version))):
                raise ValueError(QCoreApplication.translate(
                    'Nugget', 'Template {0} does not support iOS {1}.').format(template.name, version))
            # ignore PosterBoard templates since that is handled in PosterBoard tweaks
            # templates with only community tweaks have no files of their own
            if template.domain and template.domain != 'com.apple.PosterBoard' and template.domain != 'AppDomain-com.apple.PosterBoard':
                temp_dir = os.path.join(output_dir, str(uuid.uuid4()))
                os.makedirs(temp_dir)
                template.extract(output_dir=temp_dir)
                domain = template.domain
                if template.change_bundle_id:
                    domain = f"AppDomain-{template.bundle_id}"
                self.recursive_add(old_bundle=template.domain, domain=domain, files_to_restore=files_to_restore, curr_path=temp_dir)
        update_label("Adding other tweaks...")
