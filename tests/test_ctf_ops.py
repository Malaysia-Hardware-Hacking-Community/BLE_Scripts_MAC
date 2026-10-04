"""Offline validation of ble_ctf.py's primitives against the fake-BLE harness.

Proves the CTF read/write/read-loop/listen operations behave correctly without
a Bluetooth adapter, so the toolkit is validated before the CTF device is
plugged in. The gatt_env fixture (conftest) exposes a readable+notify char at
handle 0x0020 and a writable char at 0x0030.
"""

import pytest

from ble_ctf import (
    _hex_to_bytes,
    op_read,
    op_readloop,
    op_write,
)


class TestHexToBytes:
    def test_plain_hex(self):
        assert _hex_to_bytes("41") == b"\x41"

    def test_0x_prefix(self):
        assert _hex_to_bytes("0x41") == b"\x41"

    def test_spaced_hex(self):
        assert _hex_to_bytes("12 34 ab") == b"\x12\x34\xab"

    def test_colon_separated(self):
        assert _hex_to_bytes("de:ad") == b"\xde\xad"


async def test_op_read_returns_and_records(gatt_env):
    gatt_env.client.responses[("char", 0x0020)] = b"flag{read}"
    value = await op_read(gatt_env.client, "0x0020")
    assert value == b"flag{read}"
    assert ("read_gatt_char", gatt_env.battery_char, None, None) in gatt_env.client.calls


async def test_op_read_unknown_handle_returns_empty(gatt_env):
    assert await op_read(gatt_env.client, "0x9999") == b""


async def test_macos_value_handle_offset_resolves_one_below(gatt_env):
    # battery_char's handle is 0x0020. On macOS a gatttool *value* handle is one
    # above the declaration handle bleak reports, so asking for 0x0021 must fall
    # back to 0x0020 and still read the characteristic.
    gatt_env.client.responses[("char", 0x0020)] = b"offset-ok"
    assert await op_read(gatt_env.client, "0x0021") == b"offset-ok"


async def test_op_write_req_sets_response_true(gatt_env):
    ok = await op_write(gatt_env.client, "0x0030", b"\x41", response=True)
    assert ok is True
    assert gatt_env.client.calls[-1] == ("write_gatt_char", gatt_env.writable_char, b"\x41", True)


async def test_op_write_cmd_sets_response_false(gatt_env):
    await op_write(gatt_env.client, "0x0030", b"\x41", response=False)
    assert gatt_env.client.calls[-1][3] is False


async def test_op_write_unknown_handle_returns_false(gatt_env):
    assert await op_write(gatt_env.client, "0x9999", b"\x41", response=True) is False


async def test_op_readloop_reads_exactly_n_times(gatt_env):
    # Flag 10 is a 1001-read counter; prove the loop issues every read.
    gatt_env.client.responses[("char", 0x0020)] = b"\x2a"
    value = await op_readloop(gatt_env.client, "0x0020", 1001, show_every=0)
    reads = [c for c in gatt_env.client.calls if c[0] == "read_gatt_char"]
    assert len(reads) == 1001
    assert value == b"\x2a"


async def test_op_listen_subscribes_triggers_captures_and_unsubscribes(gatt_env):
    client = gatt_env.client
    real_start = client.start_notify

    async def start_and_deliver(char, cb, **kw):
        await real_start(char, cb, **kw)
        cb(char, b"notif-flag")  # simulate the peripheral pushing one update

    client.start_notify = start_and_deliver

    from ble_ctf import op_listen

    events = await op_listen(client, "0x0020", trigger=b"\x69", secs=0, response=False)

    assert any(e["text"] == "notif-flag" for e in events)
    op_names = [c[0] for c in client.calls]
    assert "write_gatt_char" in op_names  # the trigger write
    assert "stop_notify" in op_names      # cleaned up the subscription
