"""gatttool-compatible battery service query.

Provides battery level query matching bluez gatttool's common usage pattern.
The Battery Service UUID is 0x180F and the Battery Level characteristic is 0x2A19.
"""

import argparse
import asyncio

from bleak import BleakClient, normalize_uuid_str
from rich.console import Console

from ble_common import add_connection_args, connect, enumerate_services, fmt_bytes, short_uuid

console = Console()

# Standard Battery Service UUIDs
#: Bluetooth SIG Battery Service and Battery Level characteristic.
BATTERY_SERVICE_UUID = normalize_uuid_str("180f")
BATTERY_LEVEL_UUID = normalize_uuid_str("2a19")


def find_battery_characteristic(client: BleakClient, char_uuid: str = BATTERY_LEVEL_UUID):
    """Locate the Battery Level characteristic, or None if there isn't one.

    *char_uuid* is the characteristic to look for (defaults to 0x2A19); it may
    be a full 128-bit UUID, a 16-bit short form, or a substring. Returns None if
    the device has no matching characteristic *or* if GATT service discovery
    failed outright.
    """
    needle = str(char_uuid).lower()
    try:
        # bleak raises if the device exposes more than one match; fall through
        # to the substring scan in that case.
        try:
            char = client.services.get_characteristic(char_uuid)
            if char is not None:
                return char
        except Exception:
            pass
        # Fall back to a substring scan (handles short forms and vendor variants).
        canon = short_uuid(needle)
        for _svc, chars in enumerate_services(client):
            for ch in chars.values():
                uuid_l = str(ch.uuid).lower()
                if needle in uuid_l or canon == short_uuid(uuid_l):
                    return ch
    except Exception:
        # Includes "Service Discovery has not been performed yet", which is what
        # bleak raises when the peripheral dropped during discovery.
        return None
    return None


async def read_battery_raw(client: BleakClient, char_uuid: str = BATTERY_LEVEL_UUID):
    """Read the Battery Level characteristic, returning (char, raw_bytes).

    *char* is None when no matching characteristic exists; *raw_bytes* is None
    when it exists but is not readable or the read failed.
    """
    char = find_battery_characteristic(client, char_uuid)
    if char is None or "read" not in char.properties:
        return char, None
    try:
        return char, bytes(await client.read_gatt_char(char))
    except Exception:
        return char, None


async def main() -> None:
    parser = argparse.ArgumentParser(description="Gatttool-compatible battery service query.")
    parser.add_argument("device", help="Device address or name")
    parser.add_argument(
        "--service",
        default=BATTERY_SERVICE_UUID,
        help="Battery service UUID (default: 0000180f-0000-1000-8000-00805f9b34fb)",
    )
    parser.add_argument(
        "--char",
        default=BATTERY_LEVEL_UUID,
        help="Battery level characteristic UUID (default: 00002a19-0000-1000-8000-00805f9b34fb)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["percentage", "raw", "decimal"],
        default="percentage",
        help="Output format (default: percentage)",
    )
    add_connection_args(parser)

    args = parser.parse_args()

    client = None
    try:
        client = await connect(
            args.device,
            args.scan_timeout,
            args.connect_timeout,
        )
        if client is None:
            console.print("[red]Failed to connect.[/red]")
            return

        console.print(f"[cyan]Reading battery from {args.device}...[/cyan]")

        char, raw = await read_battery_raw(client, args.char)

        if char is None:
            console.print(
                "[yellow]Could not find a Battery Level characteristic. Either "
                "the device does not expose one, or GATT service discovery "
                "failed (it commonly drops mid-discovery).[/yellow]"
            )
            return

        if raw is None or len(raw) == 0:
            console.print(
                f"[yellow]Found {char.uuid} (handle {char.handle}) but it is not "
                f"readable or returned no data.[/yellow]"
            )
            return

        # Per the Battery Service spec the first byte is the level in percent.
        level = raw[0]
        if args.format == "raw":
            console.print(f"[green]Raw: {fmt_bytes(raw)}[/green]")
        elif args.format == "decimal":
            console.print(f"[green]Battery: {level}[/green]")
        else:  # percentage
            if 0 <= level <= 100:
                console.print(f"[green]Battery: {level}%[/green]")
            else:
                console.print(
                    f"[yellow]Level byte {level} is outside 0-100 (non-conforming); "
                    f"raw {fmt_bytes(raw)}.[/yellow]"
                )

    except Exception as exc:
        console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
    finally:
        if client is not None and client.is_connected:
            await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
