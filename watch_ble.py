import argparse
import asyncio
from datetime import datetime

from bleak import BleakScanner
from rich.console import Console
from rich.table import Table

console = Console()


async def main():
    parser = argparse.ArgumentParser(
        description="Continuously monitor BLE advertisements."
    )
    parser.add_argument("--name", help="Only display names containing this text.")
    args = parser.parse_args()

    latest = {}

    def callback(device, adv):
        name = device.name or adv.local_name or "(unnamed)"
        if args.name and args.name.casefold() not in name.casefold():
            return
        latest[device.address] = (device, adv, datetime.now())

    scanner = BleakScanner(detection_callback=callback)
    console.print("[cyan]Monitoring advertisements; press Ctrl-C to stop.[/cyan]")

    try:
        async with scanner:
            while True:
                await asyncio.sleep(2)
                table = Table(
                    title="BLE Advertisement Monitor", header_style="bold cyan"
                )
                table.add_column("Name", style="green")
                table.add_column("Identifier", style="dim")
                table.add_column("RSSI", justify="right")
                table.add_column("Last seen")
                table.add_column("Services", overflow="fold")

                for device, adv, seen in sorted(
                    latest.values(),
                    key=lambda item: item[1].rssi if item[1].rssi is not None else -999,
                    reverse=True,
                ):
                    table.add_row(
                        device.name or adv.local_name or "(unnamed)",
                        device.address,
                        str(adv.rssi) if adv.rssi is not None else "—",
                        seen.strftime("%H:%M:%S"),
                        ", ".join(adv.service_uuids) or "—",
                    )

                console.clear()
                console.print(
                    table
                    if latest
                    else "[yellow]Waiting for advertisements...[/yellow]"
                )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
