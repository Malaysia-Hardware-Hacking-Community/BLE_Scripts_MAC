"""Log BLE advertisements to CSV over time.

Where `wamble-watch` shows a live, self-refreshing view, this appends one
timestamped CSV row per advertisement sighting, so you get a time-series you can
analyse later: when a device appeared or disappeared, and how its RSSI moved.

```
wamble-adv-log -o log.csv                 # log everything until Ctrl-C
wamble-adv-log -o log.csv --timeout 300   # log for five minutes
wamble-adv-log -n Fitbit --min-interval 5 # one row per matching device per 5s
```

With no `-o` the CSV goes to stdout (status messages stay on stderr), so it
pipes cleanly. The per-device `--min-interval` throttle keeps a chatty beacon
from flooding the log.
"""

import argparse
import asyncio
import contextlib
import csv
import sys
from datetime import UTC, datetime
from typing import Any

from bleak import BleakScanner
from rich.console import Console

from wamble.common import parse_advertisement_data

# Status messages go to stderr so a stdout CSV stream stays clean for piping.
err = Console(stderr=True)

#: CSV columns, shared by the writer and its header row.
ADV_LOG_FIELDS = ["timestamp", "address", "name", "rssi", "service_uuids", "manufacturer"]


def adv_log_row(timestamp: str, device: Any, adv: Any) -> dict:
    """Build one CSV row from an advertisement sighting."""
    data = parse_advertisement_data(adv)
    return {
        "timestamp": timestamp,
        "address": str(device.address),
        "name": device.name or adv.local_name or "",
        "rssi": "" if adv.rssi is None else adv.rssi,
        "service_uuids": ";".join(data["service_uuids"]),
        "manufacturer": data["manufacturer"],
    }


def is_due(previous: float | None, now: float, min_interval: float) -> bool:
    """True if a device should be logged now, given when it was last logged.

    *previous* is the last log time (monotonic seconds) or None if never logged.
    A *min_interval* of 0 logs every sighting.
    """
    if min_interval <= 0 or previous is None:
        return True
    return (now - previous) >= min_interval


def _passes_filters(device: Any, adv: Any, name: str | None, min_rssi: int | None) -> bool:
    if name and name.casefold() not in (device.name or adv.local_name or "").casefold():
        return False
    return not (min_rssi is not None and (adv.rssi or 0) < min_rssi)


@contextlib.contextmanager
def _open_output(path: str | None):
    """Yield a writable stream: the file at *path*, or stdout when *path* is None."""
    if path:
        with open(path, "w", newline="") as f:
            yield f
    else:
        yield sys.stdout


async def _scan_until_done(on_detection, timeout: float | None) -> None:
    scanner = BleakScanner(detection_callback=on_detection)
    async with scanner:
        if timeout:
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(timeout):
                    await asyncio.Event().wait()
        else:
            await asyncio.Event().wait()


async def run_log(args: argparse.Namespace) -> None:
    """Scan and append a CSV row per sighting until the timeout or Ctrl-C."""
    last_seen: dict[str, float] = {}
    count = 0

    with _open_output(args.output) as out:
        writer = csv.DictWriter(out, fieldnames=ADV_LOG_FIELDS)
        writer.writeheader()
        out.flush()

        def on_detection(device: Any, adv: Any) -> None:
            nonlocal count
            if not _passes_filters(device, adv, args.name, args.min_rssi):
                return
            now = asyncio.get_event_loop().time()
            if not is_due(last_seen.get(device.address), now, args.min_interval):
                return
            last_seen[device.address] = now
            writer.writerow(adv_log_row(datetime.now(UTC).isoformat(), device, adv))
            out.flush()
            count += 1

        window = f"for {args.timeout:g}s" if args.timeout else "until Ctrl-C"
        err.print(f"[cyan]Logging advertisements {window}...[/cyan]")
        try:
            await _scan_until_done(on_detection, args.timeout)
        finally:
            err.print(f"[green]Logged {count} advertisement rows.[/green]")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Log BLE advertisements to CSV over time.")
    parser.add_argument("-o", "--output", help="CSV file to write (default: stdout)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Stop after this many seconds (default: run until Ctrl-C)",
    )
    parser.add_argument("-n", "--name", help="Only log devices whose name contains this substring")
    parser.add_argument(
        "-m", "--min-rssi", type=int, default=None, help="Only log signals at least this strong"
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=0.0,
        help="Minimum seconds between rows for the same device (default: log every sighting)",
    )
    args = parser.parse_args()
    if args.timeout is not None and args.timeout <= 0:
        parser.error("--timeout must be positive")
    await run_log(args)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        err.print("\n[yellow]Stopped.[/yellow]")
