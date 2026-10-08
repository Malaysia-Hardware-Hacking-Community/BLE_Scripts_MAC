"""Benchmark connection performance to a BLE device (``wamble-bench``).

Measures the things that make a link feel fast or flaky, over repeated samples:

* **connection time** - how long ``connect()`` takes, sampled N times with a
  disconnect between each, reported as min / median / mean / max;
* **connect reliability** - how many of those attempts succeeded;
* **ATT MTU** - the value the OS negotiated (see :mod:`wamble.mtu`);
* **read throughput** - repeated reads of one characteristic over a window,
  as reads/second and bytes/second;
* **notification throughput** - notifications/second over a window, when a
  notify characteristic is available.

Everything here uses only the cross-platform ``bleak`` surface (``connect``,
``mtu_size``, ``read_gatt_char``, ``start_notify``), so it behaves the same on
macOS and Windows. The statistics helpers are kept free of any Bluetooth I/O so
they can be unit-tested without an adapter.
"""

import argparse
import asyncio
import statistics
import sys
import time
from typing import Any

from bleak import BleakClient
from rich.console import Console
from rich.table import Table

from wamble.common import (
    add_connection_args,
    describe_gatt_error,
    find_characteristic,
    find_device,
    is_gatt_refusal,
)

console = Console()


def summarize_durations(durations: list[float]) -> dict | None:
    """Summarise a list of second-valued samples as milliseconds.

    Returns ``{count, min_ms, median_ms, mean_ms, max_ms}`` or ``None`` when no
    samples were collected (every attempt failed), so the caller can say "no
    successful samples" rather than print zeros.
    """
    if not durations:
        return None
    ms = [d * 1000.0 for d in durations]
    return {
        "count": len(ms),
        "min_ms": min(ms),
        "median_ms": statistics.median(ms),
        "mean_ms": statistics.fmean(ms),
        "max_ms": max(ms),
    }


def throughput(ops: int, total_bytes: int, seconds: float) -> dict:
    """Operations and bytes per second over *seconds* (0 when no time elapsed)."""
    if seconds <= 0:
        return {"ops_per_s": 0.0, "bytes_per_s": 0.0}
    return {"ops_per_s": ops / seconds, "bytes_per_s": total_bytes / seconds}


def success_rate(successes: int, attempts: int) -> float:
    """Fraction in [0, 1] of attempts that succeeded (0 when none were made)."""
    if attempts <= 0:
        return 0.0
    return successes / attempts


async def measure_connect(
    device: Any, connect_timeout: float, samples: int
) -> tuple[list[float], int, int | None]:
    """Connect and disconnect *samples* times, timing each successful connect.

    Returns ``(durations, attempts, mtu)``: the per-connect seconds for the
    attempts that succeeded, the number of attempts made, and the ATT MTU read
    from the first successful connection (``None`` if none succeeded).
    """
    durations: list[float] = []
    mtu: int | None = None
    attempts = 0
    for _ in range(samples):
        attempts += 1
        client = BleakClient(device)
        start = time.perf_counter()
        try:
            await client.connect(timeout=connect_timeout)
        except Exception as exc:
            console.print(f"[dim]connect attempt failed: {exc or type(exc).__name__}[/dim]")
            continue
        durations.append(time.perf_counter() - start)
        if mtu is None:
            try:
                mtu = int(client.mtu_size)
            except Exception:
                mtu = None
        try:
            await client.disconnect()
        except Exception:
            pass
    return durations, attempts, mtu


async def measure_read_throughput(
    client: BleakClient, char: Any, seconds: float
) -> tuple[int, int, float]:
    """Read *char* in a loop for *seconds*; return (reads, total_bytes, elapsed).

    Stops early and returns what it has if the device refuses or drops the read,
    so a protected characteristic degrades to a partial result rather than an
    error.
    """
    reads = 0
    total = 0
    start = time.perf_counter()
    while time.perf_counter() - start < seconds:
        try:
            value = await client.read_gatt_char(char)
        except Exception as exc:
            reason = describe_gatt_error(exc)
            style = "dim" if is_gatt_refusal(exc) else "yellow"
            console.print(f"[{style}]read stopped: {reason}[/{style}]")
            break
        reads += 1
        total += len(value)
    return reads, total, time.perf_counter() - start


async def measure_notify_throughput(
    client: BleakClient, char: Any, seconds: float
) -> tuple[int, float]:
    """Count notifications on *char* for *seconds*; return (count, elapsed)."""
    count = 0

    def handler(_sender, _data) -> None:
        nonlocal count
        count += 1

    start = time.perf_counter()
    try:
        await client.start_notify(char, handler)
    except Exception as exc:
        reason = describe_gatt_error(exc)
        style = "dim" if is_gatt_refusal(exc) else "yellow"
        console.print(f"[{style}]cannot subscribe: {reason}[/{style}]")
        return 0, 0.0
    try:
        await asyncio.sleep(seconds)
    finally:
        try:
            await client.stop_notify(char)
        except Exception:
            pass
    return count, time.perf_counter() - start


def build_table(
    device: str,
    connect_stats: dict | None,
    attempts: int,
    successes: int,
    mtu: int | None,
    read: dict | None,
    notify: dict | None,
) -> Table:
    """Render the collected measurements as one summary table."""
    table = Table(title=f"Connection benchmark: {device}", header_style="bold cyan")
    table.add_column("Metric", style="green")
    table.add_column("Value", justify="right")

    if connect_stats:
        table.add_row("Connect min", f"{connect_stats['min_ms']:.0f} ms")
        table.add_row("Connect median", f"{connect_stats['median_ms']:.0f} ms")
        table.add_row("Connect mean", f"{connect_stats['mean_ms']:.0f} ms")
        table.add_row("Connect max", f"{connect_stats['max_ms']:.0f} ms")
    else:
        table.add_row("Connect time", "no successful connects")
    table.add_row(
        "Connect success", f"{successes}/{attempts} ({success_rate(successes, attempts):.0%})"
    )
    table.add_row("ATT MTU", f"{mtu} bytes" if mtu is not None else "unknown")

    if read is not None:
        table.add_row("Read throughput", f"{read['ops_per_s']:.1f} reads/s")
        table.add_row("Read bandwidth", f"{read['bytes_per_s']:.0f} B/s")
    if notify is not None:
        table.add_row("Notify throughput", f"{notify['ops_per_s']:.1f} notif/s")

    return table


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark connection time, MTU and throughput to a BLE device."
    )
    parser.add_argument("device", help="Device address or name")
    parser.add_argument(
        "-n",
        "--samples",
        type=int,
        default=5,
        help="Connect/disconnect samples to time (default: 5)",
    )
    parser.add_argument(
        "--read-seconds",
        type=float,
        default=3.0,
        help="Seconds to measure read throughput (0 to skip; default: 3)",
    )
    parser.add_argument(
        "--read-char",
        default=None,
        help="Characteristic UUID to read (default: first readable one)",
    )
    parser.add_argument(
        "--notify-seconds",
        type=float,
        default=0.0,
        help="Seconds to measure notification throughput (0 to skip; default: 0)",
    )
    parser.add_argument(
        "--notify-char",
        default=None,
        help="Characteristic UUID to subscribe to (default: first notify one)",
    )
    add_connection_args(parser)
    args = parser.parse_args()

    if args.samples < 1:
        parser.error("--samples must be at least 1")
    if args.scan_timeout <= 0 or args.connect_timeout <= 0:
        parser.error("timeouts must be positive")

    device = await find_device(args.device, args.scan_timeout)
    if device is None:
        console.print(f"[red]Device '{args.device}' not found.[/red]")
        sys.exit(1)
    console.print(f"[green]Found {device.name!r} [{device.address}][/green]")

    console.print(f"[cyan]Timing {args.samples} connection(s)...[/cyan]")
    durations, attempts, mtu = await measure_connect(device, args.connect_timeout, args.samples)
    connect_stats = summarize_durations(durations)

    read_result: dict | None = None
    notify_result: dict | None = None

    # Throughput needs one live connection; only open it if there were any
    # successful connects and the user asked for a throughput measurement.
    if durations and (args.read_seconds > 0 or args.notify_seconds > 0):
        client = BleakClient(device)
        try:
            await client.connect(timeout=args.connect_timeout)
            if args.read_seconds > 0:
                char = _pick(client, args.read_char, "read")
                if char is None:
                    console.print("[dim]no readable characteristic for throughput[/dim]")
                else:
                    console.print(f"[cyan]Reading for {args.read_seconds:g}s...[/cyan]")
                    reads, total, elapsed = await measure_read_throughput(
                        client, char, args.read_seconds
                    )
                    read_result = throughput(reads, total, elapsed)
            if args.notify_seconds > 0:
                char = _pick(client, args.notify_char, "notify")
                if char is None:
                    console.print("[dim]no notify characteristic for throughput[/dim]")
                else:
                    console.print(f"[cyan]Listening for {args.notify_seconds:g}s...[/cyan]")
                    count, elapsed = await measure_notify_throughput(
                        client, char, args.notify_seconds
                    )
                    notify_result = throughput(count, 0, elapsed)
        except Exception as exc:
            console.print(f"[yellow]throughput phase skipped: {exc or type(exc).__name__}[/yellow]")
        finally:
            if client.is_connected:
                await client.disconnect()

    console.print(
        build_table(
            args.device, connect_stats, attempts, len(durations), mtu, read_result, notify_result
        )
    )


def _pick(client: BleakClient, uuid: str | None, prop: str) -> Any | None:
    """Resolve the characteristic to exercise: the named one, else the first with
    the required property."""
    if uuid:
        char = find_characteristic(client, uuid)
        if char is not None and prop in char.properties:
            return char
        return None
    matches = find_characteristic(client, prop, by="property")
    return matches[0] if matches else None


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
