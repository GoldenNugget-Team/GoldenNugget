#!/usr/bin/env python3
"""The pairing file GoldenNugget Mobile imports must be complete.

The host's stored pair record (usbmuxd / ``~/Library/Lockdown/<udid>.plist``)
is keyed by its **file name**, so it carries no ``UDID`` key at all, and
records written on older hosts omit ``WiFiMACAddress``. GoldenNugget Mobile's
lockdown parser requires both (``Vendor/MinimuxerCommon/PairingFile.swift``:
``LockdownPairingFile.missingKeys``), so exporting the stored record untouched
produced a file the phone refused with "Missing keys: UDID" — the pairing file
looked delivered, and the app could never start.

These checks pin the completion step, the XML export and the device lookups
that feed them. No device is needed: the lockdown session is faked.
Run: python tools/test_mobile_helper_pairing.py
"""
import asyncio
import plistlib
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.devicemanagement import mobile_helper as mh
from src.exceptions.nugget_exception import NuggetException

UDID = "00008120-0006155436F0E01E"
MAC = "d4:2d:cc:75:33:f1"

# Shape of a real host record (captured from ~/.pymobiledevice3/<udid>.plist):
# every key the mobile app needs EXCEPT the UDID.
HOST_RECORD = {
    "DeviceCertificate": b"device-cert",
    "EscrowBag": b"escrow-bag",
    "HostCertificate": b"host-cert",
    "HostID": "9EE571A7-D873-4828-988F-0F58653FFE59",
    "HostPrivateKey": b"host-key",
    "RootCertificate": b"root-cert",
    "RootPrivateKey": b"root-key",
    "SystemBUID": "D80F84C2-7620-4BD8-9CFE-24196074D973",
    "WiFiMACAddress": MAC,
}


class FakeLockdown:
    """Just enough of a LockdownClient for ``read_pairing_record``."""

    def __init__(self, record, identifier=UDID, values=None):
        self.pair_record = record
        self.identifier = identifier
        self.values = values or {}
        self.asked: list[str] = []

    async def get_value(self, key=None):
        self.asked.append(key)
        return self.values.get(key)


def fake_session(lockdown):
    @asynccontextmanager
    async def session(_udid, **_kwargs):
        yield lockdown
    return session


class PairingFileCompletion(unittest.TestCase):
    def test_host_record_gains_the_udid(self):
        record = mh.complete_pairing_record(dict(HOST_RECORD), UDID)
        self.assertEqual(record["UDID"], UDID)
        self.assertEqual(record["WiFiMACAddress"], MAC)
        # Nothing the device already answered is rewritten...
        self.assertEqual({k: record[k] for k in HOST_RECORD}, HOST_RECORD)
        self.assertEqual(mh.missing_pairing_keys(record), [])
        # ...and the caller's dict is left alone.
        self.assertNotIn("UDID", HOST_RECORD)

    def test_missing_wifi_mac_is_filled_from_the_device(self):
        host = {k: v for k, v in HOST_RECORD.items() if k != "WiFiMACAddress"}
        record = mh.complete_pairing_record(host, UDID, wifi_mac=MAC)
        self.assertEqual(record["WiFiMACAddress"], MAC)
        self.assertEqual(mh.missing_pairing_keys(record), [])

    def test_a_stale_wifi_mac_is_not_guessed(self):
        host = dict(HOST_RECORD, WiFiMACAddress="00:00:00:00:00:00")
        record = mh.complete_pairing_record(host, UDID, wifi_mac=MAC)
        self.assertEqual(record["WiFiMACAddress"], "00:00:00:00:00:00")

    def test_an_empty_record_is_not_turned_into_a_udid_only_file(self):
        self.assertEqual(mh.complete_pairing_record({}, UDID), {})
        self.assertEqual(mh.complete_pairing_record(None, UDID), {})

    def test_remote_pairing_record_is_exported_as_is(self):
        rp = {"identifier": "AAAA", "private_key": b"rp-key", "public_key": b"rp-pub"}
        self.assertEqual(mh.missing_pairing_keys(rp), [])
        self.assertEqual(mh.complete_pairing_record(rp, UDID), rp)
        self.assertNotIn("UDID", plistlib.loads(mh.pairing_record_xml(rp)))


class PairingRecordExport(unittest.TestCase):
    def test_export_is_utf8_xml_with_the_udid(self):
        record = mh.complete_pairing_record(dict(HOST_RECORD), UDID)
        xml = mh.pairing_record_xml(record)
        # The mobile app's importer only parses UTF-8 text plists.
        self.assertIn(b"<?xml", xml)
        parsed = plistlib.loads(xml)
        self.assertEqual(parsed["UDID"], UDID)
        self.assertEqual(parsed["EscrowBag"], b"escrow-bag")
        self.assertEqual(set(mh.PAIRING_RECORD_KEYS) - set(parsed), set())

    def test_export_refuses_a_record_without_a_udid(self):
        with self.assertRaises(NuggetException) as ctx:
            mh.pairing_record_xml(dict(HOST_RECORD))
        self.assertIn("UDID", str(ctx.exception))

    def test_export_refuses_an_empty_record(self):
        with self.assertRaises(NuggetException):
            mh.pairing_record_xml({})

    def test_missing_escrow_bag_warns_but_still_exports(self):
        host = {k: v for k, v in HOST_RECORD.items() if k != "EscrowBag"}
        record = mh.complete_pairing_record(host, UDID)
        with self.assertLogs("GoldenNugget.mobile_helper", level="WARNING") as logs:
            xml = mh.pairing_record_xml(record)
        self.assertIn("EscrowBag", "\n".join(logs.output))
        self.assertEqual(plistlib.loads(xml)["UDID"], UDID)


class ReadPairingRecord(unittest.TestCase):
    def test_the_host_record_is_completed_with_the_device_udid(self):
        lockdown = FakeLockdown(dict(HOST_RECORD), values={"UniqueDeviceID": UDID})
        with patch.object(mh, "lockdown_session", fake_session(lockdown)):
            record = asyncio.run(mh.read_pairing_record(UDID))
        self.assertEqual(record["UDID"], UDID)
        self.assertEqual(record["WiFiMACAddress"], MAC)
        self.assertEqual(mh.missing_pairing_keys(record), [])
        # The stored record already carries the MAC — no lookup wasted on it.
        self.assertEqual(lockdown.asked, ["UniqueDeviceID"])

    def test_a_record_without_a_mac_asks_the_device_for_it(self):
        host = {k: v for k, v in HOST_RECORD.items() if k != "WiFiMACAddress"}
        lockdown = FakeLockdown(host, values={
            "UniqueDeviceID": UDID, "WiFiMACAddress": MAC})
        with patch.object(mh, "lockdown_session", fake_session(lockdown)):
            record = asyncio.run(mh.read_pairing_record(UDID))
        self.assertEqual(record["WiFiMACAddress"], MAC)
        self.assertIn("WiFiMACAddress", lockdown.asked)

    def test_the_serial_is_the_fallback_when_the_device_does_not_answer(self):
        lockdown = FakeLockdown(dict(HOST_RECORD), identifier=UDID, values={})
        with patch.object(mh, "lockdown_session", fake_session(lockdown)):
            record = asyncio.run(mh.read_pairing_record(UDID))
        self.assertEqual(record["UDID"], UDID)

    def test_an_unpaired_device_still_answers_with_no_record(self):
        lockdown = FakeLockdown(None)
        with patch.object(mh, "lockdown_session", fake_session(lockdown)):
            record = asyncio.run(mh.read_pairing_record(UDID))
        self.assertEqual(record, {})
        # Nothing is invented from a session that never confirmed trust.
        self.assertEqual(lockdown.asked, [])


class PairingFileOnThePhone(unittest.TestCase):
    """The record already on the phone is only replaced when it is ours."""

    def test_no_record_is_replaced(self):
        self.assertEqual(mh.pairing_file_action(None), "replace")
        self.assertEqual(mh.pairing_file_action(b""), "replace")

    def test_an_old_lockdown_record_is_replaced(self):
        record = mh.complete_pairing_record(dict(HOST_RECORD), UDID)
        self.assertEqual(mh.pairing_file_action(mh.pairing_record_xml(record)),
                         "replace")

    def test_a_damaged_file_is_replaced(self):
        self.assertEqual(mh.pairing_file_action(b"not a plist"), "replace")

    def test_the_app_own_remote_pairing_record_is_kept(self):
        rp = {"identifier": "AAAA", "private_key": b"rp-key", "public_key": b"rp-pub"}
        self.assertEqual(mh.pairing_file_action(plistlib.dumps(rp)), "keep")


# The record pymobiledevice3 caches after pair-setup on the lockdown link: the
# Ed25519 key pair (plus a remote-unlock key the phone does not need).
REMOTE_HOST_RECORD = {
    "public_key": b"p" * 32,
    "private_key": b"k" * 32,
    "remote_unlock_host_key": "",
}

# The host identifier the device registered during pair-setup. pymobiledevice3
# keeps it out of its own record (it re-derives the UUIDv3 of the hostname), so
# the export has to add it to the file the phone receives.
HOST_ID = "9EE571A7-D873-4828-988F-0F58653FFE59"


def fake_remote_pairing_service(record, *, first_pairing=False, closed=None):
    """A ``RemotePairingLockdownService`` that pairs without a device."""
    from pymobiledevice3.exceptions import RemotePairingCompletedError

    class FakeService:
        identifier = HOST_ID
        handshake_info = {"peerDeviceInfo": {
            "name": "Test iPhone", "model": "iPhone17,1",
            "identifier": UDID}}

        def __init__(self):
            self.pair_record = record

        @classmethod
        async def create(cls, lockdown):
            return cls()

        async def connect(self, autopair=True):
            if first_pairing:
                # A first pairing ends with the endpoint closing the link.
                raise RemotePairingCompletedError()

        async def close(self):
            if closed is not None:
                closed.append(True)

    return FakeService


class RemotePairingExport(unittest.TestCase):
    def test_the_mobile_record_carries_identifier_and_key_pair(self):
        parsed = plistlib.loads(mh.mobile_remote_pairing_xml(
            REMOTE_HOST_RECORD, HOST_ID))
        self.assertEqual(parsed, {
            "identifier": HOST_ID,
            "private_key": b"k" * 32,
            "public_key": b"p" * 32,
        })

    def test_a_record_without_a_private_key_is_refused(self):
        with self.assertRaises(NuggetException):
            mh.mobile_remote_pairing_xml(
                {k: v for k, v in REMOTE_HOST_RECORD.items() if k != "private_key"},
                HOST_ID)

    def test_a_record_without_an_identifier_is_refused(self):
        with self.assertRaises(NuggetException):
            mh.mobile_remote_pairing_xml(REMOTE_HOST_RECORD, "  ")

    def test_export_pairs_over_lockdown_and_writes_the_mobile_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.mobiledevicepairing"
            closed = []
            fake = fake_remote_pairing_service(
                dict(REMOTE_HOST_RECORD), first_pairing=True, closed=closed)
            lockdown = FakeLockdown(dict(HOST_RECORD))
            with patch.object(mh, "lockdown_session", fake_session(lockdown)), \
                    patch("pymobiledevice3.remote.tunnel_service."
                          "RemotePairingLockdownService", fake):
                info = asyncio.run(
                    mh.export_remote_pairing_file(str(dest), udid=UDID))

            parsed = plistlib.loads(dest.read_bytes())
            self.assertEqual(parsed["identifier"], HOST_ID)
            self.assertEqual(parsed["private_key"], b"k" * 32)
            self.assertEqual(parsed["public_key"], b"p" * 32)
            self.assertEqual(info["path"], str(dest))
            self.assertEqual(info["name"], "Test iPhone")
            self.assertEqual(info["model"], "iPhone17,1")
            self.assertEqual(info["udid"], UDID)
            # The service is closed on both outcomes, pairing or not.
            self.assertEqual(closed, [True])

    def test_an_already_paired_device_does_not_need_a_second_pair_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out.mobiledevicepairing"
            fake = fake_remote_pairing_service(dict(REMOTE_HOST_RECORD))
            with patch.object(mh, "lockdown_session",
                              fake_session(FakeLockdown(dict(HOST_RECORD)))), \
                    patch("pymobiledevice3.remote.tunnel_service."
                          "RemotePairingLockdownService", fake):
                info = asyncio.run(
                    mh.export_remote_pairing_file(str(dest), udid=UDID))
            self.assertTrue(dest.exists())
        self.assertEqual(info["path"], str(dest))


class FakeHouse:
    """The house_arrest calls ``send_pairing_to_app`` makes, and nothing else."""

    def __init__(self, existing=None):
        self.files = {} if existing is None else {
            f"Documents/{mh.PAIRING_FILE_NAME}": existing}
        self.written: dict[str, bytes] = {}
        self.closed = False

    async def send_command(self, bundle_id, command):
        self.vend = (bundle_id, command)

    async def listdir(self, _path):
        return ["Documents"]

    async def mkdir(self, _path):
        pass

    async def get_file_contents(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    async def set_file_contents(self, path, data):
        self.written[path] = data

    async def close(self):
        self.closed = True


class Delivery(unittest.TestCase):
    def _send(self, house):
        lockdown = FakeLockdown(dict(HOST_RECORD), values={"UniqueDeviceID": UDID})
        with patch.object(mh, "lockdown_session", fake_session(lockdown)), \
                patch.object(mh, "HouseArrestService", lambda **_kw: house):
            return asyncio.run(mh.send_pairing_to_app(
                UDID, b"<plist/>", bundle_id="com.example.app"))

    def test_an_app_pairing_record_is_not_overwritten(self):
        rp = {"identifier": "AAAA", "private_key": b"rp-key", "public_key": b"rp-pub"}
        house = FakeHouse(plistlib.dumps(rp))
        self.assertEqual(self._send(house), "kept")
        self.assertEqual(house.written, {})
        self.assertTrue(house.closed)

    def test_our_record_replaces_an_old_lockdown_one(self):
        house = FakeHouse(mh.pairing_record_xml(
            mh.complete_pairing_record(dict(HOST_RECORD), UDID)))
        self.assertEqual(self._send(house), "delivered")
        self.assertEqual(
            house.written[f"Documents/{mh.PAIRING_FILE_NAME}"], b"<plist/>")
        self.assertTrue(house.closed)

    def test_a_fresh_container_gets_the_record(self):
        house = FakeHouse(None)
        self.assertEqual(self._send(house), "delivered")
        self.assertIn(f"Documents/{mh.PAIRING_FILE_NAME}", house.written)


if __name__ == "__main__":
    unittest.main()
