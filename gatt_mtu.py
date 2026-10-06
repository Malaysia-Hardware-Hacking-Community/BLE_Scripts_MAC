"""Report the negotiated ATT MTU for a connected peripheral.

macOS / Windows caveat
----------------------
On both CoreBluetooth (macOS) and WinRT (Windows) the ATT MTU is negotiated by
the OS during connection setup and is not exposed for client-side modification.
``bleak`` therefore offers ``BleakClient.mtu_size`` as a read-only property and
no way to request a specific value. ``gatttool -m`` on Linux can force an MTU
because it talks to BlueZ's HCI socket directly; there is no equivalent on
macOS or Windows.

This script reports the negotiated value. It does not attempt to set it.

On Linux/BlueZ ``mtu_size`` always reports 23 regardless of the real value, so
the output there reflects the protocol minimum, not the link's MTU.
"""

import argparse
import asyncio
import sys

from bleak import BleakClient
from rich.console import Console
from rich.table import Table

from ble_common import add_connection_args, connect

console = Console()

#: ATT minimum: a Write Command can carry 20 bytes of payload.
ATT_MIN_MTU = 23


def get_mtu(client: BleakClient) -> int:
    """Return the negotiated ATT MTU in bytes.

    ``BleakClient.mtu_size`` is a read-only property in bleak >= 1.0; the older
    ``client._mtu`` attribute this script used to read does not exist.
    """
    return int(client.mtu_size)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report the negotiated GATT MTU for a connected device.",
        epilog=(
            "The MTU is negotiated by the OS and cannot be set from Python. "
            "On Linux/BlueZ this always reports 23."
        ),
    )
    parser.add_argument("device", help="Device address or name")
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
            sys.exit(1)

        mtu = get_mtu(client)

        table = Table(title=f"ATT MTU — {args.device}", header_style="bold cyan")
        table.add_column("Property", style="green")
        table.add_column("Value", justify="right")
        table.add_row("Negotiated MTU", f"{mtu} bytes")
        table.add_row("Max payload per PDU", f"{max(0, mtu - 3)} bytes")
        table.add_row("Spec minimum", f"{ATT_MIN_MTU} bytes")
        console.print(table)

        if sys.platform == "darwin":
            console.print(
                "[dim]CoreBluetooth negotiates this automatically; "
                "it cannot be set from Python.[/dim]"
            )
        elif sys.platform.startswith("win"):
            console.print(
                "[dim]WinRT negotiates this automatically; it cannot be set from Python.[/dim]"
            )
        elif sys.platform.startswith("linux"):
            console.print(
                "[yellow]BlueZ reports the 23-byte protocol minimum through "
                "bleak, not the real link MTU.[/yellow]"
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
