"""Tests for the capture-loader in BLE-Exploits/ble_replay.py.

load_commands() parses a prior capture JSON into a replayable packet list; its
error paths (no commands, nothing replayable) matter because a silent empty
replay would look like the exploit failed. Pure file logic, no adapter needed.
"""

import json
import sys
from pathlib import Path

import pytest

_EXPLOITS = Path(__file__).resolve().parent.parent / "BLE-Exploits"
if str(_EXPLOITS) not in sys.path:
    sys.path.insert(0, str(_EXPLOITS))

from ble_replay import load_commands  # noqa: E402


def _write(tmp_path, obj) -> str:
    p = tmp_path / "cap.json"
    p.write_text(json.dumps(obj))
    return str(p)


def test_loads_commands_with_packet_hex(tmp_path):
    path = _write(
        tmp_path,
        {"commands": [{"action": "power on", "packet_hex": "33 01 01"}, {"action": "off", "packet_hex": "33 01 00"}]},
    )
    cmds = load_commands(path)
    assert [c["action"] for c in cmds] == ["power on", "off"]
    assert cmds[0]["packet_hex"] == "33 01 01"


def test_missing_commands_key_raises(tmp_path):
    with pytest.raises(ValueError):
        load_commands(_write(tmp_path, {"target": "x"}))


def test_empty_commands_raises(tmp_path):
    with pytest.raises(ValueError):
        load_commands(_write(tmp_path, {"commands": []}))


def test_commands_without_packet_hex_raise(tmp_path):
    with pytest.raises(ValueError):
        load_commands(_write(tmp_path, {"commands": [{"action": "noop"}]}))


def test_entries_missing_packet_hex_are_skipped(tmp_path):
    path = _write(
        tmp_path,
        {"commands": [{"action": "noop"}, {"action": "on", "packet_hex": "33 01 01"}]},
    )
    cmds = load_commands(path)
    assert len(cmds) == 1 and cmds[0]["action"] == "on"


def test_missing_file_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        load_commands(str(tmp_path / "does-not-exist.json"))
