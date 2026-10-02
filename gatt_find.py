"""gatttool-compatible find characteristic/descriptor by UUID.

Provides `find` functionality matching bluez gatttool's `find <uuid>` command,
searching for characteristics or descriptors matching a UUID substring.
"""
import argparse
import asyncio
from bleak import BleakClient
from rich.console import Console

console = Console()

from ble_common import (
    connect,
    enumerate_services,
    find_characteristic,
    find_descriptor,
    GATTTableBuilder,
)


async def find_by_uuid(client: BleakClient, uuid_substring: str, target: str = "char") -> None:
    """Find characteristics or descriptors matching uuid substring.

    Args:
        client: Connected BleakClient
        uuid_substring: UUID substring to match (case-insensitive)
        target: "char" to find characteristics, "descr" to find descriptors
    """
    uuid_lower = uuid_substring.lower()
    builder = GATTTableBuilder(title=f"Found {target}s matching '{uuid_substring}'", header_style="bold cyan")
    builder.add_services(client)

    found = []
    for _svc, chars in builder._services:
        for ch in chars.values():
            if uuid_lower in str(ch.uuid).lower():
                found.append(ch)

    if target == "descr":
        # Also check descriptors
        for _svc, chars in builder._services:
            for ch in chars.values():
                for d in ch.descriptors:
                    if uuid_lower in str(d.uuid).lower():
                        found.append(d)

    if not found:
        console.print(f"[yellow]No {target}s found matching '{uuid_substring}'.[/yellow]")
        return

    table = builder.build()
    console.print(table)

    for item in found:
        extras = ""
        if target == "char":
            props = ", ".join(
                p.replace("-", " ").title() for p in item.properties
                if p in ("broadcast", "read", "write-without-response", "write", "notify", "indicate")
            )
            extras = f" handle={item.handle} props={props}"
        elif target == "descr":
            extras = f" uuid={item.uuid}"
        console.print(f"  [cyan]{item.uuid}[/cyan]{extras}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gatttool-compatible find characteristic/descriptor by UUID."
    )
    parser.add_argument("device", help="Device address or name")
    parser.add_argument(
        "uuid", help="UUID substring to search for (16-bit, 32-bit, or 128-bit)"
    )
    parser.add_argument(
        "--target", choices=["char", "descr"], default="char",
        help="Search target: characteristics (default) or descriptors"
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

        await find_by_uuid(client, args.uuid, args.target)

    except Exception as exc:
        console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
    finally:
        if client is not None and client.is_connected:
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())