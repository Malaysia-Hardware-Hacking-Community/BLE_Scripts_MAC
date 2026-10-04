"""Tests for the MiBeacon decoder in BLE-Exploits/ble_adv_harvest.py.

Decoding the fe95 advertisement is pure byte work, so it is tested against the
real frame captured from a Xiaomi Scale S400 during the live assessment.
"""

import sys
from pathlib import Path

_EXPLOITS = Path(__file__).resolve().parent.parent / "BLE-Exploits"
if str(_EXPLOITS) not in sys.path:
    sys.path.insert(0, str(_EXPLOITS))

from ble_adv_harvest import decode_mibeacon  # noqa: E402

# The exact fe95 service-data captured live from "Xiaomi Scale S400 CEC9".
REAL_FRAME = bytes.fromhex("1059d53b00c9ce63acea1c")


class TestDecodeMibeacon:
    def test_decodes_the_real_captured_scale_frame(self):
        d = decode_mibeacon(REAL_FRAME)
        assert d is not None
        assert d["frame_control"] == "0x5910"
        assert d["version"] == 5
        assert d["product_id"] == "0x3BD5"
        assert d["frame_counter"] == 0

    def test_extracts_the_little_endian_mac(self):
        # Bytes c9 ce 63 ac ea 1c, reversed, are the broadcast hardware MAC.
        assert decode_mibeacon(REAL_FRAME)["mac"] == "1C:EA:AC:63:CE:C9"

    def test_no_object_payload_in_header_only_frame(self):
        assert decode_mibeacon(REAL_FRAME)["object_payload"] == ""

    def test_object_payload_is_captured_when_present(self):
        frame = REAL_FRAME + bytes.fromhex("0a1002e803")
        assert decode_mibeacon(frame)["object_payload"] == "0a 10 02 e8 03"

    def test_frame_without_mac_flag_has_no_mac(self):
        # Frame control 0x3000 has the MAC-include bit (0x0010) clear.
        frame = bytes.fromhex("0030d53b00")
        d = decode_mibeacon(frame)
        assert d is not None and d["mac"] is None

    def test_too_short_returns_none(self):
        assert decode_mibeacon(b"\x10\x59") is None
        assert decode_mibeacon(b"") is None
