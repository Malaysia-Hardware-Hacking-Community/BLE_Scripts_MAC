import argparse
import asyncio
import traceback

from bleak.exc import BleakGATTProtocolError
from rich.console import Console

from ble_common import (
    GATTTableBuilder,
    connect,
    decode_bytes,
    fmt_bytes,
    short_uuid,
    show_value,
)

console = Console()


#: CTF-relevant UUID patterns we commonly encounter
CTF_INTERESTING_UUIDS = {
    # Common CTF flag/service UUIDs (16-bit)
    "180a": "Device Information Service",
    "2a00": "Device Name",
    "2a01": "Appearance",
    "2a05": "Service String",
    "2a07": "Precision Pointer",
    "2a37": "Heart Rate Measurement",
    "2a38": "Body Sensor Location",
    "2a85": "Alert Notification Control Point",
    "2a86": "Alert Notification Status",
    "2a87": "Group Notification Configuration",
    "2a88": "Direct Find",
    "2a89": "Find Me Target",
    "2a8a": "Find Me Target",
    # 128-bit UUIDs that sometimes appear in CTF challenges
    # (these are just hints; actual 128-bit would be full hash)
}


def ctfflag_highlight(text: str) -> str:
    """Apply rich formatting to make potential flags stand out."""
    return f"[bold magenta]{text}[/bold magenta]"


async def main():
    parser = argparse.ArgumentParser(
        description="Connect and enumerate GATT attributes (CTF-aware)."
    )
    parser.add_argument("device", help="Identifier from scan_ble.py (address or name)")
    parser.add_argument("--scan-timeout", type=float, default=15, help="Scan timeout in seconds")
    parser.add_argument("--connect-timeout", type=float, default=30, help="Connection timeout in seconds")
    parser.add_argument(
        "--readable",
        action="store_true",
        help="Attempt reads on characteristics reporting the read property.",
    )
    parser.add_argument(
        "--writable",
        action="store_true",
        help="Attempt writes on characteristics reporting the write property.",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Subscribe to notifications on characteristics.",
    )
    parser.add_argument(
        "--indicate",
        action="store_true",
        help="Subscribe to indications on characteristics.",
    )
    parser.add_argument(
        "--ctf-mode",
        action="store_true",
        help="Enable CTF mode: highlight interesting UUIDs and attempt common reads.",
    )
    parser.add_argument(
        "--filter-uuid",
        help="Only enumerate characteristics matching this UUID substring (case-insensitive).",
    )
    args = parser.parse_args()

    if args.scan_timeout <= 0:
        parser.error("--scan-timeout must be positive")
    if args.connect_timeout <= 0:
        parser.error("--connect-timeout must be positive")

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

        # Number of active notify/indicate subscriptions. Defined up front so the
        # end-of-run wait loop can reference it whether or not --notify was given.
        count = 0

        # -------------------------------------------------------------------------
        # GATT enumeration
        # -------------------------------------------------------------------------
        builder = GATTTableBuilder(title="GATT Attributes", header_style="bold cyan")
        builder.add_services(client)

        # Also filter by UUID if requested
        filter_uuid = args.filter_uuid.lower() if args.filter_uuid else None

        all_chars = []  # type: list
        for _svc, chars in builder.services:
            for ch in chars.values():
                # Apply UUID filter
                if filter_uuid:
                    if filter_uuid not in str(ch.uuid).lower():
                        continue

                all_chars.append(ch)

        # Populate value rows for readable characteristics
        if args.readable or args.ctf_mode:
            for _svc, chars in builder.services:
                for ch in chars.values():
                    # Apply UUID filter
                    if filter_uuid and filter_uuid not in str(ch.uuid).lower():
                        continue
                    if "read" not in ch.properties:
                        continue
                    try:
                        value = await client.read_gatt_char(ch)
                        text = decode_bytes(value)
                        if text or args.ctf_mode:
                            interesting = (
                                short_uuid(ch.uuid) in CTF_INTERESTING_UUIDS
                            )
                            mark = " [bold magenta]<-- interesting[/bold magenta]" if interesting else ""
                            console.print(
                                f"\n[cyan]Read {ch.uuid} (handle {ch.handle}){mark}[/cyan]"
                            )
                            show_value(value, label="  ")
                    except BleakGATTProtocolError as exc:
                        code = getattr(exc, "code", None)
                        code_str = f"0x{code:02X}" if isinstance(code, int) else "n/a"
                        console.print(
                            f"[red]GATT read failed (code {code_str}): {exc}[/red]"
                        )
                    except Exception as exc:
                        console.print(
                            f"[red]Read failed ({type(exc).__name__}): {exc!r}[/red]"
                        )

        # Write support
        if args.writable:
            console.print("\n[cyan]Writable characteristics:[/cyan]")
            for _svc, chars in builder.services:
                for ch in chars.values():
                    if "write" in ch.properties or "write-without-response" in ch.properties:
                        console.print(f"  [green]{ch.uuid}[/green] (handle {ch.handle})")

        # Notify/Indicate subscription
        if args.notify or args.indicate:
            console.print("\n[cyan]Subscribe notifications/indications:[/cyan]")

            def _notification_handler(sender, data):
                text = decode_bytes(data)
                if args.ctf_mode and text:
                    console.print(f"[green]{short_uuid(sender.uuid)}: {text}[/green]")
                else:
                    console.print(
                        f"[green]{short_uuid(sender.uuid)} notified "
                        f"({len(data)} bytes)[/green]"
                    )

            for _svc, chars in builder.services:
                for ch in chars.values():
                    # Apply UUID filter
                    if filter_uuid and filter_uuid not in str(ch.uuid).lower():
                        continue
                    if not ({"notify", "indicate"} & set(ch.properties)):
                        continue
                    # bleak has no separate indicate call: start_notify writes the
                    # CCCD, and the peripheral picks notify vs indicate from the
                    # value written.
                    kind = (
                        "notify" if "notify" in ch.properties else "indicate"
                    )
                    try:
                        await client.start_notify(ch, _notification_handler)
                        count += 1
                        console.print(
                            f"  [green]subscribed[/green] {ch.uuid} "
                            f"(handle {ch.handle}, {kind})"
                        )
                    except Exception as exc:
                        console.print(
                            f"  [red]failed {kind} on {ch.uuid}: {exc!r}[/red]"
                        )

            console.print(f"\n[dim]{count} subscription(s) active.[/dim]")

        # -------------------------------------------------------------------------
        # CTF mode: attempt reads on common UUIDs + summary
        # -------------------------------------------------------------------------
        if args.ctf_mode:
            console.print("\n[bold]=== CTF MODE: attempting reads on common UUIDs ===[/bold]")
            found_flags = []

            for _svc, chars in builder.services:
                for ch in chars.values():
                    if filter_uuid and filter_uuid not in str(ch.uuid).lower():
                        continue
                    uuid_16 = short_uuid(ch.uuid)
                    label = CTF_INTERESTING_UUIDS.get(uuid_16)
                    if label is None or "read" not in ch.properties:
                        continue
                    try:
                        value = await client.read_gatt_char(ch)
                        text = decode_bytes(value)
                        console.print(
                            f"  [magenta]Read {ch.uuid} ({label}):[/magenta] {fmt_bytes(value)}"
                        )
                        if text and not text.startswith("("):
                            found_flags.append((ch.uuid, text))
                    except Exception as e:
                        console.print(f"    [red]Read error: {e!r}[/red]")

            if found_flags:
                console.print(
                    f"\n[bold green]Potential flags found: {len(found_flags)}[/bold green]"
                )
                for uuid, text in found_flags[:10]:
                    console.print(f"  - {uuid}: {text}")
            else:
                console.print(
                    "[dim]No CTF-relevant standard UUIDs with read property found.[/dim]"
                )

        # -------------------------------------------------------------------------
        # Generic characteristic enumeration (always on)
        # -------------------------------------------------------------------------
        console.print("\n[bold]All characteristics:[/bold]")
        for _svc, chars in builder.services:
            for ch in chars.values():
                # Apply UUID filter
                if filter_uuid and filter_uuid not in str(ch.uuid).lower():
                    continue

                props_str = ", ".join(
                    p.replace("-", " ").title() for p in ch.properties
                    if p in ("broadcast", "read", "write-without-response", "write", "notify", "indicate")
                )
                console.print(
                    f"  [cyan]UUID {ch.uuid}[/cyan] handle={ch.handle} props={props_str}"
                )

                # Describe descriptors if any. Descriptors need read_gatt_descriptor,
                # not read_gatt_char.
                descrs = ch.descriptors
                if descrs:
                    console.print(f"    [dim]Descriptors ({len(descrs)}):[/dim]")
                    for d in descrs[:5]:  # show first 5
                        console.print(
                            f"      [dim]  {short_uuid(d.uuid)} "
                            f"(handle {d.handle})[/dim]"
                        )
                    if len(descrs) > 5:
                        console.print(f"      [dim]... and {len(descrs) - 5} more[/dim]")

        # -------------------------------------------------------------------------
        # Summary
        # -------------------------------------------------------------------------
        console.print(
            f"\n[dim]Total characteristics enumerated: {len(all_chars)}[/dim]"
        )

        # If the user asked to subscribe, block here so notifications actually
        # arrive. Without this the function would return and the finally below
        # would disconnect before the peripheral ever pushed an update.
        if (args.notify or args.indicate) and count:
            console.print(
                "\n[dim]Streaming updates. Press Ctrl-C to disconnect.[/dim]"
            )
            # Block until interrupted. On Ctrl-C the task is cancelled; the
            # cancellation propagates (not swallowed) so the finally below runs
            # to disconnect and __main__ reports it, matching watch_ble.
            await asyncio.Event().wait()

    except Exception as exc:
        console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
        traceback.print_exc()

    finally:
        if client is not None and client.is_connected:
            await client.disconnect()
            console.print("[dim]Disconnected.[/dim]")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")