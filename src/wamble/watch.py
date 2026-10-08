"""Continuously monitor BLE advertisements until interrupted."""

import argparse
import asyncio
from datetime import datetime

from bleak import BleakScanner
from rich.console import Console
from rich.live import Live
from rich.table import Table

from wamble.common import short_uuid, uuid_name
from wamble.identify import decode_manufacturer, display_name

console = Console()


def _service_label(uuid) -> str:
    """A compact UUID with its assigned name appended when known."""
    name = uuid_name(uuid)
    return f"{short_uuid(uuid)} ({name})" if name else short_uuid(uuid)


def build_table(latest: dict) -> Table:
    """Render the newest advertisement per device, strongest signal first."""
    table = Table(title="BLE Advertisement Monitor", header_style="bold cyan")
    # Fold the name and reserve the full address width so both can be copied as
    # a target (see scan_ble.make_table): no_wrap without a min_width lets rich
    # crop a long name or a 36-char macOS address in a narrow terminal.
    table.add_column("Name", style="green", overflow="fold", min_width=12)
    table.add_column("Identifier", style="dim", no_wrap=True, min_width=36)
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
        name = display_name(device, adv)
        table.add_row(
            name,
            device.address,
            str(adv.rssi) if adv.rssi is not None else "—",
            seen.strftime("%H:%M:%S"),
            ", ".join(_service_label(u) for u in (adv.service_uuids or [])) or "—",
            decode_manufacturer(adv) or "—",
        )
    return table


async def main() -> None:
    parser = argparse.ArgumentParser(description="Continuously monitor BLE advertisements.")
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
            return "[yellow]Waiting for advertisements...[/yellow]"
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
        # `async with scanner` stops the scanner on exit (including on Ctrl-C
        # cancellation), so there is no separate stop() to keep in sync.
        async with scanner:
            if args.timeout is None:
                await asyncio.Event().wait()  # until cancelled
            else:
                await asyncio.sleep(args.timeout)

    if latest:
        console.print(f"[dim]{len(latest)} device(s) seen.[/dim]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/yellow]")
