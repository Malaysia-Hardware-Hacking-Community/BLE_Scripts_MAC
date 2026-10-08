"""Tests for the platform logic and pair/unpair flow behind wamble-pair.

Pairing itself is done by the OS, so the unit-testable part is how the tool
decides what to do and how it reports the outcome. A small fake client stands in
for bleak's ``pair``/``unpair``/``read_gatt_char`` so every branch (explicit API,
macOS trigger, failure, no-API) is covered without an adapter.
"""

import pytest

from wamble.pair import attempt_pair, attempt_unpair, pairing_support


class FakeClient:
    def __init__(self, *, pair="ok", read="ok", unpair="ok"):
        self._pair = pair
        self._read = read
        self._unpair = unpair

    async def pair(self):
        if self._pair == "notimpl":
            raise NotImplementedError
        if self._pair == "error":
            raise RuntimeError("pair boom")
        return True

    async def read_gatt_char(self, _char):
        if self._read == "error":
            raise RuntimeError("encryption failed")
        return b"\x01"

    async def unpair(self):
        if self._unpair == "notimpl":
            raise NotImplementedError
        if self._unpair == "error":
            raise RuntimeError("unpair boom")
        return True


class TestPairingSupport:
    def test_windows_has_explicit_apis(self):
        s = pairing_support("win32")
        assert s["explicit_pair"] and s["explicit_unpair"]

    def test_macos_has_neither_and_mentions_settings(self):
        s = pairing_support("darwin")
        assert not s["explicit_pair"] and not s["explicit_unpair"]
        assert "System Settings" in s["note"]

    def test_linux_has_explicit_apis(self):
        s = pairing_support("linux")
        assert s["explicit_pair"] and s["explicit_unpair"]


class TestAttemptPair:
    async def test_explicit_api_pairs(self):
        status, _ = await attempt_pair(FakeClient(pair="ok"))
        assert status == "paired"

    async def test_no_api_without_trigger_is_manual(self):
        status, detail = await attempt_pair(FakeClient(pair="notimpl"), trigger_char=None)
        assert status == "manual"
        assert "--char" in detail

    async def test_no_api_with_trigger_read_triggers(self):
        status, _ = await attempt_pair(FakeClient(pair="notimpl", read="ok"), trigger_char=object())
        assert status == "triggered"

    async def test_no_api_with_failing_trigger_is_failed(self):
        status, _ = await attempt_pair(
            FakeClient(pair="notimpl", read="error"), trigger_char=object()
        )
        assert status == "failed"

    async def test_api_error_is_failed(self):
        status, detail = await attempt_pair(FakeClient(pair="error"))
        assert status == "failed"
        assert "boom" in detail


class TestAttemptUnpair:
    async def test_explicit_api_unpairs(self):
        status, _ = await attempt_unpair(FakeClient(unpair="ok"))
        assert status == "unpaired"

    async def test_no_api_is_manual(self):
        status, detail = await attempt_unpair(FakeClient(unpair="notimpl"))
        assert status == "manual"
        assert "Bluetooth" in detail

    async def test_error_is_failed(self):
        status, _ = await attempt_unpair(FakeClient(unpair="error"))
        assert status == "failed"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
