"""Track one device's RSSI over time as a "hotter / colder" finder (``wamble-range``).

Follows a single device's advertised signal strength live: current RSSI, a
sparkline of recent samples, a rough distance estimate, and whether you are
getting warmer (signal rising) or cooler. Useful for physically locating a
beacon or tag.

It reads the per-advertisement RSSI the scanner already reports, which `bleak`
exposes identically on macOS and Windows, so this behaves the same on both. The
decoding and maths (sparkline, distance estimate, trend) are kept free of any
Bluetooth I/O so they can be unit-tested without an adapter.

The distance estimate uses the log-distance path-loss model,
``d = 10 ** ((tx_power - rssi) / (10 * n))``, where ``tx_power`` is the expected
RSSI at one metre and ``n`` is the environment's path-loss exponent. It is a
rough guide, not a measurement: BLE RSSI is noisy and antenna-dependent.
"""

import argparse
import asyncio
import statistics
from collections import deque
from datetime import datetime

from bleak import BleakScanner
from rich.console import Console
from rich.live import Live
from rich.table import Table

from wamble.common import resolve_target

console = Console()

#: Block glyphs for the sparkline, lowest to highest.
_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values, width: int = 0) -> str:
    """Render *values* as a block sparkline, newest last.

    With *width* > 0 only the last *width* values are shown. A flat series (all
    equal) renders as a mid-height line rather than dividing by zero.
    """
    vals = list(values)
    if width and len(vals) > width:
        vals = vals[-width:]
    if not vals:
        return ""
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return _BLOCKS[len(_BLOCKS) // 2] * len(vals)
    span = hi - lo
    top = len(_BLOCKS) - 1
    return "".join(_BLOCKS[round((v - lo) / span * top)] for v in vals)


def estimate_distance(rssi: float, tx_power: float = -59.0, path_loss: float = 2.0) -> float:
    """Estimate metres from *rssi* via the log-distance path-loss model.

    *tx_power* is the RSSI expected at 1 m; *path_loss* is the environment
    exponent (about 2.0 in free space, 2.7-4.3 indoors). Returns ``inf`` for a
    non-positive exponent rather than raising.
    """
    if path_loss <= 0:
        return float("inf")
    return 10 ** ((tx_power - rssi) / (10 * path_loss))


def signal_label(rssi: float) -> str:
    """A coarse strength word for *rssi* in dBm."""
    if rssi >= -60:
        return "excellent"
    if rssi >= -70:
        return "good"
    if rssi >= -80:
        return "fair"
    return "weak"


def trend(values, lookback: int = 5, threshold: float = 3.0) -> str:
    """Compare the recent mean RSSI to the preceding window.

    Returns "warmer" when the signal rose by at least *threshold* dB (you are
    getting closer), "cooler" when it fell by as much, else "steady". Too few
    samples is "steady".
    """
    vals = list(values)
    if len(vals) < 2:
        return "steady"
    recent = vals[-lookback:]
    prev = vals[-2 * lookback : -lookback]
    if not prev:
        return "steady"
    delta = statistics.fmean(recent) - statistics.fmean(prev)
    if delta >= threshold:
        return "warmer"
    if delta <= -threshold:
        return "cooler"
    return "steady"


#: Colour per trend word, for the live display.
_TREND_STYLE = {"warmer": "bold green", "cooler": "bold red", "steady": "dim"}


def build_table(
    name: str,
    address: str,
    samples,
    *,
    tx_power: float,
    path_loss: float,
    window: int,
    last_seen: datetime | None,
) -> Table:
    """Render the live RSSI panel for the tracked device."""
    table = Table(title=f"Signal: {name}", header_style="bold cyan", show_header=False)
    table.add_column("Field", style="green")
    table.add_column("Value", overflow="fold")

    table.add_row("Address", address)
    if not samples:
        table.add_row("RSSI", "waiting for advertisements...")
        return table

    vals = list(samples)
    current = vals[-1]
    direction = trend(vals)
    table.add_row("RSSI", f"{current} dBm ({signal_label(current)})")
    table.add_row("Trend", f"[{_TREND_STYLE[direction]}]{direction}[/{_TREND_STYLE[direction]}]")
    table.add_row("Distance", f"~{estimate_distance(current, tx_power, path_loss):.1f} m (est)")
    table.add_row("History", sparkline(vals, window))
    table.add_row(
        "min / avg / max",
        f"{min(vals)} / {statistics.fmean(vals):.0f} / {max(vals)} dBm  (n={len(vals)})",
    )
    if last_seen is not None:
        table.add_row("Last seen", last_seen.strftime("%H:%M:%S"))
    return table


def _matches(needle: str, device, adv) -> bool:
    """True when *device*/*adv* is the target named by *needle* (addr or name)."""
    if needle == str(device.address).strip().casefold():
        return True
    name = (device.name or adv.local_name or "").casefold()
    return bool(needle) and needle in name


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Track a device's RSSI live, with a sparkline and distance estimate."
    )
    parser.add_argument("device", help="Device address or name (or @alias)")
    parser.add_argument(
        "--timeout", type=float, default=None, help="Stop after N seconds (default: until Ctrl-C)"
    )
    parser.add_argument(
        "--tx-power",
        type=float,
        default=-59.0,
        help="RSSI in dBm expected at 1 m, for the distance estimate (default: -59)",
    )
    parser.add_argument(
        "--path-loss",
        type=float,
        default=2.0,
        help="Path-loss exponent: ~2.0 free space, 2.7-4.3 indoors (default: 2.0)",
    )
    parser.add_argument(
        "--window", type=int, default=48, help="Samples kept for the sparkline (default: 48)"
    )
    parser.add_argument(
        "--refresh", type=float, default=4.0, help="Screen refreshes per second (default: 4)"
    )
    args = parser.parse_args()

    if args.timeout is not None and args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.window < 1:
        parser.error("--window must be at least 1")
    if args.path_loss <= 0:
        parser.error("--path-loss must be positive")
    if args.refresh <= 0:
        parser.error("--refresh must be positive")

    needle = str(resolve_target(args.device)).strip().casefold()
    samples: deque = deque(maxlen=args.window)
    state = {"name": args.device, "address": "-", "last_seen": None}

    def detection_callback(device, adv) -> None:
        if not _matches(needle, device, adv) or adv.rssi is None:
            return
        samples.append(adv.rssi)
        state["name"] = device.name or adv.local_name or args.device
        state["address"] = device.address
        state["last_seen"] = datetime.now()

    def render():
        return build_table(
            state["name"],
            state["address"],
            samples,
            tx_power=args.tx_power,
            path_loss=args.path_loss,
            window=args.window,
            last_seen=state["last_seen"],
        )

    console.print(f"[cyan]Tracking {args.device!r}... press Ctrl-C to stop.[/cyan]")
    scanner = BleakScanner(detection_callback=detection_callback)
    with Live(get_renderable=render, console=console, refresh_per_second=args.refresh):
        async with scanner:
            if args.timeout is None:
                await asyncio.Event().wait()
            else:
                await asyncio.sleep(args.timeout)

    if samples:
        console.print(f"[dim]{len(samples)} sample(s); last RSSI {samples[-1]} dBm.[/dim]")
    else:
        console.print(f"[yellow]No advertisements seen from {args.device!r}.[/yellow]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/yellow]")
