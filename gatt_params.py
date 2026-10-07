"""Inspect (or attempt to set) a peripheral's preferred connection parameters.

The relevant object is the **Peripheral Preferred Connection Parameters**
(PPCP) *characteristic* (``0x2A04``) on the Generic Access service
(``0x1800``). It is eight bytes, little-endian, per the Bluetooth core
specification (GATT, Generic Access Profile service):

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
PPCP reports the peripheral's *preferred* parameters, not the values actually
in force. The live parameters are negotiated in HCI / over the link layer,
which CoreBluetooth does not expose to applications. Linux
``gatttool``/``btmgmt`` can read the negotiated values because they bind to
BlueZ's HCI socket.

Also note PPCP is defined read-only: a central cannot change a connection's
parameters with a GATT write (that needs an L2CAP Connection Parameter Update
Request, which CoreBluetooth does not expose either). ``--set`` therefore
attempts the write but most peripherals reject it, and even a success would not
change the live connection. ``--get`` reads and decodes the preferred values.
"""

import argparse
import asyncio
import struct
import sys

from bleak import BleakClient, normalize_uuid_str
from rich.console import Console
from rich.table import Table

from ble_common import add_connection_args, connect, describe_gatt_error, short_uuid

console = Console()

GAP_SERVICE_UUID = normalize_uuid_str("1800")
PPCP_UUID = normalize_uuid_str("2a04")  # Peripheral Preferred Connection Parameters

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


def find_ppcp_characteristic(client: BleakClient):
    """Locate the 0x2A04 PPCP characteristic (on the GAP service), or None.

    PPCP is a characteristic, not a descriptor, so match on UUID against the
    collection's characteristic index.
    """
    for char in client.services.characteristics.values():
        if str(char.uuid).casefold() == PPCP_UUID:
            return char
    return None


def show_gap_contents(client: BleakClient) -> None:
    """List what the Generic Access (0x1800) service actually exposes.

    Printed when PPCP is absent, so a negative result still tells the operator
    what the device's GAP service does contain.
    """
    gap = next(
        (s for s in client.services if str(s.uuid).casefold() == GAP_SERVICE_UUID),
        None,
    )
    if gap is None:
        console.print("[dim]No Generic Access (0x1800) service found on this device.[/dim]")
        return
    console.print("[cyan]Generic Access (0x1800) characteristics present:[/cyan]")
    for ch in gap.characteristics:
        props = ", ".join(ch.properties) or "—"
        console.print(
            f"  [magenta]{short_uuid(ch.uuid)}[/magenta] (handle {ch.handle}) [dim]{props}[/dim]"
        )


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
            "This reads (or, with --set, attempts to write) the PPCP "
            "characteristic 0x2A04 on the Generic Access service (0x1800). PPCP "
            "is read-only, so --set is usually rejected, and macOS cannot report "
            "the negotiated connection parameters in any case."
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
    add_connection_args(parser)

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

        char = find_ppcp_characteristic(client)
        if char is None:
            console.print(
                "[yellow]This device does not expose the optional Peripheral "
                "Preferred Connection Parameters characteristic (0x2A04).[/yellow]\n"
                "[dim]That is normal. Many peripherals, including most RGB LED "
                "controllers, omit it. There are no preferred parameters to read, and "
                "nothing to set; the OS negotiates the connection parameters "
                "itself and macOS does not expose the result.[/dim]"
            )
            show_gap_contents(client)
            console.print(
                f"[dim]For the device's full attribute table, run:  "
                f"enum_ble.py {args.device!r} --readable[/dim]"
            )
            return  # a legitimate negative result, not an error

        if args.get:
            try:
                raw = await client.read_gatt_char(char)
            except Exception as exc:
                console.print(
                    f"[yellow]Could not read the parameters: {describe_gatt_error(exc)}[/yellow]"
                )
                sys.exit(2)
            params = unpack_range(raw)
            if params is None:
                console.print(
                    f"[yellow]Characteristic returned {len(raw)} byte(s); expected 8.[/yellow]"
                )
                sys.exit(2)
            console.print(
                f"[cyan]Preferred connection parameters "
                f"(characteristic {char.uuid}, handle {char.handle}):[/cyan]"
            )
            console.print(describe(params))
            console.print(
                "[dim]These are the peripheral's preferred values, not the "
                "parameters in force. macOS cannot report the negotiated result.[/dim]"
            )
            return

        payload = pack_range(args.interval_min, args.interval_max, args.latency, args.timeout)
        try:
            await client.write_gatt_char(char, payload, response=True)
        except Exception as exc:
            console.print(
                f"[yellow]Write to handle {char.handle} not accepted: "
                f"{describe_gatt_error(exc)}[/yellow]"
            )
            console.print(
                "[dim]PPCP is read-only on most peripherals; this is expected. A "
                "central cannot set connection parameters via GATT.[/dim]"
            )
            sys.exit(2)

        console.print("[green]PPCP write accepted by the peripheral.[/green]")
        console.print(describe(unpack_range(payload)))
        console.print(
            "[yellow]Even when the write succeeds it only updates the preferred "
            "values; it does not change the live connection, and macOS gives no "
            "way to confirm what is in force.[/yellow]"
        )

    except Exception as exc:
        console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
        sys.exit(1)
    finally:
        if client is not None and client.is_connected:
            await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
