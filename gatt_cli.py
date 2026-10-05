import argparse
import asyncio
import shlex
import signal
import sys
import threading

# Importing readline makes input() use a proper line editor: it handles
# bracketed-paste (so pasted text is not mangled by ESC[200~…ESC[201~ wrappers),
# and adds history and editing. Guarded so the client still runs where readline
# is unavailable (e.g. a stock Windows Python without pyreadline).
try:
    import readline  # noqa: F401

    # Turn bracketed paste OFF so a Cmd-V paste arrives as ordinary keystrokes
    # that the terminal echoes and input() reads, instead of being captured by
    # readline's paste handler (which, under the TUI, was swallowing the paste
    # so nothing appeared at all). See also _set_bracketed_paste below.
    try:
        readline.parse_and_bind("set enable-bracketed-paste off")
    except Exception:
        pass
except ImportError:
    pass

#: Bracketed-paste wrappers a terminal puts around pasted text; stripped as a
#: safety net in case they reach input() anyway.
_PASTE_MARKERS = ("\x1b[200~", "\x1b[201~")


def _set_bracketed_paste(enabled: bool) -> None:
    """Enable/disable the terminal's bracketed-paste mode (no-op if not a tty).

    Disabled for the REPL so a paste arrives as plain typed characters; restored
    to on (the normal shell default) when the client exits, so the terminal is
    not left in a modified state.
    """
    if not sys.stdout.isatty():
        return
    try:
        sys.stdout.write("\x1b[?2004h" if enabled else "\x1b[?2004l")
        sys.stdout.flush()
    except Exception:
        pass

from rich.console import Console

from ble_common import (
    connect,
    find_characteristic,
    print_characteristics_table,
    print_descriptors_table,
    print_gatt_tables,
    print_services_table,
    short_uuid,
    show_value,
)
from ble_gatt import as_handle


def _not_found_hint(client, token: str) -> str:
    """Explain a miss when *token* is actually a service handle, not a char."""
    handle = as_handle(token)
    if handle is None:
        return ""
    for svc in client.services:
        if getattr(svc, "handle", None) == handle:
            return (
                f" Handle {handle} is service {short_uuid(svc.uuid)}; "
                "read/write take a characteristic handle or UUID."
            )
    return ""


console = Console()


def _notification_callback(sender, data) -> None:
    """Print a GATT notification/indication. Shared so re-arming reuses it."""
    console.print(
        f"\n[cyan]Update from {sender.uuid} (handle {sender.handle}):[/cyan]"
    )
    show_value(data)


async def try_reconnect(client, timeout: float, subscriptions: dict) -> bool:
    """Reconnect the client once, re-arming notifications on success.

    Shared by the automatic mid-session recovery and the manual ``reconnect``
    command. Notify subscriptions do not survive a dropped link, so each tracked
    characteristic (keyed by handle -> UUID) is re-resolved against the
    refreshed services and re-subscribed; its handle may change, so it is
    re-keyed. Subscriptions that can no longer be resolved are dropped.
    """
    try:
        await client.connect(timeout=timeout)
    except Exception as exc:
        console.print(f"[red]Reconnect failed: {exc!r}[/red]")
        return False
    if not client.is_connected:
        console.print("[red]Reconnect failed.[/red]")
        return False

    rearmed = 0
    for old_handle, uuid in list(subscriptions.items()):
        subscriptions.pop(old_handle, None)
        ch = find_characteristic(client, uuid)
        if ch is None:
            continue
        try:
            await client.start_notify(ch, _notification_callback)
            subscriptions[ch.handle] = str(ch.uuid)
            rearmed += 1
        except Exception:
            pass
    note = f" {rearmed} subscription(s) re-armed." if rearmed else ""
    console.print(f"[green]Reconnected.[/green]{note}")
    return True


class AsyncPrompt:
    """Read a line via input() on a daemon thread, awaitable from the loop.

    Running input() off the event loop lets the keepalive coroutine run while we
    wait for a command, and keeps readline (history, paste handling) intact. The
    worker is a daemon thread, so a line left unread at exit never blocks it.
    Returns (kind, value): kind is "line", "eof" (Ctrl-D) or "int" (Ctrl-C).
    """

    def __init__(self):
        self._prompt = ""
        self._loop = None
        self._fut = None
        self._go = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            self._go.wait()
            self._go.clear()
            try:
                result = ("line", input(self._prompt))
            except EOFError:
                result = ("eof", None)
            except KeyboardInterrupt:
                result = ("int", None)
            except Exception:
                result = ("eof", None)
            self._loop.call_soon_threadsafe(self._deliver, result)

    def _deliver(self, result):
        if self._fut is not None and not self._fut.done():
            self._fut.set_result(result)

    async def readline(self, prompt: str):
        self._loop = asyncio.get_running_loop()
        self._fut = self._loop.create_future()
        self._prompt = prompt
        self._go.set()
        return await self._fut

    def interrupt(self):
        """Resolve a pending readline as an interrupt (for the SIGINT handler).

        Lets Ctrl-C break the REPL loop cleanly on a healthy event loop, instead
        of cancelling the task mid-await (which can hang shutdown while a notify
        stream is firing). Runs on the loop thread, so touching the future is safe.
        """
        if self._fut is not None and not self._fut.done():
            self._fut.set_result(("int", None))


def _first_readable(client):
    """First characteristic with the read property, or None (for keepalive)."""
    for service in client.services:
        for ch in service.characteristics:
            if "read" in ch.properties:
                return ch
    return None


async def _keepalive(client, interval: float, lock: asyncio.Lock) -> None:
    """Keep the link alive during idle input by reading a characteristic.

    Many cheap peripherals drop a central that goes quiet for a second or two;
    the interactive REPL is idle whenever it waits for a command, so without
    this the link dies between commands. A light periodic read is enough to keep
    it up. The lock ensures a keepalive read never overlaps a user command.
    """
    while True:
        await asyncio.sleep(interval)
        if not client.is_connected or lock.locked():
            continue
        ch = _first_readable(client)
        if ch is None:
            continue
        async with lock:
            if not client.is_connected:
                continue
            try:
                await client.read_gatt_char(ch)
            except Exception:
                pass  # a failed ping just means the next command will reconnect

COMMANDS_HELP = (
    "Commands:\n"
    "  services         (list services)\n"
    "  characteristics  (list characteristics)\n"
    "  descriptors      (list descriptors)\n"
    "  read HANDLE_OR_UUID\n"
    "  write-req HANDLE_OR_UUID HEX_BYTES\n"
    "  write-cmd HANDLE_OR_UUID HEX_BYTES\n"
    "  notify HANDLE_OR_UUID\n"
    "  indicate HANDLE_OR_UUID\n"
    "  unnotify HANDLE_OR_UUID\n"
    "  reconnect        (re-establish a dropped link)\n"
    "  help             (show this list)\n"
    "  quit"
)


async def _dispatch(client, parts, subscriptions, args) -> str | None:
    """Run one REPL command. Returns "break" to end the session, else None.

    Always called while holding the command lock, so its GATT operations never
    overlap the keepalive ping.
    """
    cmd = parts[0].lower()
    if cmd in {"quit", "exit"}:
        return "break"
    if cmd in {"help", "?"}:
        console.print(COMMANDS_HELP)
        return None

    # Manual reconnect: force a fresh link even when still connected.
    if cmd == "reconnect":
        if client.is_connected:
            try:
                await client.disconnect()
            except Exception:
                pass
        console.print("[yellow]Reconnecting…[/yellow]")
        await try_reconnect(client, args.connect_timeout, subscriptions)
        return None

    # The link can drop between commands; reconnect once before using a dead
    # handle rather than failing with "Service Discovery has not been performed".
    if not client.is_connected:
        console.print("[yellow]Device disconnected — reconnecting…[/yellow]")
        if not await try_reconnect(client, args.connect_timeout, subscriptions):
            console.print("[red]Ending session.[/red]")
            return "break"

    if cmd == "services":
        print_services_table(client)
        return None
    if cmd == "characteristics":
        print_characteristics_table(client)
        return None
    if cmd == "descriptors":
        print_descriptors_table(client)
        return None

    if cmd == "read" and len(parts) == 2:
        char = find_characteristic(client, parts[1])
        if char is None:
            console.print(f"[red]Characteristic not found.[/red]{_not_found_hint(client, parts[1])}")
        elif "read" not in char.properties:
            console.print("[red]Not readable.[/red]")
        else:
            try:
                show_value(await client.read_gatt_char(char))
            except Exception as exc:
                console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
        return None

    if cmd in {"write-req", "write-cmd"} and len(parts) == 3:
        char = find_characteristic(client, parts[1])
        if char is None:
            console.print(f"[red]Characteristic not found.[/red]{_not_found_hint(client, parts[1])}")
            return None
        response = cmd == "write-req"
        required = "write" if response else "write-without-response"
        if required not in char.properties:
            console.print(f"[red]Characteristic lacks {required}.[/red]")
            return None
        try:
            payload = bytes.fromhex(parts[2])
            await client.write_gatt_char(char, payload, response=response)
            console.print(f"[green]Sent {len(payload)} byte(s).[/green]")
        except Exception as exc:
            console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
        return None

    if cmd in {"notify", "indicate", "unnotify"} and len(parts) == 2:
        char = find_characteristic(client, parts[1])
        if char is None:
            console.print(f"[red]Characteristic not found.[/red]{_not_found_hint(client, parts[1])}")
            return None
        key = char.handle
        if cmd == "unnotify":
            if key not in subscriptions:
                console.print("[yellow]No active subscription for that handle.[/yellow]")
            else:
                await client.stop_notify(char)
                subscriptions.pop(key, None)
                console.print("[green]Subscription stopped.[/green]")
            return None
        acceptable = "notify" if cmd == "notify" else "indicate"
        if acceptable not in char.properties:
            console.print(f"[red]Characteristic lacks {acceptable} property.[/red]")
            return None
        if key in subscriptions:
            console.print("[yellow]Already subscribed.[/yellow]")
            return None
        try:
            await client.start_notify(char, _notification_callback)
            subscriptions[key] = str(char.uuid)
            console.print(
                "[green]Subscribed; use unnotify to stop.[/green] "
                "[dim](re-armed automatically after reconnects)[/dim]"
            )
        except Exception as exc:
            console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
        return None

    console.print("[yellow]Invalid command or arguments.[/yellow]")
    return None


async def main():
    parser = argparse.ArgumentParser(description="Interactive BLE GATT client.")
    parser.add_argument("device")
    parser.add_argument("--scan-timeout", type=float, default=15)
    parser.add_argument("--connect-timeout", type=float, default=30)
    parser.add_argument(
        "--keepalive",
        type=float,
        default=2.0,
        metavar="SECONDS",
        help="Ping the device every SECONDS of idle to hold the link (0 = off, default: 2)",
    )
    args = parser.parse_args()

    client = None
    subscriptions = {}  # handle -> characteristic UUID, for re-arming on reconnect
    lock = asyncio.Lock()
    keepalive_task = None

    try:
        client = await connect(args.device, args.scan_timeout, args.connect_timeout)
        if client is None:
            return
        print_gatt_tables(client)
        console.print("\n" + COMMANDS_HELP)
        if args.keepalive > 0:
            console.print(
                f"[dim]Keepalive: pinging every {args.keepalive:g}s to hold the link "
                "(disable with --keepalive 0).[/dim]"
            )

        # Paste arrives as plain keystrokes for the whole REPL (restored on exit).
        _set_bracketed_paste(False)

        prompt = AsyncPrompt()
        # Handle Ctrl-C on the loop so it breaks the REPL cleanly instead of
        # cancelling mid-await (which can hang teardown during a notify stream).
        try:
            asyncio.get_running_loop().add_signal_handler(
                signal.SIGINT, prompt.interrupt
            )
        except (NotImplementedError, RuntimeError):
            pass  # not supported on this platform/loop; top-level handler covers it
        if args.keepalive > 0:
            keepalive_task = asyncio.create_task(_keepalive(client, args.keepalive, lock))

        while True:
            kind, line = await prompt.readline("[gatt] ")
            if kind != "line":
                console.print()
                break

            for marker in _PASTE_MARKERS:
                line = line.replace(marker, "")
            try:
                # comments=True lets a trailing "# note" be ignored, so pasting
                # an annotated example (e.g. "write-cmd 19 33…  # power on")
                # works instead of parsing the note as extra arguments.
                parts = shlex.split(line.strip(), comments=True)
            except ValueError as exc:
                console.print(f"[yellow]Could not parse input: {exc}[/yellow]")
                continue

            if not parts:
                continue

            # Hold the lock for the whole command so keepalive never overlaps it.
            async with lock:
                action = await _dispatch(client, parts, subscriptions, args)
            if action == "break":
                break

    except Exception as exc:
        console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
    finally:
        if keepalive_task is not None:
            keepalive_task.cancel()
            try:
                await keepalive_task
            except BaseException:
                pass
        _set_bracketed_paste(True)  # restore the terminal's normal paste mode
        # Bound the disconnect so a wedged BLE stack (e.g. mid notify-stream)
        # can't hang exit; disconnecting also drops any notify subscriptions.
        if client is not None:
            try:
                if client.is_connected:
                    await asyncio.wait_for(client.disconnect(), timeout=5)
            except Exception:
                pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
