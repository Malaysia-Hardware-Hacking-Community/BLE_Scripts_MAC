"""Tests for the pure RSSI maths behind wamble-range.

The sparkline, distance estimate, signal label and warmer/cooler trend are all
free of Bluetooth I/O, so they are pinned here without an adapter. The live
scanner loop is not unit-tested.
"""

import math

from wamble.range import (
    estimate_distance,
    signal_label,
    sparkline,
    trend,
)


class TestSparkline:
    def test_empty(self):
        assert sparkline([]) == ""

    def test_flat_series_is_mid_height(self):
        out = sparkline([-60, -60, -60])
        assert out == "▅▅▅"  # mid glyph, length preserved

    def test_rising_series_ends_highest(self):
        out = sparkline([-90, -70, -50])
        assert out[0] == "▁"  # lowest value -> lowest block
        assert out[-1] == "█"  # highest value -> highest block
        assert len(out) == 3

    def test_window_keeps_last_n(self):
        out = sparkline([-90, -80, -70, -60, -50], width=2)
        assert len(out) == 2
        # only the last two (-60, -50) remain; -60 is the min, -50 the max
        assert out == "▁█"


class TestEstimateDistance:
    def test_one_metre_at_tx_power(self):
        assert math.isclose(estimate_distance(-59, tx_power=-59, path_loss=2.0), 1.0)

    def test_weaker_signal_is_farther(self):
        near = estimate_distance(-59, tx_power=-59, path_loss=2.0)
        far = estimate_distance(-79, tx_power=-59, path_loss=2.0)
        assert far > near

    def test_stronger_than_reference_is_closer_than_one_metre(self):
        assert estimate_distance(-40, tx_power=-59, path_loss=2.0) < 1.0

    def test_non_positive_exponent_is_inf(self):
        assert estimate_distance(-60, path_loss=0) == float("inf")


class TestSignalLabel:
    def test_bands(self):
        assert signal_label(-50) == "excellent"
        assert signal_label(-60) == "excellent"
        assert signal_label(-65) == "good"
        assert signal_label(-75) == "fair"
        assert signal_label(-90) == "weak"


class TestTrend:
    def test_too_few_is_steady(self):
        assert trend([-60]) == "steady"

    def test_rising_is_warmer(self):
        # earlier window ~-80, recent window ~-60: signal rose, getting closer
        vals = [-80, -80, -80, -80, -80, -60, -60, -60, -60, -60]
        assert trend(vals, lookback=5) == "warmer"

    def test_falling_is_cooler(self):
        vals = [-60, -60, -60, -60, -60, -80, -80, -80, -80, -80]
        assert trend(vals, lookback=5) == "cooler"

    def test_small_change_is_steady(self):
        vals = [-61, -60, -61, -60, -61, -60, -61, -60, -61, -60]
        assert trend(vals, lookback=5) == "steady"
