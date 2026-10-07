"""Subscribe to a device's notifications and log them to CSV with timestamps.

`wamble-notify-log "Device"` subscribes to every notify/indicate characteristic
(or just the ones named with `-c`) and appends one timestamped CSV row per
notification: wall-clock time, seconds since the first subscription, the
characteristic, the raw value in hex, and a printable-text rendering when the
bytes are text.

```
wamble-notify-log "HR Monitor" -o hr.csv
wamble-notify-log "HR Monitor" -c 2a37 --timeout 60
```

With no `-o` the CSV goes to stdout (status stays on stderr) so it pipes.
"""

import argparse
import asyncio
import contextlib
import csv
import sys
from datetime import UTC, datetime
from typing import Any

from rich.console import Console

from wamble.common import add_connection_args, connect, find_characteristic, short_uuid

err = Console(stderr=True)

#: CSV columns, shared by the writer and its header row.
NOTIFY_LOG_FIELDS = [
    "timestamp",
    "elapsed",
    "characteristic",
    "handle",
    "length",
    "value_hex",
    "text",
]


def as_text(raw: bytes) -> str:
    """Return a printable-text rendering of *raw*, or "" when it is not text."""
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    return decoded if decoded.isprintable() else ""


def notify_row(timestamp: str, elapsed: float, sender: Any, data: Any) -> dict:
    """Build one CSV row from a notification."""
    raw = bytes(data)
    return {
        "timestamp": timestamp,
        "elapsed": f"{elapsed:.3f}",
        "characteristic": short_uuid(sender.uuid),
        "handle": getattr(sender, "handle", ""),
        "length": len(raw),
        "value_hex": raw.hex(" "),
        "text": as_text(raw),
    }


@contextlib.contextmanager
def _open_output(path: str | None):
    """Yield a writable stream: the file at *path*, or stdout when *path* is None."""
    if path:
        with open(path, "w", newline="") as f:
            yield f
    else:
        yield sys.stdout


def select_characteristics(client: Any, specs: list[str] | None) -> list:
    """Resolve which characteristics to subscribe to.

    With *specs*, each is resolved by UUID or handle (skipping any that are not
    notify/indicate capable). Without, every notify or indicate characteristic
    on the device is chosen.
    """
    if specs:
        chosen = []
        for spec in specs:
            ch = find_characteristic(client, spec)
            if ch is not None and {"notify", "indicate"} & set(ch.properties):
                chosen.append(ch)
        return chosen
    # by="property" returns a list of matches, or None when there are none.
    notify = find_characteristic(client, "notify", by="property") or []
    indicate = find_characteristic(client, "indicate", by="property") or []
    seen, chosen = set(), []
    for ch in [*notify, *indicate]:
        if ch.uuid not in seen:
            seen.add(ch.uuid)
            chosen.append(ch)
    return chosen


async def _wait(timeout: float | None) -> None:
    if timeout:
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(timeout):
                await asyncio.Event().wait()
    else:
        await asyncio.Event().wait()


async def run_log(args: argparse.Namespace) -> None:
    """Connect, subscribe, and log each notification until the timeout or Ctrl-C."""
    client = await connect(args.device, args.scan_timeout, args.connect_timeout)
    if client is None:
        return

    chars = select_characteristics(client, args.char)
    if not chars:
        err.print("[yellow]No notify/indicate characteristics to subscribe to.[/yellow]")
        if client.is_connected:
            await client.disconnect()
        return

    count = 0
    loop = asyncio.get_event_loop()
    start = loop.time()

    with _open_output(args.output) as out:
        writer = csv.DictWriter(out, fieldnames=NOTIFY_LOG_FIELDS)
        writer.writeheader()
        out.flush()

        def handler(sender: Any, data: Any) -> None:
            nonlocal count
            writer.writerow(
                notify_row(datetime.now(UTC).isoformat(), loop.time() - start, sender, data)
            )
            out.flush()
            count += 1

        subscribed = []
        try:
            for ch in chars:
                await client.start_notify(ch, handler)
                subscribed.append(ch)
                err.print(f"[green]Subscribed[/green] {short_uuid(ch.uuid)} (handle {ch.handle})")
            window = f"for {args.timeout:g}s" if args.timeout else "until Ctrl-C"
            err.print(f"[cyan]Logging notifications {window}...[/cyan]")
            await _wait(args.timeout)
        finally:
            for ch in subscribed:
                with contextlib.suppress(Exception):
                    await client.stop_notify(ch)
            if client.is_connected:
                await client.disconnect()
            err.print(f"[green]Logged {count} notifications.[/green]")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Log a device's BLE notifications to CSV.")
    parser.add_argument("device", help="Device address or name")
    parser.add_argument(
        "-c",
        "--char",
        action="append",
        help="Characteristic UUID or handle to subscribe to (repeatable; default: all notify/indicate)",
    )
    parser.add_argument("-o", "--output", help="CSV file to write (default: stdout)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Stop after this many seconds (default: run until Ctrl-C)",
    )
    add_connection_args(parser)
    args = parser.parse_args()
    if args.timeout is not None and args.timeout <= 0:
        parser.error("--timeout must be positive")
    await run_log(args)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        err.print("\n[yellow]Stopped.[/yellow]")
