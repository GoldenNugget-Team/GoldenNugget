"""Experimental eligibility payloads from MIT-licensed Project Linwood.

These are opaque NSKeyedArchives, never ordinary preference dictionaries.
"""
import hashlib
from pathlib import Path

from src.controllers.files_handler import get_bundle_files
from src.exceptions.nugget_exception import NuggetException
from src.utils.file_to_restore import FileToRestore

from .tweak_classes import Tweak

DOMAIN = "SysContainerDomain-com.apple.eligibilityd"
RELATIVE_PATH = "Library/Caches/NeverRestore/eligibility_overrides.data"
HASHES = {
    "enable": "4290e93faf86fd4f0d38364d2bb67398d9acb77f637555790c3339ad44f64d17",
    "reset": "f9b394804d478874f40eedcade937ab1d4a73773b4c8ed018ce51fb407a00818",
}


def payload_file(action):
    data = Path(get_bundle_files(f"files/siri_ai/{action}.data")).read_bytes()
    if hashlib.sha256(data).hexdigest() != HASHES[action]:
        raise NuggetException("The bundled Siri AI archive is damaged. Reinstall GoldenNugget.")
    return FileToRestore(contents=data, restore_path=RELATIVE_PATH,
                         domain=DOMAIN, owner=0, group=0)


def require_protective_delivery(files, inject_all):
    if any(f.domain == DOMAIN for f in files) and not inject_all:
        raise NuggetException(
            "Siri AI overrides require a prepared, unencrypted protective backup. "
            "Enable protective backup, disable local backup encryption in Finder/iTunes, "
            "and remove protective/sparse restore environment overrides before retrying.")


class SiriAITweak(Tweak):
    def __init__(self, action="enable"):
        super().__init__(key="SiriAI", owner=0, group=0)
        self.action = action

    def apply_tweak(self, files_to_restore, version, model):
        if not self.enabled:
            return
        from src.devicemanagement.constants import Version
        from src.devicemanagement.device_capabilities import has_apple_intelligence
        try:
            supported_version = Version("27") <= Version(version) < Version("28")
        except (ValueError, TypeError):
            supported_version = False
        supported_model = (model or "").startswith("iPhone") and (
            self.action == "reset" or has_apple_intelligence(model))
        if not supported_version or not supported_model:
            raise NuggetException(
                "Siri AI overrides require an iPhone 15 Pro or later on iOS 27.x. "
                "Reset is available on all iPhones running iOS 27.x. "
                "Project Linwood verified iPhone 16 Pro, build 24A437; other devices and builds are untested.")
        files_to_restore.append(payload_file(self.action))
