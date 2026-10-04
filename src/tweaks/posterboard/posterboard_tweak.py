import os
import uuid
import traceback
import plistlib
from random import randint
from shutil import copytree, rmtree
from PySide6 import QtWidgets
from PySide6.QtCore import QCoreApplication

from ..tweak_classes import Tweak
from . import posterboard_converter
from .tendie_file import TendieFile
from .template_file import TemplateFile
from .pb_config_manager import (
    DB_FILE_NAME, PBConfigManager, create_empty_posterboard_db)
from src.utils.file_to_restore import FileToRestore
from src.controllers.plist_handler import set_plist_value
from src.controllers.files_handler import get_bundle_files
from src.controllers import video_handler
from src.controllers.aar.aar import wrap_in_aar
from src.exceptions.nugget_exception import NuggetException
from src.exceptions.posterboard_exceptions import PBTemplateException
from src.devicemanagement.constants import Version

# PosterKit depth effect: the animated video layer is rendered larger than the
# 390x844 document and pushed off-centre so the tilt parallax has travel.
# 1.0 / 0 produces a dead-centre layer that reads as a flat wallpaper.
VIDEO_DEPTH_SCALE = 1.3
VIDEO_DEPTH_OFFSET_Y = 40


def prompt_legacy_convert(tendie_name: str, families: "list[str]") -> bool:
    """Ask how a legacy (pre-iOS 27) wallpaper should be imported.

    Returns True to convert, False to install the original files untouched.
    Dismissing the dialog (Escape) resolves to "Install as is", so the import is
    never silently converted and never dropped.
    """
    app = QtWidgets.QApplication.instance()
    parent = app.activeWindow() if app is not None else None
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Icon.Question,
                                QCoreApplication.translate("Nugget", "Legacy Wallpaper Format"),
                                QCoreApplication.translate(
                                    "Nugget",
                                    "<b>{0}</b> uses the legacy {1} format.").format(
                                        tendie_name, ", ".join(sorted(set(families)))),
                                parent=parent)
    box.setInformativeText(QCoreApplication.translate(
        "Nugget",
        "iOS 27 only applies the depth effect to wallpapers in the modern format, "
        "so a legacy wallpaper is rewritten on import. Pick "
        "“Install as is” to push the original files untouched instead."))
    convert = box.addButton(
        QCoreApplication.translate("Nugget", "Convert (may break the wallpaper)"),
        QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    as_is = box.addButton(
        QCoreApplication.translate("Nugget", "Install as is"),
        QtWidgets.QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(convert)
    box.exec()
    return box.clickedButton() is convert


class PosterboardTweak(Tweak):
    def __init__(self):
        super().__init__(key=None)
        self.tendies: list[TendieFile] = []
        self.videoThumbnail = None
        self.videoFile = None
        self.loop_video = True
        self.reverse_video = False
        self.use_foreground = False
        # Which declared plane the generated video CAML is written into:
        # "background", "floating" or "foreground". The lock screen clock is
        # composited by the system between the planes, so "floating" is what
        # puts the video in front of it.
        self.video_plane = "background"
        self.use_configs = True  # descriptors apply method is gone (broken on iOS 26+)
        # Rewrite legacy (pre-iOS 27) wallpaper packages to the modern shape on
        # import so PosterKit builds the Depth effect for them. Only descriptors
        # without a published plane are touched; modern packages pass through.
        self.auto_convert_legacy = True
        self.calculationMode = 'linear'
        self.bundle_id = "com.apple.PosterBoard"
        self.resetModes = []
        self.full_reset = False
        self.structure_version = 61
        self.config_manager = PBConfigManager()

    def uses_domains(self):
        return (len(self.tendies) > 0 or self.videoFile != None
                or len(self.resetModes) > 0 or self.full_reset)
    
    def is_empty(self) -> bool:
        return not self.uses_domains()

    def verify_tendie(self, new_tendie: TendieFile, is_template: bool = False) -> bool:
        if new_tendie.descriptor_cnt + self.get_descriptor_count() <= 10:
            if is_template:
                raise Exception(QCoreApplication.tr("Wrong type of file"))
            else:
                self.tendies.append(new_tendie)
            # alert if prb reset is needed
            if new_tendie.unsafe_container:
                detailsBox = QtWidgets.QMessageBox()
                detailsBox.setIcon(QtWidgets.QMessageBox.Critical)
                detailsBox.setWindowTitle(QCoreApplication.tr("Warning"))
                detailsBox.setText(QCoreApplication.tr("NOTE: You may need to reset all wallpapers and then re-apply for this file to work."))
                detailsBox.exec()
            return True
        return False

    def add_tendie(self, file: str, device_version: str = None):
        new_tendie = TendieFile(path=file)
        self._ask_legacy_convert(new_tendie, device_version)
        return self.verify_tendie(new_tendie)

    # iOS 27 only builds the Depth effect for the modern ("Clownfish") layout, so
    # an imported pre-iOS 27 package has to be rewritten for it to gain depth —
    # and the rewrite is best effort (it re-stamps the family, drops external
    # scripts and republishes the planes), so it can change how a wallpaper
    # looks. iOS 26 reads legacy packages as they are: nothing is converted
    # there and the prompt never appears.
    LEGACY_CONVERT_MIN_MAJOR = 27

    def _legacy_convert_supported(self, device_version: str) -> bool:
        if not device_version:
            return False
        try:
            return Version(str(device_version)).major >= self.LEGACY_CONVERT_MIN_MAJOR
        except Exception:
            return False

    def _ask_legacy_convert(self, new_tendie: TendieFile, device_version: str) -> None:
        """Offer "Convert" / "Install as is" once, at import time.

        The answer is stored on the tendie (``auto_convert``) and honoured by
        :meth:`apply_tweak`, which converts each extracted tendie on its own.
        """
        new_tendie.auto_convert = None
        if not self.auto_convert_legacy:
            return
        if not self._legacy_convert_supported(device_version):
            return
        try:
            families = posterboard_converter.legacy_families(new_tendie.path)
        except Exception:
            traceback.print_exc()
            return
        if not families:
            return
        new_tendie.auto_convert = prompt_legacy_convert(new_tendie.name, families)

    def add_template(self, file: str, version: str = None):
        try:
            new_template = TemplateFile(path=file, device_version=version)
            if new_template.domain != "com.apple.PosterBoard":
                raise PBTemplateException(file=file, message="This is not a PosterBoard template. Please import it on the Templates page.")
        except Exception as e:
            print(traceback.format_exc())
            detailsBox = QtWidgets.QMessageBox()
            detailsBox.setIcon(QtWidgets.QMessageBox.Critical)
            detailsBox.setWindowTitle(QCoreApplication.tr("Error"))
            detailsBox.setText(QCoreApplication.tr("Failed to load template") + f" {file}\n\n{str(e)}")
            detailsBox.exec()
            return True
        return self.verify_tendie(new_template, is_template=True)

    def get_descriptor_count(self):
        cnt = 0
        for tendie in self.tendies:
            cnt += tendie.descriptor_cnt
        return cnt

    # MercuryPoster configs keep their own textual descriptor identifier
    # (e.g. "v6x.colorB") that the userInfo.lookIdentifier and the
    # suggestionMetadata reference — rewriting it to a random number breaks
    # the lookup chain. Identifiers are preserved byte-for-byte for it.
    MERCURY_EXTENSION = "com.apple.MercuryPoster"

    @classmethod
    def is_mercury(cls, restore_path: str) -> bool:
        parts = restore_path.split('/')
        return len(parts) > 6 and parts[6] == cls.MERCURY_EXTENSION

    def update_plist_id(self, file_path: str, file_name: str, randomizedID: int):
        if file_name == "com.apple.posterkit.provider.descriptor.identifier":
            return str(randomizedID).encode()
        elif file_name == "com.apple.posterkit.provider.contents.userInfo":
            # recursive=True only ever *replaces* an existing key, and a
            # third-party tendie's userInfo ships WITHOUT
            # `wallpaperRepresentingIdentifier` — so the key must be added, not
            # just overwritten, or WallpaperKit force-unwraps nil and traps
            # (EXC_BREAKPOINT) in makeViewProvider. Keep it a string to match
            # the stock descriptors.
            return set_plist_value(file=os.path.join(file_path, file_name),
                                   key="wallpaperRepresentingIdentifier",
                                   value=str(randomizedID), recursive=False)
        elif file_name.endswith("Wallpaper.plist"):
            return set_plist_value(file=os.path.join(file_path, file_name), key="identifier", value=randomizedID, recursive=False)
        return None


    def recursive_add(self,
                      files_to_restore: list[FileToRestore],
                      curr_path: str, restore_path: str = "",
                      isAdding: bool = False,
                      randomizeUUID: bool = False, randomizedID: int = None
        ):
        if not os.path.isdir(curr_path):
            return
        if isAdding and randomizeUUID and ("ordered-descriptor" in curr_path or "ordered-descriptors" in curr_path):
            # PosterBoard orders wallpapers by wallpaper id in reverse order
            r_id = randint(9999, 99999)
            r_id_list = sorted([r_id + i for i in range(len(os.listdir(curr_path)))], reverse=True)
        counter = 0
        for folder in sorted(os.listdir(curr_path)):
            # `.com.apple.posterkit.provider.contents.configurableOptions.plist`
            # is a legitimate descriptor plist (Apple hides it with a leading
            # dot) that carries `preferredRenderingConfiguration` — the poster
            # editor reads it for depth. Only skip real Finder/archive junk.
            if folder == "__MACOSX" or folder == ".DS_Store" or folder.startswith("._"):
                continue
            if isAdding:
                # randomize uuid
                folder_name = folder
                curr_randomized_id = randomizedID
                if randomizeUUID:
                    if "ordered-descriptor" in curr_path or "ordered-descriptors" in curr_path:
                        folder_name = str(uuid.uuid4()).upper()
                        curr_randomized_id = r_id_list[counter]
                        counter += 1
                    else:
                        folder_name = str(uuid.uuid4()).upper()
                        curr_randomized_id = randint(9999, 99999)
                    # add it to the configuration
                    ext = restore_path.split('/')[6]
                    self.config_manager.add_config(folder_name, ext)
                    # Third-party .tendies usually ship without the
                    # descriptor.identifier sidecar. PosterKit then invents one
                    # that disagrees with userInfo / Wallpaper.plist, and
                    # WallpaperKit traps building the view. Stamp the sidecar so
                    # all three identity fields carry the same randomized id
                    # (see update_plist_id).
                    if (not self.is_mercury(restore_path)
                            and os.path.isdir(os.path.join(curr_path, folder))
                            and not os.path.exists(os.path.join(
                                curr_path, folder,
                                "com.apple.posterkit.provider.descriptor.identifier"))):
                        files_to_restore.append(FileToRestore(
                            contents=str(curr_randomized_id).encode(),
                            restore_path=f"{restore_path}/{folder_name}/"
                                         "com.apple.posterkit.provider.descriptor.identifier",
                            domain=f"AppDomain-{self.bundle_id}"
                        ))
                # if file then add it, otherwise recursively call again
                fullpath = os.path.join(curr_path, folder)
                if os.path.isfile(fullpath):
                    try:
                        # if converting to config and it is a file to be modified, then update it (don't add it here and add them later)
                        if self.config_manager.file_needs_updated(folder):
                            continue
                        # update plist ids if needed
                        new_contents = None
                        contents_path = fullpath
                        # Mercury identifiers are preserved (see is_mercury);
                        # the rewrite below is Marble/Collections-specific.
                        if curr_randomized_id != None and not self.is_mercury(restore_path):
                            new_contents = self.update_plist_id(curr_path, folder, curr_randomized_id)
                            if new_contents != None:
                                contents_path = None
                        files_to_restore.append(FileToRestore(
                            contents=new_contents,
                            contents_path=contents_path,
                            restore_path=f"{restore_path}/{folder_name}".replace("//", "/"),
                            domain=f"AppDomain-{self.bundle_id}"
                        ))
                    except IOError:
                        print(f"Failed to open file: {folder}") # TODO: Add QDebug equivalent
                else:
                    # add config files if needed
                    if curr_path.endswith("versions") and "descriptor" in curr_path:
                        self.config_manager.cache_config_files()
                        for config_file in self.config_manager.config_files:
                            files_to_restore.append(FileToRestore(
                                contents=None,
                                contents_path=os.path.join(self.config_manager.config_files_folder, config_file),
                                restore_path=f"{restore_path}/{folder_name}/{config_file}",
                                domain=f"AppDomain-{self.bundle_id}"
                            ))
                    self.recursive_add(files_to_restore, fullpath, f"{restore_path}/{folder_name}", isAdding, randomizedID=curr_randomized_id)
            else:
                # look for container folder
                name = folder.lower()
                if name == "container":
                    # A container is a full data-store snapshot: walk it (non-adding)
                    # so the descriptor folders inside get routed to configurations,
                    # exactly like a custom .tendie, and registered in the DB.
                    self.recursive_add(files_to_restore, os.path.join(curr_path, folder), restore_path="/", isAdding=False)
                    return
                elif "descriptor" in name:
                    # get the extension
                    parent = os.path.basename(curr_path)
                    if parent.startswith("com.apple."):
                        # container: the provider extension is the descriptor's parent folder
                        ext = parent
                    elif "video" in name or "photos" in name:
                        ext = "com.apple.PhotosUIPrivate.PhotosPosterProvider"
                    elif "mercury" in name:
                        ext = "com.apple.MercuryPoster"
                    else:
                        ext = "com.apple.WallpaperKit.CollectionsPoster"
                    wpfolder = "configurations"
                    self.recursive_add(
                        files_to_restore,
                        os.path.join(curr_path, folder),
                        restore_path=f"/Library/Application Support/PRBPosterExtensionDataStore/{self.structure_version}/Extensions/{ext}/{wpfolder}",
                        isAdding=True,
                        randomizeUUID=True
                    )
                else:
                    self.recursive_add(files_to_restore, os.path.join(curr_path, folder), isAdding=False)

    def create_live_photo_files(self, output_dir: str):
        if self.videoFile != None and not self.loop_video:
            source_dir = get_bundle_files("files/posterboard/1F20C883-EA98-4CCE-9923-0C9A01359721")
            video_output_dir = os.path.join(output_dir, "video-descriptor", "1F20C883-EA98-4CCE-9923-0C9A01359721")
            copytree(source_dir, video_output_dir, dirs_exist_ok=True)
            contents_path = os.path.join(video_output_dir, "versions", "0", "contents", "0EFB6A0F-7052-4D24-8859-AB22BADF2E93")

            # convert the video first
            video_contents = None
            if self.videoFile.endswith('.mov'):
                # no need to convert
                with open(self.videoFile, "rb") as vid:
                    video_contents = vid.read()
            else:
                # convert to mov
                video_contents = video_handler.convert_to_mov(input_file=self.videoFile)
            # now replace video
            with open(os.path.join(contents_path, "output.layerStack", "portrait-layer_settling-video.MOV"), "wb") as overriding:
                overriding.write(video_contents)
            aar_path = os.path.join(contents_path, "input.segmentation", "segmentation.data.aar")
            wrap_in_aar(get_bundle_files("files/posterboard/contents.plist"), video_contents, aar_path)

            # replace the heic files
            if self.videoThumbnail != None:
                del video_contents
                with open(self.videoThumbnail, "rb") as thumb:
                    thumb_contents = thumb.read()
            else:
                raise NuggetException("No thumbnail heic selected!")
            to_override = ["input.segmentation/asset.resource/Adjusted.HEIC", "input.segmentation/asset.resource/proxy.heic", "output.layerStack/portrait-layer_background.HEIC"]
            for file in to_override:
                with open(os.path.join(contents_path, *(file.split("/"))), "wb") as overriding:
                    overriding.write(thumb_contents)
            del thumb_contents

    def create_video_loop_files(self, output_dir: str, update_label=lambda x: None):
        if self.videoFile and self.loop_video:
            source_dir = get_bundle_files("files/posterboard/VideoCAML")
            video_output_dir = os.path.join(output_dir, "descriptor", "VideoCAML")
            copytree(source_dir, video_output_dir, dirs_exist_ok=True)
            contents_path = os.path.join(video_output_dir, "versions", "1", "contents", "9183.Custom-390w-844h@3x~iphone.wallpaper")
            if self.use_foreground:
                # Legacy branch: swap the floating layer over the background
                # one. Both names used to be left on the old iPad screen class
                # ("810w-1080h@2x~ipad") while the template ships the iPhone one,
                # so this died with FileNotFoundError on a layer that does not
                # exist. Prefer video_plane instead.
                bg_path = os.path.join(contents_path, "9183.Custom_Background-390w-844h@3x~iphone.ca")
                contents_path = os.path.join(contents_path, "9183.Custom_Floating-390w-844h@3x~iphone.ca")
                rmtree(bg_path, ignore_errors=True)
                os.rename(contents_path, bg_path)
                layer_name = "Floating"
            else:
                # Which of the three declared planes the video is written into.
                # PosterKit composites the lock screen clock *between* the
                # planes, so a video parked in the background plane leaves the
                # clock painted on top of it. Putting it in the floating plane
                # makes the video the near layer, which is what lets it occlude
                # the clock (the depth/occlusion pass has no idea the system
                # clock belongs behind the wallpaper).
                plane = (self.video_plane or "background").lower()
                suffix = {
                    "background": "9183.Custom_Background-390w-844h@3x~iphone.ca",
                    "floating": "9183.Custom_Floating-390w-844h@3x~iphone.ca",
                    "foreground": "9183.Custom_Foreground-390w-844h@3x~iphone.ca",
                }.get(plane)
                if suffix is None:
                    raise PBTemplateException(
                        f"Unknown video_plane {self.video_plane!r}; expected "
                        "background, floating or foreground")
                contents_path = os.path.join(contents_path, suffix)
                layer_name = {
                    "background": "Background",
                    "floating": "Floating",
                    "foreground": "Foreground",
                }[plane]
            print(f"path at {contents_path}, creating caml")
            # Depth: PosterKit parallaxes planes whose bounds/origin differ from
            # the 390x844 document (The Odyssey's spartanbg is 1852x4104 at
            # y=545.9). A layer at scale 1.0 dead-centre has nothing to move
            # against, so the video is rendered oversized and pushed off-centre
            # to give the tilt/parallax effect some travel.
            video_handler.create_caml(
                video_path=self.videoFile, output_file=contents_path,
                auto_reverses=self.reverse_video, calculationMode=self.calculationMode,
                update_label=update_label,
                bounds_scale=VIDEO_DEPTH_SCALE, offset_y=VIDEO_DEPTH_OFFSET_Y,
                layer_name=layer_name,
            )
            
            

    def apply_tweak(self,
                    files_to_restore: list[FileToRestore], output_dir: str,
                    templates: list[TemplateFile],
                    version: str, force_pb_refresh: bool,
                    update_label=lambda x: None):
        # find the directory
        # The on-device store structure version is learned from the fetched
        # DB's manifest path (61, 62, ... vary between iOS releases) by
        # extract_posterboard_db and carried on the config manager; fall back
        # to 61 (the oldest supported layout) when no DB was fetched.
        self.structure_version = self.config_manager.structure_version if (
            getattr(self.config_manager, "structure_version", 0)) else 61
        if self.full_reset:
            # Full reset: wipe the entire PosterBoard container and replace
            # the on-device sqlite with an empty (schema-only) database.
            update_label(QCoreApplication.tr("Resetting PosterBoard..."))
            # Zero out every wallpaper provider under Extensions plus the
            # gallery cache. The zero-files keep the /61 folder a real
            # directory, so the sqlite injection below lands cleanly.
            wipe_paths = [
                f"/{self.structure_version}/Extensions",
                f"/{self.structure_version}/GalleryCache",
                f"/{self.structure_version}/Backups",
            ]
            for wp in wipe_paths:
                files_to_restore.append(FileToRestore(
                    contents=b"",
                    restore_path=f"/Library/Application Support/PRBPosterExtensionDataStore{wp}",
                    domain=f"AppDomain-{self.bundle_id}"
                ))
            # fresh empty database
            empty_db = create_empty_posterboard_db(
                os.path.join(output_dir, "empty_posterboard.sqlite3"))
            db_path = (f"/Library/Application Support/PRBPosterExtensionDataStore/"
                       f"{self.structure_version}/{DB_FILE_NAME}")
            files_to_restore.append(FileToRestore(
                contents=None,
                contents_path=empty_db,
                restore_path=db_path,
                domain=f"AppDomain-{self.bundle_id}"
            ))
            # ship 0-byte -wal/-shm so iOS starts the store clean (WAL dead-zone)
            for wal_suffix in ("-wal", "-shm"):
                files_to_restore.append(FileToRestore(
                    contents=b"",
                    restore_path=db_path + wal_suffix,
                    domain=f"AppDomain-{self.bundle_id}"
                ))
            # reset the PosterBoard preferences on a full reset
            plist = {
                "PBF_LOCALE_DID_CHANGE": False,
                "PBF_RESET_FILE_PROTECTIONS": True
            }
            if Version(version) >= Version("26.4"):
                plist["PersistedPosterContainerBundleIdentifiers"] = [
                    "com.apple.Posters.CollectionsPosterApp"
                ]
                plist["CompletedPosterBundleIdentifierMigrations"] = [
                    "com.apple.Posters.UnityPosterApp.ExtragalacticPoster",
                    "com.apple.Posters.WeatherPosterApp.WeatherPoster",
                    "com.apple.Posters.UnityPosterApp.Unity2025Poster",
                    "com.apple.Posters.UnityPosterApp.UnityPosterExtension",
                    "com.apple.Posters.UnityPosterApp.RhizomePoster",
                    "com.apple.Posters.KaleidoscopePosterApp.KaleidoscopePoster"
                ]
            files_to_restore.append(FileToRestore(
                contents=plistlib.dumps(plist, fmt=plistlib.PlistFormat.FMT_BINARY),
                restore_path="/Library/Preferences/com.apple.PosterBoard.unprotectedUserDefaults.plist",
                domain=f"AppDomain-{self.bundle_id}"
            ))
            return
        elif len(self.resetModes) > 0:
            # null out the folder
            file_paths = []
            for mode in self.resetModes:
                if mode == "Collections":
                    # resetting collections
                    file_paths.append(f"/{self.structure_version}/Extensions/com.apple.WallpaperKit.CollectionsPoster/descriptors")
                    file_paths.append(f"/{self.structure_version}/Extensions/com.apple.MercuryPoster/descriptors")
                elif mode == "Suggested Photos":
                    # resetting suggested photos
                    file_paths.append(f"/{self.structure_version}/Extensions/com.apple.PhotosUIPrivate.PhotosPosterProvider/descriptors")
                elif mode == "Gallery Cache":
                    # resetting gallery cache
                    file_paths.append(f"/{self.structure_version}/GalleryCache")
                else:
                    # resetting prb extensions
                    file_paths.append("")
            for file_path in file_paths:
                files_to_restore.append(FileToRestore(
                    contents=b"",
                    restore_path=f"/Library/Application Support/PRBPosterExtensionDataStore{file_path}",
                    domain=f"AppDomain-{self.bundle_id}"
                ))
            return
        elif len(self.tendies) == 0 and len(templates) == 0 and self.videoFile == None:
            return
        update_label(QCoreApplication.tr("Generating PosterBoard Video..."))
        self.create_live_photo_files(output_dir)
        self.create_video_loop_files(output_dir, update_label=update_label)
        # extract tendies
        # Each tendie is extracted into its own folder so the legacy conversion
        # (and the skeleton rename) can honour the per-tendie "convert / install
        # as is" answer captured at import time.
        extracted: list[tuple[str, bool]] = []
        for tendie in self.tendies:
            update_label(QCoreApplication.tr("Extracting tendie {0}...").format(tendie.name))
            extracted.append((tendie.extract(output_dir=output_dir),
                              getattr(tendie, "auto_convert", True) is not False))
        # extract templates
        for template in templates:
            if template.domain == 'com.apple.PosterBoard' or template.domain == 'AppDomain-com.apple.PosterBoard':
                update_label(QCoreApplication.tr("Configuring template {0}...").format(template.name))
                extracted.append((template.extract(output_dir=output_dir), True))
        # add the files
        update_label(QCoreApplication.tr("Adding tendies..."))
        if self.auto_convert_legacy:
            try:
                for root, convert in extracted:
                    if not convert:
                        print(f"Left {os.path.basename(root)} in its original "
                              f"legacy format (installed as is)")
                        continue
                    for item in posterboard_converter.convert_tree(root):
                        print(f"Converted legacy wallpaper {item.get('wallpaper')} to "
                              f"{item.get('screen')} (planes={item.get('planes')})")
                    # Rename the converted bundles to the stock Clownfish file layout
                    # (<assetId>.<Family>-<class>.wallpaper). WallpaperKit builds the
                    # lock-screen view from the on-disk name and traps in
                    # WKPlatformPackageView when a converted tendie keeps its
                    # original name (e.g. Windows_11.wallpaper / background.ca).
                    for item in posterboard_converter.rename_descriptors_to_skeleton(root):
                        print(f"Renamed wallpaper to {item.get('wallpaper')} "
                              f"(planes={item.get('planes')})")
            except Exception:
                print(traceback.format_exc())
        self.config_manager.start_staging()
        self.recursive_add(files_to_restore, curr_path=output_dir)
        staged_db_path = self.config_manager.update_sqlite()
        db_path = f"/Library/Application Support/PRBPosterExtensionDataStore/{self.structure_version}/PBFPosterExtensionDataStoreSQLiteDatabase.sqlite3"
        files_to_restore.append(FileToRestore(
            contents=None,
            contents_path=staged_db_path,
            restore_path=db_path,
            domain=f"AppDomain-{self.bundle_id}"
        ))
        # The on-device database runs in WAL mode. Replacing only the main
        # file while a stale -wal/-shm stays behind makes the next open replay
        # old frames over the fresh database -> "database disk image is
        # malformed" / random PosterBoard breakage. Ship 0-byte companions so
        # iOS starts the store clean.
        for wal_suffix in ("-wal", "-shm"):
            files_to_restore.append(FileToRestore(
                contents=b"",
                restore_path=db_path + wal_suffix,
                domain=f"AppDomain-{self.bundle_id}"
            ))
        # add the force refresh
        if force_pb_refresh:
            plist = {
                "PBF_LOCALE_DID_CHANGE": False,
                "PBF_RESET_FILE_PROTECTIONS": True
            }
            if Version(version) >= Version("26.4"):
                plist["PersistedPosterContainerBundleIdentifiers"] = [
                    "com.apple.Posters.CollectionsPosterApp"
                ]
                plist["CompletedPosterBundleIdentifierMigrations"] = [
                    "com.apple.Posters.UnityPosterApp.ExtragalacticPoster",
                    "com.apple.Posters.WeatherPosterApp.WeatherPoster",
                    "com.apple.Posters.UnityPosterApp.Unity2025Poster",
                    "com.apple.Posters.UnityPosterApp.UnityPosterExtension",
                    "com.apple.Posters.UnityPosterApp.RhizomePoster",
                    "com.apple.Posters.KaleidoscopePosterApp.KaleidoscopePoster"
                ]
            files_to_restore.append(FileToRestore(
                contents=plistlib.dumps(plist, fmt=plistlib.PlistFormat.FMT_BINARY),
                restore_path="/Library/Preferences/com.apple.PosterBoard.unprotectedUserDefaults.plist",
                domain=f"AppDomain-{self.bundle_id}"
            ))
        update_label(QCoreApplication.tr("Adding other tweaks..."))
