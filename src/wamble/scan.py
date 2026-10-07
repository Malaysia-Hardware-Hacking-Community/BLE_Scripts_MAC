import argparse
import asyncio
import csv
import json
from datetime import UTC, datetime
from typing import Any

from bleak import BleakScanner
from rich.console import Console
from rich.table import Table

from wamble.common import parse_advertisement_data, short_uuid

console = Console()


def service_uuid_matches(service_filter: str, adv_service_uuids) -> bool:
    """True if any advertised service UUID matches *service_filter*.

    macOS CoreBluetooth reports SIG UUIDs in their full 128-bit form
    (e.g. ``0000180f-0000-1000-8000-00805f9b34fb``) while users habitually type
    the 16-bit short form (``180f``); Linux advertises the short form directly.
    So the filter and each advertised UUID are reduced to the same canonical
    form with :func:`short_uuid` before comparing, which makes ``"180f"``,
    ``"0x180F"`` and the full 128-bit UUID all match the same device in either
    direction.

    The comparison is on the whole UUID, not a substring: a substring test
    against the 128-bit form would make fragments of the Bluetooth base suffix
    (``1000``, ``8000``, ``34fb`` …) match every SIG device.
    """
    needle = service_filter.strip().casefold()
    needle = needle.removeprefix("0x")
    if not needle:
        return False
    needle_canon = short_uuid(needle).casefold()
    for uuid in adv_service_uuids or []:
        if needle == str(uuid).casefold():  # exact, as the user typed it
            return True
        if needle_canon == short_uuid(uuid).casefold():  # 16-bit <-> 128-bit
            return True
    return False


def make_table(
    found: dict[str, tuple[Any, Any]],
) -> tuple[Table, list[tuple[str, Any, Any]]]:
    """Build a rich table from discovered BLE advertisements.

    Returns:(table, rows) where rows are (address, device, advertisement) tuples
    sorted by RSSI descending.
    """
    table = Table(title="Nearby BLE Devices", header_style="bold cyan")
    table.add_column("#", justify="right", style="yellow")
    # Fold rather than ellipsize the name: a truncated "SomeName…" cannot be
    # copied back in as a target, which is the whole point of the column.
    table.add_column("Name", style="green", overflow="fold", min_width=12)
    # Reserve the full width of an address (a 36-char macOS CoreBluetooth UUID,
    # or a 17-char MAC on Win/Linux) so it is shown complete on one line and can
    # be copied verbatim. no_wrap without a min_width lets rich crop it in a
    # narrow terminal, which yields an unusable, truncated identifier.
    table.add_column("Address / Identifier", style="dim", no_wrap=True, min_width=36)
    table.add_column("RSSI", justify="right")
    table.add_column("Advertised services", overflow="fold")
    table.add_column("Manufacturer data", overflow="fold")
    table.add_column("Service data", overflow="fold")

    rows: list[tuple[str, Any, Any]] = []
    for index, (address, (device, adv)) in enumerate(
        sorted(
            found.items(),
            key=lambda item: item[1][1].rssi if item[1][1].rssi is not None else -999,
            reverse=True,
        ),
        start=1,
    ):
        # Parse advertisement data
        adv_data = parse_advertisement_data(adv)

        name = device.name or adv.local_name or "(unnamed)"

        # Format service UUIDs
        adv_uuids = adv.service_uuids or []
        services_str = ", ".join(short_uuid(u) for u in adv_uuids) or "—"

        manufacturer = adv_data.get("manufacturer") or "—"
        service_data = adv_data.get("service_data", {})

        # Show at most the first three service-data entries.
        # parse_advertisement_data already returns hex strings, so don't re-format.
        sd_parts = [f"0x{u[:8]}={data[:16]}" for u, data in list(service_data.items())[:3]]
        service_data_str = "; ".join(sd_parts) or "—"

        rows.append((address, device, adv))

        table.add_row(
            str(index),
            name,
            address,
            str(adv.rssi) if adv.rssi is not None else "—",
            services_str,
            manufacturer,
            service_data_str,
        )

    return table, rows


#: The column order shared by the CSV writer and its header row.
CSV_FIELDS = [
    "address",
    "name",
    "rssi",
    "local_name",
    "service_uuids",
    "manufacturer_data",
    "service_data",
]


def build_device_record(address: str, device: Any, adv: Any) -> dict:
    """One device's discovery data, shared by the JSON and CSV writers.

    Keeping this in one place means the two export formats never drift apart on
    which fields they carry.
    """
    adv_data = parse_advertisement_data(adv)
    return {
        "address": address,
        "name": device.name or adv.local_name or "(unnamed)",
        "rssi": adv.rssi,
        "local_name": adv.local_name,
        "service_uuids": adv_data["service_uuids"],
        "manufacturer_data": adv_data["manufacturer"],
        "service_data": adv_data["service_data"],
    }


def csv_row(record: dict) -> dict:
    """Flatten a device record's lists and dicts into CSV-safe string cells.

    A CSV cell cannot hold a list or a dict, so the advertised service UUIDs are
    joined with ``;`` and the service data is rendered as ``uuid=hex`` pairs. An
    absent RSSI becomes an empty cell rather than the word "None".
    """
    service_data = record["service_data"]
    return {
        **record,
        "rssi": "" if record["rssi"] is None else record["rssi"],
        "local_name": record["local_name"] or "",
        "service_uuids": ";".join(record["service_uuids"]),
        "service_data": ";".join(f"{uuid}={data}" for uuid, data in service_data.items()),
    }


def write_csv(path: str, records: list[dict]) -> None:
    """Write device records to *path* as CSV with a header row."""
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(csv_row(record))


def write_exports(
    found: dict[str, tuple[Any, Any]],
    *,
    json_path: str | None,
    csv_path: str | None,
    timeout: float,
) -> None:
    """Write the discovery results to the requested file formats, if any.

    Both formats draw from the same per-device records, so JSON and CSV always
    carry identical fields. Does nothing when no output path was given or no
    device was found.
    """
    if not (json_path or csv_path) or not found:
        return

    records = [
        build_device_record(address, device, adv) for address, (device, adv) in found.items()
    ]

    if json_path:
        output = {
            # datetime.utcnow() is deprecated since 3.12; use an explicit UTC tz.
            "timestamp": datetime.now(UTC).isoformat(),
            "timeout": timeout,
            "device_count": len(records),
            "devices": records,
        }
        with open(json_path, "w") as f:
            json.dump(output, f, indent=2)
        console.print(f"[green]Discovery data written to {json_path}[/green]")

    if csv_path:
        write_csv(csv_path, records)
        console.print(f"[green]Discovery data written to {csv_path}[/green]")


async def main():
    parser = argparse.ArgumentParser(description="Scan nearby BLE advertisements.")
    parser.add_argument(
        "-t", "--timeout", type=float, default=8, help="Scan timeout in seconds (default: 8)"
    )
    parser.add_argument(
        "-n", "--name", help="Only display advertisements from devices with this name substring"
    )
    parser.add_argument(
        "-s",
        "--service",
        help="Only display advertisements containing this service UUID (16-bit hex, e.g. '180f')",
    )
    parser.add_argument(
        "-m",
        "--min-rssi",
        type=int,
        default=None,
        help="Minimum RSSI filter (exclude weaker signals)",
    )
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
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Write discovery data to a CSV file path (one row per device)",
    )
    args = parser.parse_args()

    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    found: dict[str, tuple[Any, Any]] = {}

    def detection_callback(device, adv):
        # Filter by name substring if provided
        if args.name:
            name = device.name or adv.local_name or ""
            if args.name.casefold() not in name.casefold():
                return

        # Filter by service UUID if provided. See service_uuid_matches for why
        # a plain endswith() is wrong on macOS.
        if args.service and not service_uuid_matches(args.service, adv.service_uuids):
            return

        # RSSI filter
        if args.min_rssi is not None and (adv.rssi or 0) < args.min_rssi:
            return

        found[device.address] = (device, adv)

    console.print(f"[cyan]Scanning for {args.timeout:g} seconds...[/cyan]")
    scanner = BleakScanner(detection_callback=detection_callback)

    # `async with` starts the scanner on entry and stops it on exit, so there is
    # no explicit start()/stop() pair to keep in sync with Ctrl-C handling.
    try:
        async with scanner:
            async with asyncio.timeout(args.timeout):
                await asyncio.Event().wait()
    except TimeoutError:
        pass  # normal: the scan ran for its full requested duration
    except KeyboardInterrupt:
        if console.is_terminal:
            console.print("[yellow]Scan interrupted.[/yellow]")

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

    write_exports(found, json_path=args.write_to, csv_path=args.csv, timeout=args.timeout)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
