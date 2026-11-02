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
    async def session(_udid):
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


if __name__ == "__main__":
    unittest.main()
