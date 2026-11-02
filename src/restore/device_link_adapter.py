"""Idempotent compatibility adapters for the pinned mobilebackup2 protocol."""
import asyncio
import os
import shutil
import sys
from pymobiledevice3.exceptions import NotEnoughDiskSpaceError, PyMobileDevice3Exception
from src.utils.log_util import log_info, log_warn, log_debug

# How long the device may stay completely silent in the middle of a transfer
# before the backup is abandoned. A healthy DeviceLink answers within seconds
# (the penalty charge is per message or per file); a silent device leaves the
# host blocked in ``readexactly`` forever, which is exactly how an apply used
# to hang on "Device data… 46%" with no error and a log that simply stopped
# (issue #81). Generous on purpose: one huge payload (a multi-GB ProRes video)
# is read with a single large ``readexactly``, so this is a silence budget,
# not a file budget.
DEFAULT_RECV_TIMEOUT_SECS = 900.0
RECV_TIMEOUT_ENV = "GOLDENNUGGET_BACKUP_STALL_SECS"


def recv_timeout_secs() -> float:
    """Silence budget for one DeviceLink read, overridable for slow setups."""
    try:
        value = float(os.environ.get(RECV_TIMEOUT_ENV, DEFAULT_RECV_TIMEOUT_SECS))
    except ValueError:
        return DEFAULT_RECV_TIMEOUT_SECS
    return value if value > 0 else DEFAULT_RECV_TIMEOUT_SECS


class DeviceLinkStalled(PyMobileDevice3Exception):
    """The device stopped sending data mid-transfer.

    Raised instead of blocking forever on a read that will never complete.
    Deliberately worded without the connection-error keywords
    (``connection``/``terminated``/``incomplete``) so ``is_connection_error``
    does not mistake a dead transfer for a transient link flap and silently
    replay the whole backup.
    """


def install_recv_timeout(timeout_secs: float = None) -> None:
    """Bound every DeviceLink read so a silent device cannot hang an apply.

    ``DeviceLink._recvall`` is the single choke point for everything the device
    sends (plists, file chunks, status codes). Wrapping it turns "the device
    never answers" into a ``DeviceLinkStalled`` after the silence budget,
    which the apply reports as an actionable error and the user can retry --
    instead of a progress bar frozen at the last percentage with nothing in
    the log.
    """
    timeout = recv_timeout_secs() if timeout_secs is None else timeout_secs
    try:
        from pymobiledevice3.services.device_link import DeviceLink
    except Exception as e:  # pragma: no cover - defensive
        log_debug(f"DeviceLink recv-timeout hook not installed: {e}")
        return
    if getattr(DeviceLink, "_gn_recv_timeout_installed", False):
        return
    original_recvall = DeviceLink._recvall

    async def _recvall(self, size):
        budget = getattr(self, "_gn_recv_timeout", None) or timeout
        try:
            return await asyncio.wait_for(original_recvall(self, size), timeout=budget)
        except asyncio.TimeoutError as error:
            minutes = max(1, round(budget / 60))
            raise DeviceLinkStalled(
                "The iPhone stopped sending data during a device transfer "
                f"(no data for {minutes} min), so the operation was stopped "
                "instead of waiting forever. Unlock the iPhone, keep the "
                "screen awake, reconnect the cable, then try again."
            ) from error

    DeviceLink._recvall = _recvall
    DeviceLink._gn_recv_timeout_installed = True
    log_info(f"DeviceLink read silence budget: {timeout:g}s "
             f"({RECV_TIMEOUT_ENV} overrides)")


def install_verbose(disk_space_message) -> None:
    """Log free-space traffic and answer purge requests without aborting the link.

    The device decides how much it uploads (and whether it trims large app
    containers like PosterBoard) based on the free-space value the host reports
    on ``DLMessageGetFreeDiskSpace`` — the only platform-forked part of the
    whole backup path (APFS purgeable space on macOS). A purge request is not
    the device's final verdict. Match the upstream fix after pinned 10.7.1:
    reply that no space was reclaimed, then wait for success or a real error.
    https://github.com/doronz88/pymobiledevice3/issues/1879
    """
    try:
        from pymobiledevice3.services.device_link import DeviceLink
    except Exception as e:  # pragma: no cover - defensive
        log_debug(f"DeviceLink verbose hook not installed: {e}")
        return
    if getattr(DeviceLink, "_gn_verbose_installed", False):
        return
    original_receive_message = DeviceLink.receive_message

    async def get_free_disk_space(self, _message):
        statvfs = shutil.disk_usage(self.root_path).free
        important = None
        if sys.platform == "darwin":
            try:
                from pymobiledevice3.services.device_link import _darwin_important_available_capacity
                important = _darwin_important_available_capacity(self.root_path)
            except Exception as e:
                log_debug(f"darwin important-capacity lookup failed: {e}")
        freespace = max(statvfs, important) if important is not None else statvfs
        log_info(f"DeviceLink free-space query | root={self.root_path} | "
                 f"statvfs={statvfs} | purgeable_aware={important} | reported={freespace}")
        self._gn_reported_free_space = freespace
        await self.status_response(0, status_dict=freespace)

    async def purge_disk_space(self, message):
        self._gn_purge_requested = True
        amount = message[1] if len(message) > 1 else None
        log_warn(f"DeviceLink: device requested host DISK PURGE | root={self.root_path} | "
                 f"requested_bytes={amount}; no space reclaimed, waiting for device verdict")
        # The amount is a purge request, not a reliable required-backup size.
        # Never report fabricated free space or delete user files to satisfy it.
        await self.status_response(-1, "DLPurgeDiskSpace failed to purge", status_dict=0)

    async def receive_message(self):
        message = await original_receive_message(self)
        # Preserve the pinned dl_loop's handling of every other message/error.
        # MBErrorDomain/105 after a host purge request is an actual refusal.
        if (getattr(self, "_gn_purge_requested", False)
                and len(message) > 1 and message[0] == "DLMessageProcessMessage"
                and isinstance(message[1], dict) and message[1].get("ErrorCode") == 105):
            raise NotEnoughDiskSpaceError(disk_space_message(
                self.root_path, getattr(self, "_gn_reported_free_space", None)))
        return message

    DeviceLink.get_free_disk_space = get_free_disk_space
    DeviceLink.purge_disk_space = purge_disk_space
    DeviceLink.receive_message = receive_message
    DeviceLink._gn_verbose_installed = True


def install_contents():
    """Make ``DLContentsOfDirectory`` tolerant of missing directories.

    The device enumerates the prior backup's ``Snapshot`` payload directory
    during an incremental backup. The cache master keeps payloads directly
    under ``<udid>/<xx>/<fileid>`` (no ``Snapshot`` subdirectory), so the
    stock pymobiledevice3 handler crashes on ``path.iterdir()``
    (FileNotFoundError) instead of answering. Apple's own host answers with an
    empty listing for a missing directory, which is how the device learns there
    is nothing to diff against and proceeds to a safe full rebuild. Mirror that:
    any missing/inaccessible enumeration target yields an empty status dict, so
    the backup never dies on the probe.
    """
    try:
        import datetime as _datetime
        from pymobiledevice3.services.device_link import APPLE_EPOCH, DeviceLink
        from typing import cast
    except Exception as e:  # pragma: no cover - defensive
        log_debug(f"DeviceLink contents shim not installed: {e}")
        return
    if getattr(DeviceLink, "_gn_contents_installed", False):
        return

    async def contents_of_directory(self, message):
        data = {}
        path = self.root_path / cast(str, message[1])
        if path.is_dir():
            # os.scandir + one entry.stat() per file. The iterdir() loop this
            # replaces called is_dir(), is_file() and stat() twice — four
            # syscalls per entry — on the backup diff enumeration, which walks
            # hundreds of thousands of files.
            with os.scandir(path) as entries:
                for entry in entries:
                    try:
                        stat_result = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        ftype = "DLFileTypeDirectory"
                    elif entry.is_file(follow_symlinks=False):
                        ftype = "DLFileTypeRegular"
                    else:
                        ftype = "DLFileTypeUnknown"
                    modifications_data = _datetime.datetime.fromtimestamp(
                        stat_result.st_mtime - APPLE_EPOCH)
                    modifications_data = modifications_data.replace(tzinfo=None)
                    data[entry.name] = {
                        "DLFileType": ftype,
                        "DLFileSize": stat_result.st_size,
                        "DLFileModificationDate": modifications_data,
                    }
        else:
            log_debug(f"DeviceLink contents-of-directory: \"{message[1]}\" absent "
                      f"under {self.root_path} — answering with an empty listing")
        await self.status_response(0, status_dict=data)

    DeviceLink.contents_of_directory = contents_of_directory
    DeviceLink._gn_contents_installed = True
