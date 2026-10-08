"""Tests for the learned-identity cache that lets a scan show what an enum found.

``wamble-enum`` connects to a device, reads its real name from the Device
Information Service and records it against the device address; a later
``wamble-scan`` or ``wamble-watch`` reads that back so an otherwise "(unnamed)"
row is labelled with what the device turned out to be. These tests pin the cache
round-trip and the name-resolution precedence without any Bluetooth adapter.
"""

from types import SimpleNamespace

import pytest

from wamble.common import (
    identities_path,
    learned_identity,
    load_identities,
    remember_identity,
)
from wamble.identify import display_name


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Point the cache at a throwaway file via the documented env override."""
    path = tmp_path / "identities.json"
    monkeypatch.setenv("WAMBLE_IDENTITIES", str(path))
    return path


def _adv(local_name=None, manufacturer_data=None):
    return SimpleNamespace(
        local_name=local_name,
        manufacturer_data=manufacturer_data or {},
        service_data={},
        service_uuids=[],
    )


def _device(address="AA:BB:CC:DD:EE:FF", name=None):
    return SimpleNamespace(address=address, name=name)


class TestCacheRoundTrip:
    def test_env_override_controls_location(self, cache):
        assert identities_path() == cache

    def test_remember_then_read_back(self, cache):
        remember_identity("AA:BB", "Garmin Forerunner")
        assert learned_identity("AA:BB") == "Garmin Forerunner"
        assert load_identities() == {"AA:BB": "Garmin Forerunner"}

    def test_unknown_address_is_empty(self, cache):
        assert learned_identity("NO:SUCH") == ""

    def test_blank_name_is_not_stored(self, cache):
        remember_identity("AA:BB", "   ")
        assert load_identities() == {}

    def test_name_is_trimmed(self, cache):
        remember_identity("AA:BB", "  Polar H10 ")
        assert learned_identity("AA:BB") == "Polar H10"

    def test_second_device_is_added_not_replaced(self, cache):
        remember_identity("AA:BB", "Garmin Forerunner")
        remember_identity("CC:DD", "Polar H10")
        assert load_identities() == {"AA:BB": "Garmin Forerunner", "CC:DD": "Polar H10"}

    def test_corrupt_file_reads_as_empty(self, cache):
        cache.write_text("{ not json")
        assert load_identities() == {}


class TestDisplayNamePrecedence:
    def test_advertised_name_wins(self, cache):
        remember_identity("AA:BB:CC:DD:EE:FF", "Garmin Forerunner")
        name = display_name(_device(name="MyWatch"), _adv())
        assert name == "MyWatch"

    def test_local_name_used_when_device_name_missing(self, cache):
        assert display_name(_device(), _adv(local_name="Advertised")) == "Advertised"

    def test_learned_identity_fills_in_for_unnamed(self, cache):
        remember_identity("AA:BB:CC:DD:EE:FF", "Garmin Forerunner")
        assert display_name(_device(), _adv()) == "Garmin Forerunner"

    def test_derived_label_when_nothing_learned(self, cache):
        # Apple manufacturer data with no name and nothing cached: an inferred
        # label, marked with a leading middle dot.
        adv = _adv(manufacturer_data={0x0075: b"\x01"})
        assert display_name(_device(), adv) == "\N{MIDDLE DOT} Samsung Electronics"

    def test_unnamed_when_truly_unknown(self, cache):
        assert display_name(_device(), _adv()) == "(unnamed)"

    def test_learned_beats_derived(self, cache):
        remember_identity("AA:BB:CC:DD:EE:FF", "Garmin Forerunner")
        adv = _adv(manufacturer_data={0x0075: b"\x01"})
        assert display_name(_device(), adv) == "Garmin Forerunner"
