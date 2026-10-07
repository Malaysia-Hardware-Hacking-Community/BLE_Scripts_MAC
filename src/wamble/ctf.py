"""A gatttool-style, scriptable BLE CTF client for macOS (``wamble.ctf``).

The CyberDSA BLE CTF walkthrough (`ble_ctf_commands.txt`) is written for Linux
`gratttool`/`gatttool`: handle-based reads and writes, write-then-listen for
notifications/indications, a 1001-read loop, and a score/submission handle.
`gatttool` does not exist on macOS, so this provides the same handle-centric
primitives over CoreBluetooth via bleak, non-interactively, one subcommand per
operation:

    enum                      list services/characteristics with handles
    read     -a HANDLE        read a characteristic by handle (gatttool --char-read)
    write    -a HANDLE -n HEX write hex (gatttool --char-write-req; --cmd for no-response)
    writestr -a HANDLE -s STR write an ASCII string
    submit   -s FLAG          write a flag string to the submission handle (0x002c)
    score                     read and decode the score handle (0x002a)
    listen   -a HANDLE [-n HEX] subscribe, optionally trigger-write, capture notify/indicate
    readloop -a HANDLE -c N   read N times (flag 10's 1001-read counter), print final value
    mtu                       report the negotiated ATT MTU (and whether flag 16 is reachable)

Coverage on macOS is 16/20 (verified live against the device). Four flags are
blocked by CoreBluetooth itself and need a Linux/BlueZ host with gatttool/btmgmt:
  * flag 15 sets a local BD address (gatttool --bdaddr): no CoreBluetooth API.
  * flag 16 wants the ATT MTU exactly 444 (gatttool --mtu): macOS auto-negotiates
    (500 here) and cannot set it; `mtu` reports what you got.
  * flag 18 is a "hidden" notification on 0xff15: the characteristic has no notify
    property, so CoreBluetooth refuses to subscribe (CBATTError Code 6).
  * flag 19 is a notification half on 0xff16: declares notify but has no CCCD
    (0x2902), so CoreBluetooth cannot enable notifications (CBATTError Code 10).
Flags whose characteristics have a real notify+CCCD setup (0xff0c/0e/0f/11,
i.e. flags 11-14) work fine. See the README for the full breakdown.

Default target name is the CTF device ("M0DUL0CTF"); override with -b/--device
(a name substring or a CoreBluetooth address).
"""

import argparse
import asyncio

from wamble.common import (
    add_connection_args,
    connect,
    console,
    decode_bytes,
    describe_gatt_error,
    fmt_bytes,
)
from wamble.gatt import as_handle, read_target, resolve_target

DEFAULT_DEVICE = "M0DUL0CTF"
SCORE_HANDLE = "0x002a"
SUBMIT_HANDLE = "0x002c"
FLAG16_REQUIRED_MTU = 444


def _hex_to_bytes(text: str) -> bytes:
    """Parse a hex string (spaces/0x tolerated), e.g. '41', '0x41', '12 34'."""
    cleaned = text.replace("0x", "").replace("0X", "").replace(" ", "").replace(":", "")
    return bytes.fromhex(cleaned)


def _resolve(client, handle_or_uuid: str):
    """Resolve a characteristic/descriptor by UUID or handle, macOS-aware.

    macOS CoreBluetooth does not expose real ATT handles; bleak synthesizes a
    handle that is the characteristic *declaration* handle, one below the
    gatttool *value* handle the Linux CTF walkthrough uses (confirmed on the
    live device: ff01 is 0x29 here vs 0x2a there). So when a handle does not
    resolve, retry one lower, letting the walkthrough's value handles work
    verbatim. UUID addressing (``ff01`` …) is unaffected and always works.
    """
    target = resolve_target(client, handle_or_uuid)
    if target is None:
        h = as_handle(str(handle_or_uuid).strip())
        if h is not None and h > 0:
            shifted = resolve_target(client, str(h - 1))
            if shifted is not None:
                console.print(
                    f"[dim](macOS handle offset: {handle_or_uuid} → resolved at "
                    f"declaration handle 0x{h - 1:04x})[/dim]"
                )
                return shifted
    if target is None:
        console.print(f"[red]No characteristic/descriptor for {handle_or_uuid!r}.[/red]")
    return target


def _show(value: bytes, label: str = "") -> None:
    prefix = f"{label} " if label else ""
    console.print(f"{prefix}[dim]hex:[/dim]  {fmt_bytes(value)}")
    text = decode_bytes(value)
    if text:
        console.print(f"{prefix}[green]text:[/green] {text}")


# --- operations (each takes a connected client, so they are unit-testable) ---


async def op_read(client, handle: str) -> bytes:
    target = _resolve(client, handle)
    if target is None:
        return b""
    value = bytes(await read_target(client, target))
    _show(value)
    return value


async def op_write(client, handle: str, data: bytes, *, response: bool) -> bool:
    target = _resolve(client, handle)
    if target is None:
        return False
    await client.write_gatt_char(target, data, response=response)
    mode = "req" if response else "cmd"
    console.print(f"[green]wrote[/green] {fmt_bytes(data)} to {handle} ({mode}).")
    return True


async def op_readloop(client, handle: str, count: int, show_every: int = 0) -> bytes:
    target = _resolve(client, handle)
    if target is None:
        return b""
    last = b""
    for i in range(1, count + 1):
        last = bytes(await read_target(client, target))
        if show_every and i % show_every == 0:
            console.print(f"[dim]  read {i}/{count}: {fmt_bytes(last)}[/dim]")
    console.print(f"[green]completed {count} reads.[/green] Final value:")
    _show(last)
    return last


async def op_listen(
    client, handle: str, trigger: bytes | None, secs: float, *, response: bool
) -> list:
    target = _resolve(client, handle)
    if target is None:
        return []
    events: list = []

    def handler(_sender, data):
        entry = {"hex": fmt_bytes(data), "text": decode_bytes(data)}
        events.append(entry)
        console.print(f"  [cyan]notify/indicate[/cyan]: {entry['text'] or entry['hex']}")

    await client.start_notify(target, handler)
    console.print(
        f"[green]subscribed[/green] to {handle}; listening {secs:g}s. Ctrl-C to stop early."
    )
    try:
        if trigger is not None:
            await client.write_gatt_char(target, trigger, response=response)
            console.print(f"[green]triggered[/green] with {fmt_bytes(trigger)}.")
        await asyncio.sleep(secs)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        try:
            await client.stop_notify(target)
        except Exception:
            pass
    console.print(f"[dim]captured {len(events)} message(s).[/dim]")
    return events


def op_mtu_report(mtu: int) -> None:
    console.print(f"Negotiated ATT MTU: [bold]{mtu}[/bold] bytes (payload {max(0, mtu - 3)}).")
    # Flag 16 requires the negotiated MTU to be EXACTLY 444; the device returns
    # a hint ("Set your connection MTU to 444") for any other value. macOS
    # CoreBluetooth negotiates the MTU itself and exposes no way to set it, so
    # hitting exactly 444 is impossible here regardless of what we got.
    if mtu == FLAG16_REQUIRED_MTU:
        console.print(f"[green]Exactly {FLAG16_REQUIRED_MTU}: flag 16 is readable now.[/green]")
    else:
        console.print(
            f"[yellow]Flag 16 needs the MTU to be exactly {FLAG16_REQUIRED_MTU}; this is {mtu}. "
            "macOS auto-negotiates the MTU and cannot set it, so flag 16 is blocked here. "
            "Use a Linux/BlueZ host with `gatttool --mtu 444`.[/yellow]"
        )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="gatttool-style scriptable BLE CTF client for macOS.")
    p.add_argument(
        "-b",
        "--device",
        default=DEFAULT_DEVICE,
        help=f"Device name/address (default: {DEFAULT_DEVICE})",
    )
    add_connection_args(p)
    sub = p.add_subparsers(dest="op", required=True)

    sub.add_parser("enum", help="Enumerate services/characteristics with handles")
    sub.add_parser("score", help="Read + decode the score handle (0x002a)")
    sub.add_parser("mtu", help="Report the negotiated ATT MTU (flag 16 reachability)")

    r = sub.add_parser("read", help="Read a characteristic by handle")
    r.add_argument("-a", "--handle", required=True)

    w = sub.add_parser("write", help="Write hex to a handle")
    w.add_argument("-a", "--handle", required=True)
    w.add_argument("-n", "--value", required=True, help="Hex, e.g. 41 or '0x41' or '12 34'")
    w.add_argument("--cmd", action="store_true", help="Write-without-response (default: write-req)")

    ws = sub.add_parser("writestr", help="Write an ASCII string to a handle")
    ws.add_argument("-a", "--handle", required=True)
    ws.add_argument("-s", "--string", required=True)
    ws.add_argument("--cmd", action="store_true")

    sm = sub.add_parser("submit", help="Write a flag string to the submission handle")
    sm.add_argument("-s", "--string", required=True)
    sm.add_argument("-a", "--handle", default=SUBMIT_HANDLE)

    lp = sub.add_parser(
        "listen", help="Subscribe, optionally trigger-write, capture notify/indicate"
    )
    lp.add_argument("-a", "--handle", required=True)
    lp.add_argument("-n", "--value", help="Optional hex to write as a trigger")
    lp.add_argument("--secs", type=float, default=8.0)
    lp.add_argument("--cmd", action="store_true")

    rl = sub.add_parser("readloop", help="Read a handle N times (flag 10)")
    rl.add_argument("-a", "--handle", required=True)
    rl.add_argument("-c", "--count", type=int, default=1001)
    rl.add_argument("--show-every", type=int, default=200)
    return p


async def main() -> None:
    args = build_parser().parse_args()

    # 'enum'/'mtu'/'score' and the rest all need a connection.
    client = await connect(args.device, args.scan_timeout, args.connect_timeout)
    if client is None:
        console.print("[red]Failed to connect.[/red]")
        return
    try:
        if args.op == "enum":
            from wamble.common import print_gatt_tables

            print_gatt_tables(client)
        elif args.op == "mtu":
            op_mtu_report(int(client.mtu_size))
        elif args.op == "score":
            console.print("[cyan]Score:[/cyan]")
            await op_read(client, SCORE_HANDLE)
        elif args.op == "read":
            await op_read(client, args.handle)
        elif args.op == "write":
            await op_write(client, args.handle, _hex_to_bytes(args.value), response=not args.cmd)
        elif args.op == "writestr":
            await op_write(client, args.handle, args.string.encode("utf-8"), response=not args.cmd)
        elif args.op == "submit":
            if await op_write(client, args.handle, args.string.encode("utf-8"), response=True):
                console.print("[green]submitted. Check `score`.[/green]")
        elif args.op == "listen":
            trigger = _hex_to_bytes(args.value) if args.value else None
            await op_listen(client, args.handle, trigger, args.secs, response=not args.cmd)
        elif args.op == "readloop":
            await op_readloop(client, args.handle, args.count, args.show_every)
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Let a real interrupt propagate to the __main__ guard; the finally below
        # still disconnects on the way out.
        raise
    except Exception as exc:
        # A device refusing a read or write (it wants pairing, or the handle is
        # locked) is a normal answer, so report it plainly instead of letting a
        # traceback escape.
        console.print(f"[yellow]{describe_gatt_error(exc)}[/yellow]")
    finally:
        if client.is_connected:
            await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
