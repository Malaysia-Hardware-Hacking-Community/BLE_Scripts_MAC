"""Tests for the Govee control-packet builder in wamble.exploits.

The exploit's correctness rests entirely on the 20-byte framing and the XOR
checksum: a wrong checksum means the controller silently drops the packet. This
is pure logic, so it is tested without a Bluetooth adapter.
"""

from functools import reduce

import pytest

from wamble.exploits.led_unauth_control import (
    PACKET_LEN,
    brightness_packet,
    color_packet,
    govee_packet,
    power_packet,
)


def _xor(data: bytes) -> int:
    return reduce(lambda a, b: a ^ b, data, 0)


class TestGoveePacket:
    def test_every_packet_is_20_bytes(self):
        for pkt in (
            power_packet(True),
            power_packet(False),
            brightness_packet(128),
            color_packet(255, 0, 0),
            govee_packet(0x01, 0x01),
        ):
            assert len(pkt) == PACKET_LEN

    def test_first_byte_is_the_control_marker(self):
        assert power_packet(True)[0] == 0x33

    def test_last_byte_is_xor_of_the_first_19(self):
        for pkt in (power_packet(True), color_packet(1, 2, 3), brightness_packet(200)):
            assert pkt[-1] == _xor(pkt[:19])

    def test_power_on_and_off_differ_only_in_state_and_checksum(self):
        on, off = power_packet(True), power_packet(False)
        assert on[:2] == off[:2] == bytes([0x33, 0x01])
        assert on[2] == 0x01 and off[2] == 0x00

    def test_known_good_power_on_packet(self):
        # 33 01 01 <16 zero bytes> 33
        assert power_packet(True) == bytes([0x33, 0x01, 0x01]) + bytes(16) + bytes([0x33])

    def test_known_good_red_packet(self):
        assert color_packet(255, 0, 0) == bytes([0x33, 0x05, 0x02, 0xFF, 0x00, 0x00]) + bytes(
            13
        ) + bytes([0xCB])

    def test_color_channels_are_clamped_to_byte_range(self):
        pkt = color_packet(-5, 999, 128)
        assert pkt[3] == 0 and pkt[4] == 255 and pkt[5] == 128
        assert pkt[-1] == _xor(pkt[:19])

    def test_brightness_is_clamped(self):
        assert brightness_packet(999)[2] == 255
        assert brightness_packet(-10)[2] == 0

    def test_overlong_payload_is_rejected(self):
        with pytest.raises(ValueError):
            govee_packet(0x05, *range(20))
