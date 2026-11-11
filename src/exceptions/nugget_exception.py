from typing import Optional


class NuggetException(Exception):
    def __init__(self, message: str, detailed_text: Optional[str] = None):
        self.message = message
        self.detailed_text = detailed_text
        super().__init__(self.message)
        
    def __str__(self):
        return self.message

class BackupStorageError(NuggetException):
    def __init__(self, message: str, location: str):
        super().__init__(message)
        self.location = location


class BackupDiskSpaceError(NuggetException):
    """The computer's backup destination cannot satisfy a backup space check."""


class PosterBoardBackupEncryptionError(NuggetException):
    """The PosterBoard reader cannot extract encrypted backup payloads."""
