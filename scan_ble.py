import argparse
import asyncio
from typing import Any, Dict, List, Tuple

from bleak import BleakScanner
from rich.console import Console
from rich.table import Table

from ble_common import parse_advertisement_data, fmt_bytes

console = Console()


def make_table(
    found: Dict[str, Tuple[Any, Any]],
) -> Tuple[Table, List[Tuple[str, Any, Any]]]:
    """Build a rich table from discovered BLE advertisements.

    Returns:(table, rows) where rows are (address, device, advertisement) tuples
    sorted by RSSI descending.
    """
    table = Table(title="Nearby BLE Devices", header_style="bold cyan")
    table.add_column("#", justify="right", style="yellow")
    table.add_column("Name", style="green")
    # Keep the address on one line. Use --plain if the terminal is still too narrow.
    table.add_column("Address / Identifier", style="dim", no_wrap=True, overflow="fold")
    table.add_column("RSSI", justify="right")
    table.add_column("Connectable", justify="center")
    table.add_column("Advertised services", overflow="fold")
    table.add_column("Manufacturer data", overflow="fold")
    table.add_column("Service data", overflow="fold")

    rows: List[Tuple[str, Any, Any]] = []
    for index, (address, (device, adv)) in enumerate(
        sorted(found.items(), key=lambda item: item[1][1].rssi if item[1][1].rssi is not None else -999, reverse=True),
        start=1,
    ):
        # Parse advertisement data
        adv_data = parse_advertisement_data(adv)

        name = device.name or adv.local_name or "(unnamed)"
        connectable = "yes" if device.connectable else "no"

        # Format service UUIDs
        adv_uuids = adv.service_uuids or []
        services_str = ", ".join(
            [f"0x{uuid.uuid[-4:]}" if hasattr(uuid, "uuid") else str(uuid)[-4:] for uuid in adv_uuids]
            if adv_uuids
            else "—"
        )

        manufacturer = adv_data.get("manufacturer", "—")
        service_data = adv_data.get("service_data", {})

        # Build service data string (show first few entries)
        sd_parts = []
        for uuid_hex, data_bytes in list(service_data.items())[:3]:
            sd_parts.append(f"0x{uuid_hex[:8]}={fmt_bytes(data_bytes)[:16]}")
        service_data_str = "; ".join(sd_parts) if sd_parts else "—"

        rows.append((address, device, adv))

        table.add_row(
            str(index),
            name,
            address,
            str(adv.rssi) if adv.rssi is not None else "—",
            connectable,
            services_str,
            manufacturer,
            service_data_str,
        )

    return table, rows


async def main():
    parser = argparse.ArgumentParser(description="Scan nearby BLE advertisements.")
    parser.add_argument("-t", "--timeout", type=float, default=8, help="Scan timeout in seconds (default: 8)")
    parser.add_argument("-n", "--name", help="Only display advertisements from devices with this name substring")
    parser.add_argument("-s", "--service", help="Only display advertisements containing this service UUID (16-bit hex, e.g. '180f')")
    parser.add_argument("-m", "--min-rssi", type=int, default=None, help="Minimum RSSI filter (exclude weaker signals)")
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Plain output without rich table formatting",
    )
    parser.add_argument(
        "--write-to",
        type=str,
        default=None,
        help="Write raw discovery data to a JSON file path",
    )
    args = parser.parse_args()

    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    found: Dict[str, Tuple[Any, Any]] = {}

    def detection_callback(device, adv):
        # Filter by name substring if provided
        if args.name:
            name = device.name or adv.local_name or ""
            if args.name.casefold() not in name.casefold():
                return

        # Filter by service UUID if provided
        if args.service:
            # Normalize to lowercase 16-bit hex
            service_filter = args.service.lower().replace("0x", "")
            adv_uuids = adv.service_uuids or []
            matched = False
            for uuid in adv_uuids:
                uuid_str = str(uuid).lower().replace("-", "")
                if uuid_str.endswith(service_filter) or uuid_str == service_filter:
                    matched = True
                    break
            if not matched:
                return

        # RSSI filter
        if args.min_rssi is not None and (adv.rssi or 0) < args.min_rssi:
            return

        found[device.address] = (device, adv)

    console.print(f"[cyan]Scanning for {args.timeout:g} seconds...[/cyan]")
    scanner = BleakScanner(detection_callback=detection_callback)

    try:
        async with scanner:
            await scanner.start()
            await asyncio.sleep(args.timeout)
            await scanner.stop()
    except KeyboardInterrupt:
        console.print("[yellow]Scan interrupted.[/yellow]")
        await scanner.stop()

    table, rows = make_table(found)

    if not found and not args.name and not args.service and args.min_rssi is None:
        console.print("[yellow]No devices found.[/yellow]")
    else:
        if args.plain:
            for index, (address, device, adv) in enumerate(rows, 1):
                name = device.name or adv.local_name or "(unnamed)"
                rssi = adv.rssi if adv.rssi is not None else "—"
                print(f"{index}. {name} [{address}] RSSI: {rssi}")
        else:
            console.print(table)

    # Optionally write raw data
    if args.write_to and found:
        import json
        from datetime import datetime

        now = datetime.utcnow().isoformat()
        output = {
            "timestamp": now,
            "timeout": args.timeout,
            "device_count": len(found),
            "devices": [],
        }
        for address, (device, adv) in found.items():
            adv_data = parse_advertisement_data(adv)
            output["devices"].append(
                {
                    "address": address,
                    "name": device.name or adv.local_name or "(unnamed)",
                    "rssi": adv.rssi,
                    "connectable": device.connectable,
                    "local_name": adv.local_name,
                    "service_uuids": [str(u) for u in adv.service_uuids] if adv.service_uuids else [],
                    "manufacturer_data": adv_data.get("manufacturer", ""),
                    "service_data": adv_data.get("service_data", {}),
                }
            )
        with open(args.write_to, "w") as f:
            json.dump(output, f, indent=2)
        console.print(f"[green]Discovery data written to {args.write_to}[/green]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")