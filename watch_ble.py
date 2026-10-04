"""Continuously monitor BLE advertisements until interrupted."""

import argparse
import asyncio
from datetime import datetime

from bleak import BleakScanner
from rich.console import Console
from rich.live import Live
from rich.table import Table

from ble_common import parse_advertisement_data, short_uuid

console = Console()


def build_table(latest: dict) -> Table:
    """Render the newest advertisement per device, strongest signal first."""
    table = Table(title="BLE Advertisement Monitor", header_style="bold cyan")
    table.add_column("Name", style="green", no_wrap=True)
    table.add_column("Identifier", style="dim", overflow="fold")
    table.add_column("RSSI", justify="right")
    table.add_column("Last seen")
    table.add_column("Services", overflow="fold")
    table.add_column("Manufacturer", overflow="fold")

    ordered = sorted(
        latest.values(),
        key=lambda item: item[1].rssi if item[1].rssi is not None else -999,
        reverse=True,
    )
    for device, adv, seen in ordered:
        table.add_row(
            device.name or adv.local_name or "(unnamed)",
            device.address,
            str(adv.rssi) if adv.rssi is not None else "—",
            seen.strftime("%H:%M:%S"),
            ", ".join(short_uuid(u) for u in (adv.service_uuids or [])) or "—",
            parse_advertisement_data(adv)["manufacturer"] or "—",
        )
    return table


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Continuously monitor BLE advertisements."
    )
    parser.add_argument(
        "--name",
        help="Only display names containing this text.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Stop after this many seconds (default: run until Ctrl-C)",
    )
    parser.add_argument(
        "--refresh",
        type=float,
        default=4.0,
        help="Screen refreshes per second (default: 4)",
    )
    args = parser.parse_args()

    if args.timeout is not None and args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.refresh <= 0:
        parser.error("--refresh must be positive")

    latest: dict = {}

    def detection_callback(device, adv) -> None:
        name = device.name or adv.local_name or "(unnamed)"
        if args.name and args.name.casefold() not in name.casefold():
            return
        latest[device.address] = (device, adv, datetime.now())

    def render():
        if not latest:
            return "[yellow]Waiting for advertisements…[/yellow]"
        return build_table(latest)

    scanner = BleakScanner(detection_callback=detection_callback)

    # rich re-invokes render() on its own refresh thread, so the table is only
    # rebuilt when the frame is actually about to be drawn.
    with Live(
        get_renderable=render,
        console=console,
        refresh_per_second=args.refresh,
        screen=False,
    ):
        async with scanner:
            try:
                if args.timeout is None:
                    await asyncio.Event().wait()  # until cancelled
                else:
                    await asyncio.sleep(args.timeout)
            finally:
                await scanner.stop()

    if latest:
        console.print(f"[dim]{len(latest)} device(s) seen.[/dim]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/yellow]")