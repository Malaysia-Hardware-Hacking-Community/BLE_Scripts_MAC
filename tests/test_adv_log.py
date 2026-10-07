"""Tests for the pure logic in wamble.adv_log.

Scanning needs a radio, but the CSV row shape and the per-device throttle are
pure, and they are what a downstream analysis depends on, so they are pinned
here without a Bluetooth adapter.
"""

from types import SimpleNamespace

from wamble.adv_log import ADV_LOG_FIELDS, adv_log_row, is_due


def _adv(**kw):
    return SimpleNamespace(
        local_name=kw.get("local_name"),
        manufacturer_data=kw.get("manufacturer_data", {}),
        service_data=kw.get("service_data", {}),
        service_uuids=kw.get("service_uuids", []),
        rssi=kw.get("rssi", -55),
    )


class TestAdvLogRow:
    def test_row_has_exactly_the_declared_fields(self):
        dev = SimpleNamespace(address="AA:BB", name="Acme")
        row = adv_log_row("2026-01-01T00:00:00+00:00", dev, _adv())
        assert sorted(row) == sorted(ADV_LOG_FIELDS)

    def test_name_falls_back_to_local_name_then_empty(self):
        dev = SimpleNamespace(address="AA:BB", name=None)
        assert adv_log_row("t", dev, _adv(local_name="Adv"))["name"] == "Adv"
        assert adv_log_row("t", dev, _adv())["name"] == ""

    def test_service_uuids_are_shortened_and_joined(self):
        dev = SimpleNamespace(address="AA:BB", name="x")
        adv = _adv(service_uuids=["0000180f-0000-1000-8000-00805f9b34fb", "fff0"])
        assert adv_log_row("t", dev, adv)["service_uuids"] == "180f;fff0"

    def test_missing_rssi_becomes_empty_cell(self):
        dev = SimpleNamespace(address="AA:BB", name="x")
        assert adv_log_row("t", dev, _adv(rssi=None))["rssi"] == ""

    def test_timestamp_and_address_are_carried_through(self):
        dev = SimpleNamespace(address="CC:DD", name="x")
        row = adv_log_row("2026-07-01T12:00:00+00:00", dev, _adv())
        assert row["timestamp"] == "2026-07-01T12:00:00+00:00"
        assert row["address"] == "CC:DD"


class TestIsDue:
    def test_never_seen_is_due(self):
        assert is_due(None, 100.0, 5.0) is True

    def test_zero_interval_always_due(self):
        assert is_due(100.0, 100.1, 0.0) is True

    def test_within_interval_is_not_due(self):
        assert is_due(100.0, 103.0, 5.0) is False

    def test_at_or_after_interval_is_due(self):
        assert is_due(100.0, 105.0, 5.0) is True
        assert is_due(100.0, 106.0, 5.0) is True
