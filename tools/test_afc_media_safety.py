#!/usr/bin/env python3
"""Offline test for the AFC media safety guards (no device needed).

Regression cover for a real data-loss report: after Apply Tweaks a user had
lost ~11 GB of photos, videos would not play, and Photos reported "unable to
load a higher quality version of this video".

Two independent causes are pinned here:

1. Completeness was decided by "the media folder is not empty", so a partial
   pull counted as the only copy of the photos and the backup's own media rows
   were deleted (see ``clean_backup_for_restore``).
2. ``_pull_one`` broke out of its read loop on the first empty chunk without
   checking the result against ``st_size``, so a short read was written out as
   a truncated file and reported as a success.

Exercises: the ``.media_state.json`` verification marker, invalidation on
failure/cancellation, atomic + size-checked pull, the pre-apply gate, and the
push side (no host bookkeeping pushed, short writes detected).

Run: python tools/test_afc_media_safety.py
"""
import asyncio
import os
import shutil
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.devicemanagement.device_manager import DeviceManager
from src.exceptions.nugget_exception import NuggetException
from src.restore import afc_media
from src.restore import restore as restore_mod
from src.restore.afc_media import (
    MEDIA_STATE_FILE,
    _invalidate_media_state,
    _pull_one,
    _write_media_state,
    describe_media_store,
    media_store_state,
    media_store_verified,
)

PASS = 0
TMP = tempfile.mkdtemp(prefix="gn_afc_media_")
_REAL_AFC_SERVICE = afc_media.AfcService


def check(name, cond, extra=""):
    global PASS
    assert cond, f"FAILED: {name} {extra}"
    PASS += 1
    print(f"  ok: {name}" + (f"  [{extra}]" if extra else ""))


def store(name):
    return os.path.join(TMP, name)


def write_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


# --- a fake AFC service that can misbehave exactly like the real one did -----
class FakeAfc:
    """Stand-in for pymobiledevice3's AfcService (pull + push surface only)."""

    def __init__(self, files=None, short_reads=(), drop_after_first_chunk=()):
        self.files = dict(files or {})
        self.short_reads = set(short_reads)
        self.drop_after_first_chunk = set(drop_after_first_chunk)
        self.written = {}
        self.made_dirs = []
        self._pos = {}

    async def listdir(self, path):
        if path == "/":
            trees = {p.split("/")[1] for p in self.files}
            return [".", ".."] + sorted(trees)
        prefix = path.rstrip("/") + "/"
        kids = {p[len(prefix):].split("/")[0]
                for p in self.files if p.startswith(prefix)}
        return [".", ".."] + sorted(kids)

    async def stat(self, path):
        if path in self.written:
            return {"st_size": len(self.written[path]), "st_ifmt": "S_IFREG"}
        if path in self.files:
            return {"st_size": len(self.files[path]), "st_ifmt": "S_IFREG"}
        return {"st_size": 0, "st_ifmt": "S_IFDIR"}

    async def isdir(self, path):
        return (await self.stat(path))["st_ifmt"] == "S_IFDIR"

    async def exists(self, path):
        return True

    async def makedirs(self, path):
        self.made_dirs.append(path)

    async def get_file_contents(self, path):
        return self.files[path]

    async def fopen(self, path, mode="r"):
        self._pos[path] = 0
        return path

    async def fread(self, handle, size):
        data = self.files[handle]
        if handle in self.drop_after_first_chunk and self._pos.get(handle, 0) > 0:
            return b""                                  # connection dies
        start = self._pos.get(handle, 0)
        if handle in self.short_reads:                  # device sends a stub
            self._pos[handle] = start + size // 2
            return data[start:start + size // 2]
        if start >= len(data):
            return b""                                  # genuine EOF
        chunk = data[start:start + size]
        self._pos[handle] = start + len(chunk)
        return chunk

    async def fclose(self, handle):
        pass

    async def fwrite(self, handle, chunk):
        self.written[handle] = self.written.get(handle, b"") + chunk

    async def set_file_contents(self, path, data):
        self.written[path] = data


class _Ctx:
    def __init__(self, afc):
        self.afc = afc

    async def __aenter__(self):
        return self.afc

    async def __aexit__(self, *a):
        return False


def use_afc(fake, fn):
    """Run `fn` with AfcService patched to hand back `fake`."""
    real = afc_media.AfcService
    afc_media.AfcService = lambda lockdown_client: _Ctx(fake)
    try:
        return fn()
    finally:
        afc_media.AfcService = real


# =============================================================================
def test_marker_gate():
    print("\nmedia_state.json verification gate")
    empty = store("empty")
    os.makedirs(empty)
    check("empty dir is NOT verified", not media_store_verified(empty))
    check("missing dir is NOT verified", not media_store_verified(store("nope")))
    check("no path at all is NOT verified", not media_store_verified(""))

    good = store("good")
    write_file(os.path.join(good, "DCIM", "100APPLE", "IMG_0001.JPG"), b"x" * 1000)
    _write_media_state(good, files=1, bytes_=1000, skipped=0)
    check("freshly pulled store IS verified", media_store_verified(good))
    check("describe says verified", "verified" in describe_media_store(good))

    # the reported bug: an interrupted pull leaves files behind, so the old
    # "is the folder non-empty" test passed on a fragment
    partial = store("partial")
    write_file(os.path.join(partial, "DCIM", "half.MOV"), b"x" * 10)
    check("partial store with files is NOT verified",
          not media_store_verified(partial))

    # a store that was good and then lost files must stop counting as verified
    shrunk = store("shrunk")
    for i in range(5):
        write_file(os.path.join(shrunk, "DCIM", f"f{i}.MOV"), b"y" * 500)
    _write_media_state(shrunk, files=5, bytes_=2500, skipped=0)
    check("complete store verified", media_store_verified(shrunk))
    os.remove(os.path.join(shrunk, "DCIM", "f3.MOV"))
    os.remove(os.path.join(shrunk, "DCIM", "f4.MOV"))
    check("store that lost files is NOT verified", not media_store_verified(shrunk))

    # extra local files are normal (device-deleted files are never removed)
    extra = store("extra")
    write_file(os.path.join(extra, "DCIM", "a.MOV"), b"z" * 100)
    _write_media_state(extra, files=1, bytes_=100, skipped=0)
    write_file(os.path.join(extra, "DCIM", "old_removed.MOV"), b"z" * 900)
    check("store larger than the marker is still verified",
          media_store_verified(extra))

    zero = store("zero")
    os.makedirs(zero)
    _write_media_state(zero, files=0, bytes_=0, skipped=0)
    check("zero-file store is NOT verified", not media_store_verified(zero))

    corrupt = store("corrupt")
    os.makedirs(corrupt)
    with open(os.path.join(corrupt, MEDIA_STATE_FILE), "w") as f:
        f.write("{not json")
    check("unparsable marker is NOT verified", not media_store_verified(corrupt))

    dead = store("dead")
    write_file(os.path.join(dead, "DCIM", "a.MOV"), b"q" * 100)
    _write_media_state(dead, files=1, bytes_=100, skipped=0)
    check("verified before interruption", media_store_verified(dead))
    _invalidate_media_state(dead, "test")
    check("marker gone after interruption", media_store_state(dead) is None)
    check("interrupted store is NOT verified", not media_store_verified(dead))


# =============================================================================
def test_pull():
    print("\nbackup_media_via_afc: marker only after a clean finish")
    big = b"a" * (9 * 1024 * 1024)          # > MAXIMUM_READ_SIZE -> streaming
    files = {
        "/DCIM/100APPLE/VID_0001.MOV": big,
        "/DCIM/100APPLE/IMG_0001.JPG": b"j" * 100,
    }

    done = store("pulled")
    os.makedirs(done)
    tally = use_afc(FakeAfc(files), lambda: asyncio.run(
        afc_media.backup_media_via_afc(None, done)))
    check("pull reported both files", tally["files"] == 2, tally)
    check("store verified after a clean pull", media_store_verified(done))
    check("big file fully written",
          os.path.getsize(os.path.join(done, "DCIM", "100APPLE",
                                       "VID_0001.MOV")) == len(big))
    check("no .part leftovers", not _has_part(done))

    dropped = store("dropped")
    os.makedirs(dropped)
    _write_media_state(dropped, files=2, bytes_=len(big) + 100, skipped=0)
    fake = FakeAfc(files, drop_after_first_chunk={"/DCIM/100APPLE/VID_0001.MOV"})

    def go():
        try:
            use_afc(fake, lambda: asyncio.run(
                afc_media.backup_media_via_afc(None, dropped)))
            return False
        except NuggetException:
            return True
    check("a dropped connection raises", go())
    check("store left UNVERIFIED after a failed pull",
          not media_store_verified(dropped), describe_media_store(dropped))

    warned = store("warned")
    os.makedirs(warned)
    tally = use_afc(FakeAfc(files, short_reads=set(files)), lambda: asyncio.run(
        afc_media.backup_media_via_afc(None, warned, on_error="warn")))
    check("stubbed reads are reported as failed", bool(tally.get("failed")))
    check("store with holes is NOT verified", not media_store_verified(warned))


def _has_part(root):
    for _d, _dirs, names in os.walk(root):
        for n in names:
            if n.endswith(".part"):
                return True
    return False


# =============================================================================
def test_pull_one():
    print("\n_pull_one: a truncated file never survives")
    small = os.path.join(TMP, "small.jpg")
    asyncio.run(_pull_one(FakeAfc({"/DCIM/IMG.JPG": b"k" * 2048}),
                          "/DCIM/IMG.JPG", small, {"st_size": 2048}))
    check("small file written intact", os.path.getsize(small) == 2048)

    trunc_dst = os.path.join(TMP, "trunc.mov")
    trunc = FakeAfc({"/DCIM/S.MOV": b"m" * (8 * 1024 * 1024)},
                    short_reads={"/DCIM/S.MOV"})
    check("stubbed streaming read raises", _raises(
        trunc, "/DCIM/S.MOV", trunc_dst, {"st_size": 8 * 1024 * 1024}))
    check("no truncated file left on disk", not os.path.exists(trunc_dst))
    check("no .part left behind", not os.path.exists(trunc_dst + ".part"))

    # a one-shot read that comes back smaller than st_size
    lie_dst = os.path.join(TMP, "lie.jpg")
    lie = FakeAfc({"/DCIM/L.JPG": b"l" * 512})
    check("size mismatch raises", _raises(
        lie, "/DCIM/L.JPG", lie_dst, {"st_size": 4096}))
    check("no partial file for the short-read case", not os.path.exists(lie_dst))


def _raises(fake, remote, dst, stat):
    try:
        asyncio.run(_pull_one(fake, remote, dst, stat))
        return False
    except NuggetException:
        return True


# =============================================================================
def test_push():
    print("\nrestore_media_via_afc: no host bookkeeping, short writes caught")
    src = store("pushed")
    write_file(os.path.join(src, "DCIM", "IMG.JPG"), b"p" * 500)
    write_file(os.path.join(src, "DCIM", "VID.MOV"), b"v" * (6 * 1024 * 1024))
    _write_media_state(src, files=2, bytes_=500 + 6 * 1024 * 1024, skipped=0)

    fake = FakeAfc()
    tally = use_afc(fake, lambda: asyncio.run(
        afc_media.restore_media_via_afc(None, src)))
    check("both media files pushed", tally["files"] == 2, tally)
    check("marker NOT pushed to the device",
          not any(MEDIA_STATE_FILE in k for k in fake.written), list(fake.written))
    check("no .part pushed", not any(k.endswith(".part") for k in fake.written))
    check("small file pushed intact",
          fake.written["/DCIM/IMG.JPG"] == b"p" * 500)

    class TruncatingAfc(FakeAfc):
        async def fwrite(self, handle, chunk):
            self.written[handle] = (self.written.get(handle, b"")
                                    + chunk[:len(chunk) // 2])

    short = store("shortpush")
    write_file(os.path.join(short, "DCIM", "BIG.MOV"), b"b" * (6 * 1024 * 1024))

    def go():
        try:
            use_afc(TruncatingAfc(), lambda: asyncio.run(
                afc_media.restore_media_via_afc(None, short)))
            return False
        except NuggetException as e:
            return "written short" in str(e)
    check("short write on the device is detected", go())


# =============================================================================
def test_push_diff():
    print("\nrestore_media_via_afc: only what the device lacks is transferred")
    src = store("diffpush")
    write_file(os.path.join(src, "DCIM", "SAME.JPG"), b"s" * 500)
    write_file(os.path.join(src, "DCIM", "CHANGED.JPG"), b"c" * 400)
    write_file(os.path.join(src, "DCIM", "MISSING.JPG"), b"m" * 300)
    _write_media_state(src, files=3, bytes_=500 + 400 + 300, skipped=0)

    # The device already holds SAME.JPG at the same size (so it is up to
    # date) and CHANGED.JPG at a DIFFERENT size (so the store's copy wins).
    fake = FakeAfc(files={
        "/DCIM/SAME.JPG": b"s" * 500,
        "/DCIM/CHANGED.JPG": b"x" * 999,
    })
    tally = use_afc(fake, lambda: asyncio.run(
        afc_media.restore_media_via_afc(None, src)))
    check("the unchanged file is NOT re-transferred",
          "/DCIM/SAME.JPG" not in fake.written, list(fake.written))
    check("the changed file IS re-transferred",
          fake.written.get("/DCIM/CHANGED.JPG") == b"c" * 400)
    check("the missing file IS transferred",
          fake.written.get("/DCIM/MISSING.JPG") == b"m" * 300)
    check("only the two needed files were pushed", tally["files"] == 2, tally)
    check("the skipped file is reported", tally.get("skipped") == 1, tally)

    # diff=False forces everything (the explicit "restore my data" path).
    fake2 = FakeAfc(files={"/DCIM/SAME.JPG": b"s" * 500})
    tally2 = use_afc(fake2, lambda: asyncio.run(
        afc_media.restore_media_via_afc(None, src, diff=False)))
    check("diff=False pushes every file including unchanged ones",
          tally2["files"] == 3 and "/DCIM/SAME.JPG" in fake2.written, tally2)

    # A device that cannot list its media tree must not cause files to be
    # skipped — the push has to fall back to transferring everything.
    class BrokenListAfc(FakeAfc):
        async def listdir(self, path):
            raise RuntimeError("device busy")

    broken = BrokenListAfc(files={"/DCIM/SAME.JPG": b"s" * 500})
    tally3 = use_afc(broken, lambda: asyncio.run(
        afc_media.restore_media_via_afc(None, src)))
    check("an unreadable device tree falls back to pushing everything",
          tally3["files"] == 3, tally3)


# =============================================================================
def test_pre_apply_gate():
    print("\nDeviceManager._require_media_copy: refuse before the wipe")
    good = store("gate_good")
    write_file(os.path.join(good, "DCIM", "a.MOV"), b"g" * 100)
    _write_media_state(good, files=1, bytes_=100, skipped=0)
    partial = store("gate_partial")
    write_file(os.path.join(partial, "DCIM", "a.MOV"), b"g" * 10)

    class Prepared:
        def __init__(self, media_src):
            self.media_src = media_src

    def gate(media_src):
        try:
            DeviceManager._require_media_copy(Prepared(media_src))
            return "ok"
        except NuggetException as e:
            return str(e)

    check("no media_src passes (media rides the backup)", gate("") == "ok")
    check("verified store passes", gate(good) == "ok")
    msg = gate(partial)
    check("partial store ABORTS", msg != "ok")
    check("abort message names the risk",
          "wipe" in msg and "no complete copy" in msg, msg[:80])
    check("missing store ABORTS", gate(store("gate_nope")) != "ok")
    check("a wiped apply cannot be started by a pre-wipe failure",
          "before anything was changed" in msg)


# =============================================================================
def test_restore_call_sites():
    print("\nshared restore preparation and Phase 5 fail closed")
    from unittest.mock import Mock, patch

    from src.restore.recovery import RecoveryBackend, RecoverySource, prepare_recovery
    from src.restore.verification import PruneResult
    good = store("shared_gate")
    write_file(os.path.join(good, "DCIM", "photo.jpg"), b"photo")
    _write_media_state(good, 1, 5, 0)
    for root, expected in ((good, True), (store("partial_gate"), False)):
        prune = Mock(return_value=PruneResult())
        asyncio.run(prepare_recovery(
            RecoverySource("backup", "device", media_dir=root),
            RecoveryBackend(prune, lambda *args: [], media_store_verified)))
        check("shared prune requires a freshly verified marker",
              prune.call_args.kwargs["exclude_afc_media_trees"] is expected)
    client = SimpleNamespace(close=AsyncMock())
    try:
        asyncio.run(restore_mod._push_afc_media(
            client, store("absent_media"), lambda value: None, None))
    except NuggetException as exc:
        check("Phase 5 raises on a missing media store", "missing or empty" in str(exc))
    else:
        check("Phase 5 raises on a missing media store", False)
    push = AsyncMock(return_value={"files": 1, "failed": ["DCIM/photo.jpg"]})
    with patch.object(restore_mod, "restore_media_via_afc", push):
        try:
            asyncio.run(restore_mod._push_afc_media(
                client, good, lambda value: None, None))
        except NuggetException:
            check("Phase 5 aborts on a failed media push", True)
        else:
            check("Phase 5 aborts on a failed media push", False)
    check("normal Phase 5 requests the current verified set", push.call_args.kwargs["include_historical"] is False)
    check("Phase 5 provides Abort/Resume callbacks to the AFC wait",
          "prompt_choice" in push.call_args.kwargs and "unlock_prompt" in push.call_args.kwargs)


# =============================================================================
# Phase 5 runs right after a reboot, so the AFC open hits a device that is
# paired/reachable but still at the lock screen: lockdownd answers
# PasswordProtected and the whole apply used to die there -- AFTER the wipe,
# with the photos sitting only in the cache. A real iOS 27.0.1 run failed with
# PasswordRequiredError at AfcService.__aenter__ with no way to retry.
def test_afc_open_retry():
    print("\nAFC open waits out a locked device (PasswordProtected)")
    import pymobiledevice3.exceptions as pm3_exc
    LOCKED = pm3_exc.PasswordRequiredError("PasswordProtected", "UDID", "27.0.1")
    DROPPED = pm3_exc.ConnectionTerminatedError("connection terminated")

    class FakeAfc:
        """An AfcService whose connect fails `fail_times` times, then works."""

        def __init__(self, fail_times=0, exc=None):
            self.fail_times = fail_times
            self.exc = exc
            self.closed = 0

        async def __aenter__(self):
            if self.fail_times > 0:
                self.fail_times -= 1
                raise self.exc
            return self

        async def __aexit__(self, *_exc):
            self.closed += 1
            return False

    made = []

    def install(factory):
        """Patch AfcService; `factory()` makes one service per attempt."""
        made.clear()

        def fake_service(_client):
            inst = factory()
            made.append(inst)
            return inst
        afc_media.AfcService = fake_service

    def fails_once(exc):
        """Locked for the first attempt only -- the wait then succeeds."""
        state = {"n": 0}

        def factory():
            state["n"] += 1
            return FakeAfc(fail_times=1 if state["n"] == 1 else 0, exc=exc)
        return factory

    def always_fails(exc):
        return lambda: FakeAfc(fail_times=1, exc=exc)

    original_connect = afc_media.lockdown_session
    client = SimpleNamespace(identifier="UDID", close=AsyncMock())
    @asynccontextmanager
    async def retry_session(**kwargs):
        yield client

    afc_media.lockdown_session = retry_session
    real_sleep, real_monotonic = asyncio.sleep, time.monotonic

    async def no_sleep(_):
        await real_sleep(0)

    ticks = {"t": 0}

    def fake_clock():
        ticks["t"] += 1
        return ticks["t"]

    try:
        afc_media.asyncio.sleep = no_sleep
        afc_media.time.monotonic = fake_clock

        # --- 1. a locked device is waited out, then the body runs once ------
        install(fails_once(LOCKED))
        labels, body = [], []

        async def run():
            async with afc_media.open_afc_for_media(
                    client, progress_callback=labels.append) as svc:
                body.append(svc)
        asyncio.run(run())

        check("a locked device is retried, not fatal", len(made) == 2,
              f"{len(made)} attempts")
        check("the push body runs exactly once", len(body) == 1)
        check("the service is the one __aenter__ returned", body[0] is made[-1])
        check("the service is closed afterwards", made[-1].closed == 1)
        check("the user is told to unlock the device",
              any("unlock" in str(m).lower() for m in labels),
              str(labels[0])[:44])

        # --- 2. a dropped connection is retried too -------------------------
        install(fails_once(DROPPED))

        async def run_dropped():
            async with afc_media.open_afc_for_media(client):
                return "ok"
        check("a dropped connection is retried, not fatal",
              asyncio.run(run_dropped()) == "ok")

        # --- 3. a real rejection is NOT retried ----------------------------
        install(always_fails(RuntimeError("no such service")))

        async def run_bad():
            async with afc_media.open_afc_for_media(client, timeout=60):
                raise AssertionError("body must not run")
        try:
            asyncio.run(run_bad())
            check("a real rejection raises at once", False, "no exception")
        except RuntimeError as e:
            check("a real rejection raises at once", "no such service" in str(e))
            check("a real rejection is not retried", len(made) == 1,
                  f"{len(made)} attempts")

        # --- 4. budget spent with no prompt => raise (photos may be the only copy)
        ticks["t"] = 0
        install(always_fails(LOCKED))
        ran = []

        async def run_exhausted():
            async with afc_media.open_afc_for_media(client, timeout=0) as svc:
                ran.append(svc)
        try:
            asyncio.run(run_exhausted())
            check("an exhausted wait RAISES", False, "no exception")
        except NuggetException as e:
            check("an exhausted wait RAISES", True)
            check("it says the device stayed locked",
                  "locked" in str(e).lower(), str(e)[:46])
        check("an exhausted wait never pushes anything", not ran)
        check("without a prompt the wait is not stretched forever",
              len(made) == 1, f"{len(made)} attempts")

        # --- 5. Abort ends it, Resume restarts the cycle --------------------
        ticks["t"] = 0
        seen = []

        def prompt_abort(title, text):
            seen.append((title, text))
            return "abort"
        install(always_fails(LOCKED))

        async def run_abort():
            async with afc_media.open_afc_for_media(
                    client, prompt_choice=prompt_abort,
                    unlock_prompt=("T", "unlock it"), timeout=0):
                raise AssertionError("body must not run")
        try:
            asyncio.run(run_abort())
            check("Abort stops the restore", False, "no exception")
        except NuggetException:
            check("Abort stops the restore", True)
        check("Abort shows the prompt once", len(seen) == 1, f"{len(seen)} prompts")
        check("the prompt carries a title and user-facing text",
              seen[0][0] == "T" and "unlock" in seen[0][1])

        ticks["t"] = 0
        seen.clear()
        state = {"n": 0}

        def factory():
            # locked for the whole first cycle, healthy once the user resumes
            state["n"] += 1
            return FakeAfc(fail_times=1 if state["n"] == 1 else 0, exc=LOCKED)
        install(factory)

        def prompt_resume(title, text):
            seen.append((title, text))
            return "resume"

        async def run_resume():
            async with afc_media.open_afc_for_media(
                    client, prompt_choice=prompt_resume,
                    unlock_prompt=("T", "unlock it"), timeout=0) as svc:
                return svc
        got = asyncio.run(run_resume())
        check("Resume restarts the wait and the push then runs",
              got is not None and got is made[-1])
        check("Resume was asked exactly once", len(seen) == 1, f"{len(seen)} prompts")
    finally:
        afc_media.lockdown_session = original_connect
        afc_media.asyncio.sleep = real_sleep
        afc_media.time.monotonic = real_monotonic
        afc_media.AfcService = _REAL_AFC_SERVICE

    check("the real AfcService is restored",
          afc_media.AfcService is _REAL_AFC_SERVICE)



def main():
    test_marker_gate()
    test_pull()
    test_pull_one()
    test_push()
    test_push_diff()
    test_pre_apply_gate()
    test_restore_call_sites()
    test_afc_open_retry()
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\nALL {PASS} CHECKS PASSED")


if __name__ == "__main__":
    import src.gui.thread_workers.apply_worker  # noqa: F401  (for the source check)
    main()
