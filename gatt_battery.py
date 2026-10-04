"""gatttool-compatible battery service query.

Provides battery level query matching bluez gatttool's common usage pattern.
The Battery Service UUID is 0x180F and the Battery Level characteristic is 0x2A19.
"""
import argparse
import asyncio

from bleak import BleakClient
from bleak import normalize_uuid_str
from rich.console import Console

from ble_common import connect, enumerate_services, fmt_bytes, short_uuid

console = Console()

# Standard Battery Service UUIDs
#: Bluetooth SIG Battery Service and Battery Level characteristic.
BATTERY_SERVICE_UUID = normalize_uuid_str("180f")
BATTERY_LEVEL_UUID = normalize_uuid_str("2a19")


def find_battery_characteristic(client: BleakClient):
    """Locate the Battery Level characteristic, or None if there isn't one.

    Returns None if the device has no Battery Level characteristic *or* if GATT
    service discovery failed outright.
    """
    try:
        # bleak raises if the device exposes more than one 2A19; fall through
        # to the substring scan in that case.
        char = client.services.get_characteristic(BATTERY_LEVEL_UUID)
        if char is not None:
            return char
        # Fall back to a substring scan for vendor-specific variants.
        needle = short_uuid(BATTERY_LEVEL_UUID)
        for _svc, chars in enumerate_services(client):
            for ch in chars.values():
                if needle in str(ch.uuid).lower():
                    return ch
    except Exception:
        # Includes "Service Discovery has not been performed yet", which is what
        # bleak raises when the peripheral dropped during discovery.
        return None
    return None


async def read_battery_level(client: BleakClient) -> int | None:
    """Read the battery percentage, or None if unavailable.

    Returns an int 0-100. Per the Battery Service spec the first byte is the
    level in percent, so any value outside 0-100 means the device is not
    reporting a conforming Battery Level characteristic.
    """
    char = find_battery_characteristic(client)
    if char is None or "read" not in char.properties:
        return None
    try:
        value = await client.read_gatt_char(char)
    except Exception:
        return None
    if value and len(value) > 0:
        level = value[0]
        return level if 0 <= level <= 100 else None
    return None


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gatttool-compatible battery service query."
    )
    parser.add_argument("device", help="Device address or name")
    parser.add_argument(
        "--service", default=BATTERY_SERVICE_UUID,
        help="Battery service UUID (default: 0000180f-0000-1000-8000-00805f9b34fb)"
    )
    parser.add_argument(
        "--char", default=BATTERY_LEVEL_UUID,
        help="Battery level characteristic UUID (default: 00002a19-0000-1000-8000-00805f9b34fb)"
    )
    parser.add_argument(
        "--format", "-f", choices=["percentage", "raw", "decimal"], default="percentage",
        help="Output format (default: percentage)"
    )
    parser.add_argument(
        "--scan-timeout", type=float, default=15,
        help="Scan timeout in seconds"
    )
    parser.add_argument(
        "--connect-timeout", type=float, default=30,
        help="Connection timeout in seconds"
    )

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

        pct = await read_battery_level(client)

        if pct is not None:
            if args.format == "percentage":
                console.print(f"[green]Battery: {pct}%[/green]")
            elif args.format == "raw":
                console.print(f"[green]Raw: {pct}[/green]")
            else:
                console.print(f"[green]Battery: {pct}[/green]")
            return

        char = find_battery_characteristic(client)
        if char is None:
            console.print(
                "[yellow]Could not read a Battery Level characteristic. Either "
                "the device does not expose one, or GATT service discovery "
                "failed (it commonly drops mid-discovery).[/yellow]"
            )
            return

        console.print(
            f"[yellow]Found {char.uuid} (handle {char.handle}) but it is not "
            f"readable or did not return a valid level.[/yellow]"
        )
        if "read" in char.properties:
            try:
                raw = await client.read_gatt_char(char)
                console.print(f"  Raw: {fmt_bytes(raw)}")
            except Exception as exc:
                console.print(f"  [red]Read failed: {exc!r}[/red]")

    except Exception as exc:
        console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
    finally:
        if client is not None and client.is_connected:
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())