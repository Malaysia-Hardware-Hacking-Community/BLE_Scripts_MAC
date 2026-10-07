"""Tests for the SIG measurement decoders in wamble.profiles.

These are the bug-prone part (flags-driven optional fields, the IEEE-11073
float), so they are pinned against hand-built frames with known meanings.
"""

from wamble.profiles import (
    decode_csc,
    decode_health_thermometer,
    decode_heart_rate,
    summarize_csc,
    summarize_heart_rate,
    summarize_thermometer,
)


class TestHeartRate:
    def test_8bit_rate(self):
        assert decode_heart_rate(bytes([0x00, 0x3C])) == {"bpm": 60}

    def test_16bit_rate(self):
        # flags bit0 set -> 16-bit value; 300 bpm = 0x012C little-endian.
        assert decode_heart_rate(bytes([0x01, 0x2C, 0x01])) == {"bpm": 300}

    def test_sensor_contact_detected(self):
        # bit2 (0x04) = contact supported, bit1 (0x02) = contact detected.
        assert decode_heart_rate(bytes([0x06, 0x48])) == {"bpm": 72, "sensor_contact": True}

    def test_sensor_contact_not_detected(self):
        assert decode_heart_rate(bytes([0x04, 0x48])) == {"bpm": 72, "sensor_contact": False}

    def test_energy_expended(self):
        assert decode_heart_rate(bytes([0x08, 0x3C, 0x64, 0x00])) == {"bpm": 60, "energy_j": 100}

    def test_rr_intervals(self):
        # flags bit4 (0x10) -> RR present; two 16-bit values 256 and 512.
        frame = bytes([0x10, 0x3C, 0x00, 0x01, 0x00, 0x02])
        assert decode_heart_rate(frame) == {"bpm": 60, "rr": [256, 512]}


class TestHealthThermometer:
    def test_celsius_37_degrees(self):
        # IEEE-11073 float 37.0 = mantissa 370, exponent -1 -> 0xFF000172 LE.
        frame = bytes([0x00, 0x72, 0x01, 0x00, 0xFF])
        assert decode_health_thermometer(frame) == {"temperature": 37.0, "unit": "C"}

    def test_fahrenheit_unit_flag(self):
        frame = bytes([0x01, 0x72, 0x01, 0x00, 0xFF])
        assert decode_health_thermometer(frame)["unit"] == "F"

    def test_negative_temperature(self):
        # -5.0 = mantissa -50, exponent -1 -> value 0xFFFFFFCE.
        frame = bytes([0x00]) + (0xFF000000 | (0x1000000 - 50)).to_bytes(4, "little")
        assert decode_health_thermometer(frame)["temperature"] == -5.0


class TestCsc:
    def test_wheel_only(self):
        frame = bytes([0x01, 0x64, 0x00, 0x00, 0x00, 0x00, 0x02])
        assert decode_csc(frame) == {
            "cumulative_wheel_revolutions": 100,
            "last_wheel_event_time": 512,
        }

    def test_crank_only(self):
        frame = bytes([0x02, 0x32, 0x00, 0x00, 0x01])
        assert decode_csc(frame) == {
            "cumulative_crank_revolutions": 50,
            "last_crank_event_time": 256,
        }

    def test_both_present(self):
        frame = bytes([0x03, 0x64, 0x00, 0x00, 0x00, 0x00, 0x02, 0x32, 0x00, 0x00, 0x01])
        d = decode_csc(frame)
        assert d["cumulative_wheel_revolutions"] == 100
        assert d["cumulative_crank_revolutions"] == 50


class TestSummaries:
    def test_heart_rate_summary(self):
        assert summarize_heart_rate({"bpm": 72}) == "72 bpm"
        assert summarize_heart_rate({"bpm": 72, "sensor_contact": True, "rr": [256]}) == (
            "72 bpm (contact, RR=[256])"
        )

    def test_thermometer_summary(self):
        assert summarize_thermometer({"temperature": 37.0, "unit": "C"}) == "37.0 \N{DEGREE SIGN}C"

    def test_csc_summary(self):
        assert summarize_csc({"cumulative_wheel_revolutions": 100}) == "wheel 100 rev"
