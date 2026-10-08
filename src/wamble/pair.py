"""Pair or unpair a BLE device (``wamble-pair``).

Pairing (the Security Manager key exchange) is always performed by the operating
system: an app never implements SMP itself, because neither macOS CoreBluetooth
nor Windows WinRT exposes the raw SMP/L2CAP channel (this is why `gatttool` can do
explicit pairing on Linux, which does expose it, and WAMBLE cannot on the built-in
radio - see ``docs/ROADMAP.md``). This tool therefore *drives* the OS pairing and
reports the result, which works on both target platforms:

* **Windows**: `bleak.pair()` calls the WinRT pairing API directly.
* **macOS**: there is no explicit pairing call, so CoreBluetooth auto-pairs on the
  first access to an encryption-protected characteristic. Pass ``--char`` with such
  a characteristic and the tool reads it to trigger that pairing.

Unpairing is programmatic only where the OS allows it (`bleak.unpair()` on Windows
and Linux); on macOS the tool tells you to remove the device in System Settings.

The platform logic and the pair/unpair decisions are kept free of real Bluetooth
I/O so they can be unit-tested with a fake client.
"""

import argparse
import asyncio
import sys
from typing import Any

from rich.console import Console

from wamble.common import add_connection_args, connect, describe_gatt_error, find_characteristic

console = Console()


def pairing_support(platform: str) -> dict:
    """Describe how pairing works on *platform* (a ``sys.platform`` string).

    Returns ``{explicit_pair, explicit_unpair, note}``: whether the platform has a
    direct pair/unpair API, and a one-line explanation shown to the user.
    """
    if platform.startswith("win"):
        return {
            "explicit_pair": True,
            "explicit_unpair": True,
            "note": "Windows pairs and unpairs through the WinRT pairing API.",
        }
    if platform == "darwin":
        return {
            "explicit_pair": False,
            "explicit_unpair": False,
            "note": (
                "macOS has no explicit pairing API: CoreBluetooth auto-pairs on the first "
                "access to an encryption-protected characteristic (use --char), and "
                "unpairing is done in System Settings > Bluetooth."
            ),
        }
    return {
        "explicit_pair": True,
        "explicit_unpair": True,
        "note": "Linux/BlueZ pairs and unpairs through the OS pairing agent.",
    }


async def attempt_pair(client: Any, trigger_char: Any = None) -> tuple[str, str]:
    """Drive OS pairing. Returns ``(status, detail)``.

    status is one of:
    ``"paired"`` (the explicit OS API did it), ``"triggered"`` (an encrypted read
    kicked off the OS auto-pairing), ``"manual"`` (no explicit API and no trigger
    characteristic was given), or ``"failed"``.
    """
    try:
        await client.pair()
        return ("paired", "Paired through the OS pairing API.")
    except NotImplementedError:
        if trigger_char is None:
            return (
                "manual",
                "No explicit pairing API on this platform. Re-run with --char <uuid> of an "
                "encryption-protected characteristic to trigger the OS auto-pairing.",
            )
        try:
            await client.read_gatt_char(trigger_char)
        except Exception as exc:
            return ("failed", f"could not trigger pairing: {describe_gatt_error(exc)}")
        return ("triggered", "Read an encrypted characteristic; the OS handled pairing.")
    except Exception as exc:
        return ("failed", str(exc) or type(exc).__name__)


async def attempt_unpair(client: Any) -> tuple[str, str]:
    """Unpair through the OS. Returns ``(status, detail)``.

    status is ``"unpaired"``, ``"manual"`` (platform has no programmatic unpair),
    or ``"failed"``.
    """
    try:
        await client.unpair()
        return ("unpaired", "Unpaired through the OS.")
    except NotImplementedError:
        return (
            "manual",
            "This platform cannot unpair programmatically; remove the device in the OS "
            "Bluetooth settings (on macOS: System Settings > Bluetooth).",
        )
    except Exception as exc:
        return ("failed", str(exc) or type(exc).__name__)


#: Colour per outcome word, for the printed result.
_STATUS_STYLE = {
    "paired": "bold green",
    "triggered": "green",
    "unpaired": "bold green",
    "manual": "yellow",
    "failed": "red",
}


def _report(status: str, detail: str) -> None:
    style = _STATUS_STYLE.get(status, "white")
    console.print(f"[{style}]{status}:[/{style}] {detail}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Pair or unpair a BLE device via the OS.")
    parser.add_argument("device", help="Device address or name (or @alias)")
    parser.add_argument(
        "--unpair", action="store_true", help="Unpair instead of pair (Windows/Linux only)"
    )
    parser.add_argument(
        "--char",
        default=None,
        help="Characteristic UUID to read to trigger pairing on macOS (an encrypted one)",
    )
    add_connection_args(parser)
    args = parser.parse_args()

    if args.scan_timeout <= 0 or args.connect_timeout <= 0:
        parser.error("timeouts must be positive")

    support = pairing_support(sys.platform)
    console.print(f"[dim]{support['note']}[/dim]")

    client = None
    try:
        client = await connect(args.device, args.scan_timeout, args.connect_timeout)
        if client is None:
            sys.exit(1)

        if args.unpair:
            status, detail = await attempt_unpair(client)
            _report(status, detail)
            return

        trigger = None
        if args.char:
            trigger = find_characteristic(client, args.char)
            if trigger is None:
                console.print(f"[red]Characteristic {args.char!r} not found.[/red]")
                sys.exit(1)
        status, detail = await attempt_pair(client, trigger)
        _report(status, detail)

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
