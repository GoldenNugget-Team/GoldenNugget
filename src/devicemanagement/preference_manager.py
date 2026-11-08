from os import makedirs, path
from os import remove as rmfile
from shutil import copyfile
from typing import Optional

from src.tweaks.posterboard.pb_config_item import PBConfigItem
from src.utils.paths import app_data_dir
from src.utils.settings import Settings


class PreferenceManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.auto_reboot = True
        self.disable_tendies_limit = False
        self.auto_refresh_posterboard = True
        self.use_backup_cache = True
        self.use_encrypted_backup = False
        self.use_afc_media = True
        self.skip_setup = True
        self.supervised = False
        self.organization_name = ""
        # Write the "AutoSave" preset on every tweak change and load it back on
        # startup. Turning it off stops both halves; the preset file itself is
        # left alone so an existing one can still be loaded by hand.
        self.tweak_autosave = True

    # PosterBoard Configuration Database Saving
    def get_pbconfigs_prefs() -> Settings:
        return Settings("PB Configs")
    def get_pbconfigs_db_save_path(udid: Optional[str]=None) -> str:
        app_data_path = path.join(str(app_data_dir()), "PB_Saved_Databases")
        if not path.exists(app_data_path):
            makedirs(app_data_path)
        if udid is not None:
            app_data_path = path.join(app_data_path, f'{udid}.sqlite3')
        return app_data_path
    
    def save_pbconfig_file(filepath: str, udid: str):
        pbdb_path = PreferenceManager.get_pbconfigs_db_save_path(udid)
        copyfile(filepath, pbdb_path)
    def save_pbconfig_ids(ids: list[PBConfigItem], udid: str):
        pbc_settings = PreferenceManager.get_pbconfigs_prefs()
        # convert it to serializable data
        serialized_ids: list[dict] = []
        for id in ids:
            serialized_ids.append(id.to_dict())
        pbc_settings.setValue(udid, serialized_ids)

    def remove_pbconfig_data(udid: str):
        pbdb_path = PreferenceManager.get_pbconfigs_db_save_path(udid)
        if path.exists(pbdb_path):
            rmfile(pbdb_path)
            PreferenceManager.remove_pbconfig_ids(udid)
    def remove_pbconfig_ids(udid: str):
        pbc_settings = PreferenceManager.get_pbconfigs_prefs()
        if pbc_settings.contains(udid):
            pbc_settings.remove(udid)

    def has_pbconfig_data(udid: str) -> bool:
        return path.exists(PreferenceManager.get_pbconfigs_db_save_path(udid))

    def get_pbconfig_path(udid: str) -> Optional[str]:
        pbdb_path = PreferenceManager.get_pbconfigs_db_save_path(udid)
        if path.exists(pbdb_path):
            return pbdb_path
        return None
    def get_pbconfig_ids(udid: str) -> list[PBConfigItem]:
        pbc_settings = PreferenceManager.get_pbconfigs_prefs()
        if not pbc_settings.contains(udid):
            return []
        serialized_ids = pbc_settings.value(udid)
        if serialized_ids is None:
            return []
        ids: list[PBConfigItem] = []
        for id in serialized_ids:
            ids.append(PBConfigItem.from_dict(id))
        return ids