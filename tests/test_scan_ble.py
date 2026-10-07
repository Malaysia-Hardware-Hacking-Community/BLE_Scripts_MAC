"""Tests for the pure UUID-filter logic in scan_ble.

The service-UUID filter is the one piece of scan_ble that does not touch the
Bluetooth adapter, so it is unit-testable. It regressed once: CoreBluetooth
reports SIG UUIDs in full 128-bit form, and the original endswith() check
silently matched nothing on macOS. These tests pin the fixed behaviour.
"""

import csv
from types import SimpleNamespace

import pytest

from scan_ble import (
    CSV_FIELDS,
    build_device_record,
    csv_row,
    service_uuid_matches,
    write_csv,
)

# How CoreBluetooth reports 0x180F / 0xFFF0 on macOS.
BATTERY_128 = "0000180f-0000-1000-8000-00805f9b34fb"
FFF0_128 = "0000fff0-0000-1000-8000-00805f9b34fb"


class TestServiceUuidMatches:
    def test_short_filter_matches_full_128_bit_uuid(self):
        # The regression: "180f" must match the full 128-bit advertisement.
        assert service_uuid_matches("180f", [BATTERY_128]) is True

    def test_short_filter_matches_short_uuid(self):
        assert service_uuid_matches("fff0", ["fff0"]) is True

    def test_0x_prefix_is_accepted(self):
        assert service_uuid_matches("0x180F", [BATTERY_128]) is True

    def test_uppercase_filter_is_case_insensitive(self):
        assert service_uuid_matches("180F", [BATTERY_128]) is True

    def test_full_uuid_filter_matches_full_uuid(self):
        assert service_uuid_matches(BATTERY_128, [BATTERY_128]) is True

    def test_full_uuid_filter_matches_short_advertised_form(self):
        # Linux advertises the short form; a user who pastes the full UUID must
        # still match it. Matching has to work in both directions.
        assert service_uuid_matches(BATTERY_128, ["180f"]) is True

    def test_non_matching_uuid_is_rejected(self):
        assert service_uuid_matches("180f", [FFF0_128]) is False

    @pytest.mark.parametrize("fragment", ["1000", "8000", "0000", "34fb", "805f"])
    def test_base_uuid_suffix_fragments_do_not_match_every_sig_device(self, fragment):
        # The regression this guards against: a substring test against the full
        # 128-bit form matches fragments of the Bluetooth base suffix, so these
        # would have matched every standard device. They must match nothing.
        assert service_uuid_matches(fragment, [BATTERY_128]) is False

    def test_partial_fragment_of_16bit_does_not_match(self):
        # Exact-canonical matching, not substring: "2a1" is not "2a19".
        assert service_uuid_matches("2a1", ["00002a19-0000-1000-8000-00805f9b34fb"]) is False

    def test_empty_uuid_list_is_rejected(self):
        assert service_uuid_matches("180f", []) is False

    def test_none_uuid_list_is_rejected(self):
        assert service_uuid_matches("180f", None) is False

    def test_empty_filter_matches_nothing(self):
        # An empty or junk-only filter must not match every device.
        assert service_uuid_matches("", [BATTERY_128]) is False
        assert service_uuid_matches("0x", [BATTERY_128]) is False

    def test_matches_when_any_of_several_uuids_matches(self):
        assert service_uuid_matches("180f", [FFF0_128, BATTERY_128]) is True

    @pytest.mark.parametrize("needle", ["180f", "0x180f", "0000180f"])
    def test_equivalent_spellings_all_match(self, needle):
        assert service_uuid_matches(needle, [BATTERY_128]) is True


class TestBuildDeviceRecord:
    def _adv(self, **kw):
        return SimpleNamespace(
            local_name=kw.get("local_name"),
            manufacturer_data=kw.get("manufacturer_data", {}),
            service_data=kw.get("service_data", {}),
            service_uuids=kw.get("service_uuids", []),
            rssi=kw.get("rssi", -55),
        )

    def test_name_prefers_device_name(self):
        dev = SimpleNamespace(name="Acme", address="AA:BB")
        rec = build_device_record("AA:BB", dev, self._adv(local_name="ignored"))
        assert rec["name"] == "Acme"

    def test_name_falls_back_to_local_name_then_unnamed(self):
        dev = SimpleNamespace(name=None, address="AA:BB")
        assert build_device_record("AA:BB", dev, self._adv(local_name="Adv"))["name"] == "Adv"
        assert build_device_record("AA:BB", dev, self._adv())["name"] == "(unnamed)"

    def test_service_uuids_are_shortened(self):
        dev = SimpleNamespace(name="x", address="AA:BB")
        adv = self._adv(service_uuids=["0000180f-0000-1000-8000-00805f9b34fb"])
        assert build_device_record("AA:BB", dev, adv)["service_uuids"] == ["180f"]

    def test_rssi_is_passed_through(self):
        dev = SimpleNamespace(name="x", address="AA:BB")
        assert build_device_record("AA:BB", dev, self._adv(rssi=-70))["rssi"] == -70


class TestCsvRow:
    def _record(self, **kw):
        base = {
            "address": "AA:BB",
            "name": "Acme",
            "rssi": -55,
            "local_name": "Acme",
            "service_uuids": ["180f", "fff0"],
            "manufacturer_data": "0x004C: 01 02",
            "service_data": {"180f": "64", "fff0": "aa bb"},
        }
        base.update(kw)
        return base

    def test_service_uuids_are_joined(self):
        assert csv_row(self._record())["service_uuids"] == "180f;fff0"

    def test_service_data_is_rendered_as_pairs(self):
        assert csv_row(self._record())["service_data"] == "180f=64;fff0=aa bb"

    def test_missing_rssi_becomes_empty_cell(self):
        assert csv_row(self._record(rssi=None))["rssi"] == ""

    def test_missing_local_name_becomes_empty_cell(self):
        assert csv_row(self._record(local_name=None))["local_name"] == ""

    def test_scalar_fields_are_preserved(self):
        row = csv_row(self._record())
        assert row["address"] == "AA:BB"
        assert row["manufacturer_data"] == "0x004C: 01 02"


class TestWriteCsv:
    def test_round_trip_has_header_and_one_row_per_device(self, tmp_path):
        records = [
            {
                "address": "AA:BB",
                "name": "Acme",
                "rssi": -55,
                "local_name": "Acme",
                "service_uuids": ["180f"],
                "manufacturer_data": "",
                "service_data": {},
            },
            {
                "address": "CC:DD",
                "name": "(unnamed)",
                "rssi": None,
                "local_name": None,
                "service_uuids": [],
                "manufacturer_data": "",
                "service_data": {},
            },
        ]
        path = tmp_path / "scan.csv"
        write_csv(str(path), records)

        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == CSV_FIELDS
            rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["address"] == "AA:BB"
        assert rows[0]["service_uuids"] == "180f"
        assert rows[1]["rssi"] == ""
        assert rows[1]["local_name"] == ""
