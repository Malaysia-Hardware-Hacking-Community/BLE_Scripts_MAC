"""Tests for the GATT fuzzer's payload generation and result handling.

The fuzz payloads, the writable-characteristic filter, the write loop, and the
summary are exercised here with fakes, so the destructive tool's logic is pinned
without touching a real device. The payloads are deterministic (seeded), which is
what lets a fuzz run be reproduced.
"""

from types import SimpleNamespace

from wamble.exploits.gatt_fuzz import (
    fuzz_characteristic,
    fuzz_payloads,
    summarize_results,
    writable_characteristics,
)


class TestFuzzPayloads:
    def test_deterministic_for_a_seed(self):
        assert fuzz_payloads(20, seed=7) == fuzz_payloads(20, seed=7)

    def test_different_seed_changes_random_blobs(self):
        a = dict(fuzz_payloads(32, seed=1))
        b = dict(fuzz_payloads(32, seed=2))
        assert a["random-0"] != b["random-0"]

    def test_includes_edge_cases(self):
        labels = {label for label, _ in fuzz_payloads(20)}
        assert {"empty", "one-zero", "one-ff", "ramp"} <= labels

    def test_empty_is_zero_length(self):
        assert dict(fuzz_payloads(20))["empty"] == b""

    def test_respects_max_len(self):
        for _label, data in fuzz_payloads(8, seed=3):
            assert len(data) <= 8

    def test_tiny_max_len_is_safe(self):
        # max_len of 1 must not produce longer payloads or raise.
        for _label, data in fuzz_payloads(1):
            assert len(data) <= 1


class TestWritableCharacteristics:
    def _client(self, chars):
        return SimpleNamespace(services=[SimpleNamespace(characteristics=chars)])

    def test_selects_only_writable(self):
        chars = [
            SimpleNamespace(uuid="aaaa", handle=1, properties=["read"]),
            SimpleNamespace(uuid="bbbb", handle=2, properties=["write"]),
            SimpleNamespace(uuid="cccc", handle=3, properties=["write-without-response"]),
            SimpleNamespace(uuid="dddd", handle=4, properties=["notify"]),
        ]
        out = writable_characteristics(self._client(chars))
        assert [c.uuid for c in out] == ["bbbb", "cccc"]


class FakeClient:
    def __init__(self, *, raise_on_empty=False, disconnect_after=None):
        self.is_connected = True
        self.writes = []
        self._raise_on_empty = raise_on_empty
        self._disconnect_after = disconnect_after

    async def write_gatt_char(self, _char, data, response=False):
        self.writes.append(bytes(data))
        if self._raise_on_empty and len(data) == 0:
            raise RuntimeError("bad length")
        if self._disconnect_after is not None and len(self.writes) >= self._disconnect_after:
            self.is_connected = False


_CHAR = SimpleNamespace(uuid="bbbb", handle=2, properties=["write"])


class TestFuzzCharacteristic:
    async def test_all_ok(self):
        payloads = fuzz_payloads(20)
        entry = await fuzz_characteristic(FakeClient(), _CHAR, payloads, response=True, delay=0)
        assert entry["disconnected"] is False
        assert len(entry["results"]) == len(payloads)
        assert all(r["outcome"] == "ok" for r in entry["results"])

    async def test_records_write_error(self):
        payloads = fuzz_payloads(20)  # first payload is "empty"
        entry = await fuzz_characteristic(
            FakeClient(raise_on_empty=True), _CHAR, payloads, response=True, delay=0
        )
        assert entry["results"][0]["outcome"] != "ok"

    async def test_stops_on_disconnect(self):
        payloads = fuzz_payloads(20)
        entry = await fuzz_characteristic(
            FakeClient(disconnect_after=2), _CHAR, payloads, response=False, delay=0
        )
        assert entry["disconnected"] is True
        assert len(entry["results"]) == 2  # stopped after the link dropped


class TestSummarize:
    def test_counts(self):
        per_char = [
            {
                "results": [{"outcome": "ok"}, {"outcome": "write not permitted"}],
                "disconnected": False,
            },
            {"results": [{"outcome": "ok"}], "disconnected": True},
        ]
        s = summarize_results(per_char)
        assert s == {"characteristics": 2, "writes": 3, "errors": 1, "disconnects": 1}
