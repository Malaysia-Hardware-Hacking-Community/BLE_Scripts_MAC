"""Run a script of GATT commands against a device, non-interactively.

This is the scriptable counterpart to `wamble-gatt`: instead of typing commands
at the prompt, you put them in a file (or pipe them in) and WAMBLE runs them in
order against one connection, then disconnects. It uses exactly the same commands
as the interactive client, plus a `wait <seconds>` line for holding the
connection open (handy after `notify` to capture a few updates).

```
# blink.txt
services
write-cmd 00010203-0405-0607-0809-0a0b0c0d2b11 3305020000000a...
notify 2a37
wait 5
quit
```

```
wamble-batch "Device" blink.txt
cat blink.txt | wamble-batch "Device" -       # read the script from stdin
```

Lines are tokenised like a shell (quotes work), blank lines are skipped, and
anything after `#` is a comment.
"""

import argparse
import asyncio
import shlex
import sys

from wamble.common import add_connection_args, connect, console
from wamble.interactive import _dispatch


def iter_commands(text: str) -> list[list[str]]:
    """Tokenise script *text* into a list of commands, skipping blanks/comments."""
    commands = []
    for line in text.splitlines():
        parts = shlex.split(line, comments=True)
        if parts:
            commands.append(parts)
    return commands


def parse_wait(parts: list[str]) -> float:
    """Parse a ``wait <seconds>`` command into a positive float."""
    if len(parts) != 2:
        raise ValueError("wait takes one argument: the number of seconds")
    seconds = float(parts[1])
    if seconds <= 0:
        raise ValueError("wait seconds must be positive")
    return seconds


def read_script(path: str) -> str:
    """Read the script from *path*, or from stdin when *path* is ``-``."""
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


async def run_batch(args: argparse.Namespace) -> None:
    """Connect and run each command in the script in order."""
    commands = iter_commands(read_script(args.script))
    client = await connect(args.device, args.scan_timeout, args.connect_timeout)
    if client is None:
        return

    subscriptions: dict = {}
    try:
        for parts in commands:
            console.print(f"[dim][batch][/dim] {' '.join(parts)}")
            if parts[0].lower() in {"wait", "sleep"}:
                try:
                    await asyncio.sleep(parse_wait(parts))
                except ValueError as exc:
                    console.print(f"[red]{exc}[/red]")
                continue
            if await _dispatch(client, parts, subscriptions, args) == "break":
                break
    finally:
        if client.is_connected:
            await client.disconnect()
            console.print("[dim]Disconnected.[/dim]")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a script of GATT commands against a device (see wamble-gatt)."
    )
    parser.add_argument("device", help="Device address or name")
    parser.add_argument("script", help="Path to a command script, or - to read from stdin")
    add_connection_args(parser)
    args = parser.parse_args()
    await run_batch(args)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
