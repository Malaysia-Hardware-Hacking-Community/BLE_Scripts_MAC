"""gatttool-compatible find characteristic/descriptor by UUID.

Provides `find` functionality matching bluez gatttool's `find <uuid>` command,
searching for characteristics or descriptors matching a UUID substring.
"""

import argparse
import asyncio

from bleak import BleakClient
from rich.console import Console
from rich.table import Table

from ble_common import (
    add_connection_args,
    connect,
    enumerate_services,
    format_properties,
    short_uuid,
    uuid_name,
)

console = Console()


async def find_by_uuid(client: BleakClient, uuid_substring: str, target: str = "char") -> None:
    """Find characteristics or descriptors matching uuid substring.

    Args:
        client: Connected BleakClient
        uuid_substring: UUID substring to match (case-insensitive)
        target: "char" to find characteristics, "descr" to find descriptors
    """
    uuid_lower = uuid_substring.lower()
    services = enumerate_services(client)

    if target == "char":
        found = [
            ch
            for _svc, chars in services
            for ch in chars.values()
            if uuid_lower in str(ch.uuid).lower()
        ]
    else:  # descr: search descriptors only, never characteristics
        found = [
            d
            for _svc, chars in services
            for ch in chars.values()
            for d in ch.descriptors
            if uuid_lower in str(d.uuid).lower()
        ]

    if not found:
        console.print(f"[yellow]No {target}s found matching '{uuid_substring}'.[/yellow]")
        return

    # Only list what actually matched; printing the whole GATT table here would
    # bury the answer the user asked for.
    noun = "Characteristics" if target == "char" else "Descriptors"
    table = Table(title=f"{noun} matching '{uuid_substring}'")
    table.add_column("UUID", style="cyan", no_wrap=True)
    table.add_column("Name", style="blue", overflow="fold")
    table.add_column("Handle", justify="right", style="dim")
    if target == "char":
        table.add_column("Properties", justify="center", style="green")

    for item in found:
        if target == "char":
            table.add_row(
                short_uuid(item.uuid),
                uuid_name(item.uuid, "—"),
                str(item.handle),
                format_properties(item.properties),
            )
        else:
            table.add_row(short_uuid(item.uuid), uuid_name(item.uuid, "—"), str(item.handle))

    console.print(table)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gatttool-compatible find characteristic/descriptor by UUID."
    )
    parser.add_argument("device", help="Device address or name")
    parser.add_argument("uuid", help="UUID substring to search for (16-bit, 32-bit, or 128-bit)")
    parser.add_argument(
        "--target",
        choices=["char", "descr"],
        default="char",
        help="Search target: characteristics (default) or descriptors",
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

        await find_by_uuid(client, args.uuid, args.target)

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
