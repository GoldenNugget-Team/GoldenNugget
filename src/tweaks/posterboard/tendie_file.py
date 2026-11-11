import os
import uuid
import zipfile

class TendieFile:
    path: str
    name: str
    descriptor_cnt: int
    is_container: bool
    unsafe_container: bool
    loaded: bool
    auto_convert: bool
    legacy_families: list

    def __init__(self, path: str):
        self.path = path
        self.name = os.path.basename(path)
        self.descriptor_cnt = 0
        self.is_container = False
        self.unsafe_container = False
        self.loaded = False
        # Set on import: the user answered the "convert or install as is" prompt
        # for a legacy (pre-iOS 27) package. None means the prompt never ran
        # (iOS 26, or nothing legacy inside) and the apply path decides.
        self.auto_convert: "bool | None" = None
        # Legacy (pre-iOS 27) wallpaper families found in the archive, detected
        # once on import so the tendies card can show the Convert switch without
        # re-reading the zip. Empty means the package needs no conversion.
        self.legacy_families: "list[str]" = []

        # read the contents
        with zipfile.ZipFile(path, mode="r") as archive:
            from src.controllers.archive_safety import checked_members
            checked_members(archive)
            for option in archive.namelist():
                if "__macosx/" in option.lower():
                    continue
                if "container" in option.lower():
                    self.is_container = True
                    # check for the unsafe file that requires prb reset
                    if "PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3" in option:
                        self.unsafe_container = True
                if "descriptor/" in option.lower():
                    item = option.lower().split("descriptor/")[1]
                    if item.count('/') == 1 and item.endswith('/'):
                        self.descriptor_cnt += 1
                elif "descriptors/" in option.lower():
                    item = option.lower().split("descriptors/")[1]
                    if item.count('/') == 1 and item.endswith('/'):
                        self.descriptor_cnt += 1

    def get_icon(self):
        if self.is_container:
            # container
            return ":/icon/shippingbox.svg"
        elif self.descriptor_cnt == 1:
            # single descriptor
            return ":/icon/photo.svg"
        else:
            # multiple descriptors
            return ":/icon/photo-stack.svg"
        
    def extract(self, output_dir: str):
        zip_output = os.path.join(output_dir, str(uuid.uuid4()))
        os.makedirs(zip_output)
        with zipfile.ZipFile(self.path, 'r') as zip_ref:
            # Re-check at extract time: the archive could have been swapped on
            # disk between the import check and this call.
            from src.controllers.archive_safety import checked_members
            checked_members(zip_ref)
            zip_ref.extractall(zip_output)
        return zip_output
