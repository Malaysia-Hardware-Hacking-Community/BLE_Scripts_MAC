"""Tests for the advertisement-identification logic in wamble.identify.

All of this is pure decoding of advertisement bytes, so it is pinned here with
hand-built frames (and the real Apple/Samsung shapes seen in live scans), no
Bluetooth adapter required.
"""

from types import SimpleNamespace

from wamble.identify import (
    beacon_label,
    company_name,
    decode_manufacturer,
    eddystone_from_adv,
    ibeacon_from_adv,
    identify,
    parse_ibeacon,
    vendor_label,
)


def _adv(manufacturer_data=None, service_data=None):
    return SimpleNamespace(
        manufacturer_data=manufacturer_data or {},
        service_data=service_data or {},
        service_uuids=[],
        local_name=None,
    )


# A well-formed iBeacon payload: 02 15, 16-byte UUID, major, minor, tx power.
IBEACON = bytes.fromhex("0215" + "0102030405060708090a0b0c0d0e0f10" + "0001" + "0002") + bytes(
    [0xC5]
)


class TestCompanyName:
    def test_known_ids_resolve(self):
        assert company_name(0x004C) == "Apple"
        assert company_name(0x0075) == "Samsung Electronics"

    def test_unknown_id_is_none(self):
        assert company_name(0x0211) is None


class TestParseIbeacon:
    def test_parses_a_well_formed_ibeacon(self):
        b = parse_ibeacon(IBEACON)
        assert b == {
            "uuid": "01020304-0506-0708-090a-0b0c0d0e0f10",
            "major": 1,
            "minor": 2,
            "tx_power": -59,
        }

    def test_non_ibeacon_apple_payload_is_none(self):
        # The "nearby" Apple format seen live (10 02 01 00) is not an iBeacon.
        assert parse_ibeacon(bytes.fromhex("10020100")) is None

    def test_too_short_is_none(self):
        assert parse_ibeacon(b"\x02\x15\x00") is None


class TestFromAdv:
    def test_ibeacon_from_adv(self):
        adv = _adv(manufacturer_data={0x004C: IBEACON})
        assert ibeacon_from_adv(adv)["major"] == 1

    def test_eddystone_url_is_decoded(self):
        # frame 0x10 (URL), tx power 0x00, scheme 0x03 (https://), "google", 0x07 (.com)
        body = bytes([0x10, 0x00, 0x03]) + b"google" + bytes([0x07])
        adv = _adv(service_data={"feaa": body})
        frame = eddystone_from_adv(adv)
        assert frame == {"type": "Eddystone-URL", "url": "https://google.com"}

    def test_eddystone_full_128bit_uuid_key(self):
        body = bytes([0x00, 0x00]) + b"namespacexx"
        adv = _adv(service_data={"0000feaa-0000-1000-8000-00805f9b34fb": body})
        assert eddystone_from_adv(adv)["type"] == "Eddystone-UID"


class TestLabels:
    def test_vendor_label(self):
        assert vendor_label(_adv(manufacturer_data={0x0075: b"\x01"})) == "Samsung Electronics"

    def test_vendor_label_unknown_is_none(self):
        assert vendor_label(_adv(manufacturer_data={0x0211: b"\x01"})) is None

    def test_beacon_label_ibeacon(self):
        assert beacon_label(_adv(manufacturer_data={0x004C: IBEACON})) == "iBeacon"

    def test_identify_combines_vendor_and_beacon(self):
        assert identify(_adv(manufacturer_data={0x004C: IBEACON})) == "Apple · iBeacon"

    def test_identify_vendor_only(self):
        assert identify(_adv(manufacturer_data={0x0075: b"\x01"})) == "Samsung Electronics"

    def test_identify_empty_when_nothing_known(self):
        assert identify(_adv(manufacturer_data={0x0211: b"\x01"})) == ""


class TestDecodeManufacturer:
    def test_names_the_known_vendor(self):
        assert decode_manufacturer(_adv(manufacturer_data={0x004C: b"\x10\x02"})) == (
            "Apple (0x004C): 10 02"
        )

    def test_unknown_vendor_shows_hex_id(self):
        assert decode_manufacturer(_adv(manufacturer_data={0x0211: b"\xaa"})) == "0x0211: aa"

    def test_empty_when_no_manufacturer_data(self):
        assert decode_manufacturer(_adv()) == ""
