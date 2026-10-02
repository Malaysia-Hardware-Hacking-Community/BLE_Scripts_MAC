"""gatttool-compatible battery service query.

Provides battery level query matching bluez gatttool's common usage pattern.
The Battery Service UUID is 0x180F and the Battery Level characteristic is 0x2A19.
"""
import argparse
import asyncio
from bleak import BleakClient
from rich.console import Console

console = Console()

# Standard Battery Service UUIDs
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

# Also common 16-bit equivalents
BATTERY_SERVICE_16 = "180f"
BATTERY_LEVEL_16 = "2a19"


async def read_battery_level(client: BleakClient, device_address: str) -> int | None:
    """Read battery level from the connected device.

    Returns battery percentage (0-100) or None if not found/error.
    """
    try:
        # Try reading by standard 128-bit UUID
        value = await client.read_gatt_char(BATTERY_LEVEL_UUID)
        # First byte is the battery percentage
        if isinstance(value, (bytes, bytearray)) and len(value) > 0:
            percentage = value[0]
            if 0 <= percentage <= 100:
                return percentage
        # Try decoding as text
        text = value.decode("utf-8", errors="replace").strip()
        if text.isdigit():
            pct = int(text)
            if 0 <= pct <= 100:
                return pct
        return None
    except Exception:
        # Try 16-bit UUID
        try:
            value = await client.read_gatt_char(BATTERY_LEVEL_16)
            if isinstance(value, (bytes, bytearray)) and len(value) > 0:
                percentage = value[0]
                if 0 <= percentage <= 100:
                    return percentage
        except Exception:
            pass
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
        from ble_common import connect
        client = await connect(
            args.device,
            args.scan_timeout,
            args.connect_timeout,
        )
        if client is None:
            console.print("[red]Failed to connect.[/red]")
            return

        console.print(f"[cyan]Reading battery from {args.device}...[/cyan]")

        # Try to read battery level
        pct = await read_battery_level(client, args.device)

        if pct is not None:
            if args.format == "percentage":
                console.print(f"[green]Battery: {pct}%[/green]")
            elif args.format == "raw":
                console.print(f"[green]Raw: {pct}[/green]")
            elif args.format == "decimal":
                console.print(f"[green]Battery: {pct}[/green]")
        else:
            # Try finding the characteristic dynamically
            console.print(
                f"[yellow]No standard battery level characteristic found via UUID {args.char}.[/yellow]"
            )
            # List services looking for battery
            from ble_common import enumerate_services
            services = enumerate_services(client)
            found_battery = False
            for svc_uuid, chars in services:
                for ch_uuid, ch in chars.items():
                    if "2a19" in str(ch_uuid).lower() or "180f" in str(svc_uuid).lower():
                        found_battery = True
                        try:
                            val = await client.read_gatt_char(ch_uuid)
                            console.print(
                                f"[cyan]Found battery char {ch_uuid}: "
                                f"{' '.join(fmt_bytes(val) if hasattr(__import__('ble_common', 'ble_common'), 'fmt_bytes') else val)}[/cyan]"
                            )
                        except Exception:
                            pass

            if not found_battery:
                console.print(
                    "[dim]Device does not appear to have a standard battery service.[/dim]"
                )

    except Exception as exc:
        console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
    finally:
        if client is not None and client.is_connected:
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())