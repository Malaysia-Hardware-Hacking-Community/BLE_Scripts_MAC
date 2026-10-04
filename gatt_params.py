"""Request a connection-parameter range from a peripheral.

The relevant object is the **Connection Parameter Range** *descriptor*
(``0x2A0E``) on the GAP service (``0x1800``). It is eight bytes, little-endian,
per the Bluetooth core specification Vol 3, Part G, 7.8.5:

===========  ======  =============================
Offset       Field   Meaning
===========  ======  =============================
0x00-0x01    MIN     minimum conn interval, 1.25 ms units
0x02-0x03    MAX     maximum conn interval, 1.25 ms units
0x04-0x05    LAT     peripheral latency, in events
0x06-0x07    TIMEOUT supervision timeout, 10 ms units
===========  ======  =============================

macOS caveat
------------
Writing this descriptor is only a *request*: the peripheral may accept,
ignore, or clamp it. The values actually in force are negotiated in HCI and
reported over the link layer, which CoreBluetooth does not expose to
applications. Linux ``gatttool``/``btmgmt`` can read them back because they
bind to BlueZ's HCI socket.

So this script can *request* a range but cannot *report* what was applied.
``--get`` says so rather than printing numbers it did not measure.
"""

import argparse
import asyncio
import struct
import sys

from bleak import BleakClient, normalize_uuid_str
from rich.console import Console
from rich.table import Table

from ble_common import connect

console = Console()

GAP_SERVICE_UUID = normalize_uuid_str("1800")
CONN_PARAM_RANGE_UUID = normalize_uuid_str("2a0e")

INTERVAL_UNIT_MS = 1.25
TIMEOUT_UNIT_MS = 10.0

#: Spec-mandated ranges for a Connection Parameter Range request.
INTERVAL_MIN_ALLOWED = 6
INTERVAL_MAX_ALLOWED = 3200
LATENCY_MIN_ALLOWED = 0
LATENCY_MAX_ALLOWED = 499
TIMEOUT_MIN_ALLOWED = 100
TIMEOUT_MAX_ALLOWED = 3200


def pack_range(interval_min: int, interval_max: int, latency: int, timeout: int) -> bytes:
    """Pack the four fields into the 8-byte little-endian descriptor value."""
    return struct.pack("<HHHH", interval_min, interval_max, latency, timeout)


def unpack_range(value: bytes) -> dict | None:
    """Parse an 8-byte descriptor value, or None if it is not 8 bytes."""
    if value is None or len(value) < 8:
        return None
    i_min, i_max, latency, timeout = struct.unpack("<HHHH", bytes(value[:8]))
    return {
        "interval_min": i_min,
        "interval_max": i_max,
        "latency": latency,
        "timeout": timeout,
        "interval_min_ms": i_min * INTERVAL_UNIT_MS,
        "interval_max_ms": i_max * INTERVAL_UNIT_MS,
        "timeout_ms": timeout * TIMEOUT_UNIT_MS,
    }


def find_conn_param_descriptor(client: BleakClient):
    """Locate the 0x2A0E descriptor on the GAP service, or None.

    ``BleakGATTServiceCollection.get_descriptor`` only accepts an integer
    handle, so match on UUID against the collection's descriptor index.
    """
    for desc in client.services.descriptors.values():
        if str(desc.uuid).casefold() == CONN_PARAM_RANGE_UUID:
            return desc
    return None


def describe(params: dict) -> Table:
    table = Table(header_style="bold cyan", show_header=True)
    table.add_column("Field", style="green")
    table.add_column("Raw", justify="right")
    table.add_column("Actual")
    table.add_row(
        "Conn interval min",
        str(params["interval_min"]),
        f"{params['interval_min_ms']:.2f} ms",
    )
    table.add_row(
        "Conn interval max",
        str(params["interval_max"]),
        f"{params['interval_max_ms']:.2f} ms",
    )
    table.add_row("Peripheral latency", str(params["latency"]), f"{params['latency']} events")
    table.add_row(
        "Supervision timeout",
        str(params["timeout"]),
        f"{params['timeout_ms']:.0f} ms",
    )
    return table


def validate(args, parser) -> None:
    checks = (
        ("--interval-min", args.interval_min, INTERVAL_MIN_ALLOWED, INTERVAL_MAX_ALLOWED),
        ("--interval-max", args.interval_max, INTERVAL_MIN_ALLOWED, INTERVAL_MAX_ALLOWED),
        ("--latency", args.latency, LATENCY_MIN_ALLOWED, LATENCY_MAX_ALLOWED),
        ("--timeout", args.timeout, TIMEOUT_MIN_ALLOWED, TIMEOUT_MAX_ALLOWED),
    )
    for name, value, lo, hi in checks:
        if not lo <= value <= hi:
            parser.error(f"{name} must be between {lo} and {hi} (got {value})")
    if args.interval_min > args.interval_max:
        parser.error("--interval-min must not exceed --interval-max")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Request or inspect a peripheral's connection parameter range.",
        epilog=(
            "This writes descriptor 0x2A0E on the GAP service (0x1800). The "
            "peripheral may ignore the request, and macOS cannot report the "
            "negotiated result."
        ),
    )
    parser.add_argument("device", help="Device address or name")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--get",
        action="store_true",
        help="Read the range the peripheral currently advertises",
    )
    mode.add_argument(
        "--set",
        action="store_true",
        help="Request a new connection parameter range",
    )
    parser.add_argument(
        "--interval-min",
        type=int,
        default=8,
        help=f"Conn interval min, 1.25 ms units, {INTERVAL_MIN_ALLOWED}-{INTERVAL_MAX_ALLOWED} (default: 8)",
    )
    parser.add_argument(
        "--interval-max",
        type=int,
        default=16,
        help=f"Conn interval max, 1.25 ms units, {INTERVAL_MIN_ALLOWED}-{INTERVAL_MAX_ALLOWED} (default: 16)",
    )
    parser.add_argument(
        "--latency",
        type=int,
        default=0,
        help=f"Peripheral latency in events, {LATENCY_MIN_ALLOWED}-{LATENCY_MAX_ALLOWED} (default: 0)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=400,
        help=f"Supervision timeout, 10 ms units, {TIMEOUT_MIN_ALLOWED}-{TIMEOUT_MAX_ALLOWED} (default: 400 = 4 s)",
    )
    parser.add_argument(
        "--scan-timeout", type=float, default=15, help="Scan timeout in seconds (default: 15)"
    )
    parser.add_argument(
        "--connect-timeout", type=float, default=30, help="Connection timeout in seconds (default: 30)"
    )

    args = parser.parse_args()

    if args.set:
        validate(args, parser)

    if not args.get and not args.set:
        parser.print_help()
        return

    client = None
    try:
        client = await connect(
            args.device,
            args.scan_timeout,
            args.connect_timeout,
        )
        if client is None:
            sys.exit(1)

        desc = find_conn_param_descriptor(client)
        if desc is None:
            console.print(
                "[red]Device does not expose a Connection Parameter Range "
                "descriptor (0x2A0E) on its GAP service.[/red]"
            )
            sys.exit(2)

        if args.get:
            try:
                raw = await client.read_gatt_descriptor(desc)
            except Exception as exc:
                console.print(f"[red]Read failed: {exc!r}[/red]")
                sys.exit(2)
            params = unpack_range(raw)
            if params is None:
                console.print(
                    f"[yellow]Descriptor returned {len(raw)} byte(s); expected 8.[/yellow]"
                )
                sys.exit(2)
            console.print(
                f"[cyan]Advertised connection parameter range "
                f"(descriptor {desc.uuid}, handle {desc.handle}):[/cyan]"
            )
            console.print(describe(params))
            console.print(
                "[dim]These are the range the peripheral advertises, not the "
                "values in force. macOS cannot report the negotiated result.[/dim]"
            )
            return

        payload = pack_range(args.interval_min, args.interval_max, args.latency, args.timeout)
        try:
            await client.write_gatt_descriptor(desc, payload)
        except Exception as exc:
            console.print(f"[red]Write to descriptor {desc.handle} failed: {exc!r}[/red]")
            sys.exit(2)

        console.print("[green]Connection parameter range requested.[/green]")
        console.print(describe(unpack_range(payload)))
        console.print(
            "[yellow]The peripheral may clamp or ignore this. macOS gives no "
            "way to confirm what was applied.[/yellow]"
        )

    except Exception as exc:
        console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
        sys.exit(1)
    finally:
        if client is not None and client.is_connected:
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())