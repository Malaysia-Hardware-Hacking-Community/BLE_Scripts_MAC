"""Tests for the statistics helpers behind wamble-bench.

The benchmark's number-crunching is deliberately separate from its Bluetooth I/O,
so the summaries, throughput maths, success rate and table rendering are pinned
here without an adapter. The timing loops that touch bleak are not unit-tested.
"""

from wamble.bench import (
    build_table,
    success_rate,
    summarize_durations,
    throughput,
)


class TestSummarizeDurations:
    def test_empty_is_none(self):
        assert summarize_durations([]) is None

    def test_converts_seconds_to_milliseconds(self):
        s = summarize_durations([0.1, 0.2, 0.3])
        assert s["count"] == 3
        assert s["min_ms"] == 100.0
        assert s["max_ms"] == 300.0
        assert s["median_ms"] == 200.0
        assert s["mean_ms"] == 200.0

    def test_single_sample(self):
        s = summarize_durations([0.05])
        assert s == {
            "count": 1,
            "min_ms": 50.0,
            "median_ms": 50.0,
            "mean_ms": 50.0,
            "max_ms": 50.0,
        }

    def test_median_of_even_count(self):
        s = summarize_durations([0.1, 0.2, 0.3, 0.4])
        assert s["median_ms"] == 250.0


class TestThroughput:
    def test_basic(self):
        t = throughput(ops=30, total_bytes=600, seconds=3.0)
        assert t["ops_per_s"] == 10.0
        assert t["bytes_per_s"] == 200.0

    def test_zero_seconds_is_safe(self):
        t = throughput(ops=5, total_bytes=100, seconds=0.0)
        assert t == {"ops_per_s": 0.0, "bytes_per_s": 0.0}

    def test_negative_seconds_is_safe(self):
        assert throughput(1, 1, -1.0) == {"ops_per_s": 0.0, "bytes_per_s": 0.0}


class TestSuccessRate:
    def test_all_succeed(self):
        assert success_rate(5, 5) == 1.0

    def test_partial(self):
        assert success_rate(3, 4) == 0.75

    def test_no_attempts_is_zero(self):
        assert success_rate(0, 0) == 0.0


class TestBuildTable:
    def _render(self, table) -> str:
        from rich.console import Console

        con = Console()
        with con.capture() as cap:
            con.print(table)
        return cap.get()

    def test_shows_connect_stats_and_success(self):
        stats = summarize_durations([0.1, 0.2, 0.3])
        table = self._render(
            build_table("MyDev", stats, attempts=3, successes=3, mtu=185, read=None, notify=None)
        )
        assert "Connect median" in table
        assert "3/3" in table
        assert "185 bytes" in table

    def test_no_successful_connects(self):
        table = self._render(
            build_table("MyDev", None, attempts=3, successes=0, mtu=None, read=None, notify=None)
        )
        assert "no successful connects" in table
        assert "0/3" in table
        assert "unknown" in table

    def test_includes_throughput_rows_when_present(self):
        stats = summarize_durations([0.1])
        table = self._render(
            build_table(
                "MyDev",
                stats,
                attempts=1,
                successes=1,
                mtu=23,
                read={"ops_per_s": 10.0, "bytes_per_s": 200.0},
                notify={"ops_per_s": 4.0, "bytes_per_s": 0.0},
            )
        )
        assert "Read throughput" in table
        assert "Notify throughput" in table
