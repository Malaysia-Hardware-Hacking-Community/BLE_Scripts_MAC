import argparse
import asyncio

from rich.console import Console
from rich.table import Table

from ble_common import connect, decode_bytes, fmt_bytes

console = Console()

DEVICE_INFO_UUID = "0000180a-0000-1000-8000-00805f9b34fb"

FIELDS = {
    "00002a29-0000-1000-8000-00805f9b34fb": "Manufacturer Name",
    "00002a24-0000-1000-8000-00805f9b34fb": "Model Number",
    "00002a25-0000-1000-8000-00805f9b34fb": "Serial Number",
    "00002a26-0000-1000-8000-00805f9b34fb": "Firmware Revision",
    "00002a27-0000-1000-8000-00805f9b34fb": "Hardware Revision",
    "00002a28-0000-1000-8000-00805f9b34fb": "Software Revision",
    "00002a23-0000-1000-8000-00805f9b34fb": "System ID",
    "00002a2a-0000-1000-8000-00805f9b34fb": "IEEE Certification",
    "00002a50-0000-1000-8000-00805f9b34fb": "PnP ID",
}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("device")
    parser.add_argument("--scan-timeout", type=float, default=15)
    args = parser.parse_args()

    client = None
    try:
        client = await connect(args.device, args.scan_timeout)
        chars = {
            char.uuid.casefold(): char
            for service in client.services
            if service.uuid.casefold() == DEVICE_INFO_UUID
            for char in service.characteristics
        }

        table = Table(title="Device Information", header_style="bold cyan")
        table.add_column("Field", style="green")
        table.add_column("Value")
        table.add_column("Raw bytes", style="dim")

        if not chars:
            console.print(
                "[yellow]Device does not expose the standard Device Information service.[/yellow]"
            )
            return

        for uuid, label in FIELDS.items():
            char = chars.get(uuid)
            if char is None:
                continue
            if "read" not in char.properties:
                table.add_row(label, "(not readable)", "—")
                continue
            try:
                raw = await client.read_gatt_char(char)
                table.add_row(label, decode_bytes(raw) or "(binary)", fmt_bytes(raw))
            except Exception as exc:
                table.add_row(label, f"{type(exc).__name__}: {exc}", "—")

        console.print(table)
    except Exception as exc:
        console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
    finally:
        if client and client.is_connected:
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
