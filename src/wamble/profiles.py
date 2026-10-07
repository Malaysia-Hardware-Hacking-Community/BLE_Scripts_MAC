"""Read and decode common Bluetooth SIG measurement profiles.

Where `wamble-battery` reads one standard characteristic, this decodes the
value layouts of a few more: Heart Rate Measurement (0x2A37), Temperature
Measurement (0x2A1C, the Health Thermometer) and CSC Measurement (0x2A5B,
cycling speed and cadence). Each of these is a notify/indicate characteristic
with a flags-driven binary layout, so `wamble-profile` subscribes and prints a
decoded reading per update.

```
wamble-profile "HR Monitor"                 # auto-detect the profile
wamble-profile "HR Monitor" -p heart-rate   # or name it
wamble-profile "Thermometer" --timeout 30
```

The decoders are the interesting, bug-prone part (IEEE-11073 floats, optional
fields), so they are pure functions tested on hand-built frames.
"""

import argparse
import asyncio
import contextlib
from typing import Any

from rich.console import Console

from wamble.common import add_connection_args, connect, find_characteristic

console = Console()


def decode_heart_rate(data: bytes) -> dict:
    """Decode a Heart Rate Measurement (0x2A37).

    The flags byte selects an 8- or 16-bit rate and whether sensor-contact,
    energy-expended and RR-interval fields follow.
    """
    flags = data[0]
    idx = 1
    if flags & 0x01:
        bpm = int.from_bytes(data[idx : idx + 2], "little")
        idx += 2
    else:
        bpm = data[idx]
        idx += 1
    result: dict = {"bpm": bpm}
    if flags & 0x04:  # sensor contact supported
        result["sensor_contact"] = bool(flags & 0x02)
    if flags & 0x08:  # energy expended present
        result["energy_j"] = int.from_bytes(data[idx : idx + 2], "little")
        idx += 2
    if flags & 0x10:  # RR intervals present (units of 1/1024 s)
        rr = []
        while idx + 2 <= len(data):
            rr.append(int.from_bytes(data[idx : idx + 2], "little"))
            idx += 2
        result["rr"] = rr
    return result


def _ieee11073_float(raw: bytes) -> float:
    """Decode an IEEE-11073 32-bit FLOAT: 24-bit signed mantissa, 8-bit exponent."""
    value = int.from_bytes(raw, "little")
    mantissa = value & 0x00FFFFFF
    if mantissa >= 0x800000:
        mantissa -= 0x01000000
    exponent = value >> 24
    if exponent >= 0x80:
        exponent -= 0x100
    return mantissa * (10.0**exponent)


def decode_health_thermometer(data: bytes) -> dict:
    """Decode a Temperature Measurement (0x2A1C): flags + IEEE-11073 float."""
    flags = data[0]
    temperature = round(_ieee11073_float(data[1:5]), 2)
    return {"temperature": temperature, "unit": "F" if flags & 0x01 else "C"}


def decode_csc(data: bytes) -> dict:
    """Decode a CSC Measurement (0x2A5B): cumulative wheel/crank revs and times.

    Speed and cadence are rates, so they need two samples to compute; this
    returns the cumulative counters and 1/1024 s event times each frame carries.
    """
    flags = data[0]
    idx = 1
    result: dict = {}
    if flags & 0x01:  # wheel revolution data present
        result["cumulative_wheel_revolutions"] = int.from_bytes(data[idx : idx + 4], "little")
        result["last_wheel_event_time"] = int.from_bytes(data[idx + 4 : idx + 6], "little")
        idx += 6
    if flags & 0x02:  # crank revolution data present
        result["cumulative_crank_revolutions"] = int.from_bytes(data[idx : idx + 2], "little")
        result["last_crank_event_time"] = int.from_bytes(data[idx + 2 : idx + 4], "little")
    return result


def summarize_heart_rate(d: dict) -> str:
    extra = []
    if "sensor_contact" in d:
        extra.append("contact" if d["sensor_contact"] else "no contact")
    if d.get("rr"):
        extra.append(f"RR={d['rr']}")
    tail = f" ({', '.join(extra)})" if extra else ""
    return f"{d['bpm']} bpm{tail}"


def summarize_thermometer(d: dict) -> str:
    return f"{d['temperature']} \N{DEGREE SIGN}{d['unit']}"


def summarize_csc(d: dict) -> str:
    parts = []
    if "cumulative_wheel_revolutions" in d:
        parts.append(f"wheel {d['cumulative_wheel_revolutions']} rev")
    if "cumulative_crank_revolutions" in d:
        parts.append(f"crank {d['cumulative_crank_revolutions']} rev")
    return ", ".join(parts) or "(no data)"


#: name -> (characteristic UUID, decoder, summary formatter).
PROFILES = {
    "heart-rate": ("2a37", decode_heart_rate, summarize_heart_rate),
    "thermometer": ("2a1c", decode_health_thermometer, summarize_thermometer),
    "csc": ("2a5b", decode_csc, summarize_csc),
}


def detect_profile(client: Any) -> str | None:
    """Return the name of the first supported profile the device exposes, or None."""
    for name, (char_uuid, _decode, _fmt) in PROFILES.items():
        if find_characteristic(client, char_uuid) is not None:
            return name
    return None


async def _wait(timeout: float | None) -> None:
    if timeout:
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(timeout):
                await asyncio.Event().wait()
    else:
        await asyncio.Event().wait()


async def run_profile(args: argparse.Namespace) -> None:
    """Connect, subscribe to the chosen profile, and print decoded readings."""
    client = await connect(args.device, args.scan_timeout, args.connect_timeout)
    if client is None:
        return
    try:
        name = args.profile or detect_profile(client)
        if name is None:
            console.print(f"[yellow]Device exposes none of: {', '.join(PROFILES)}.[/yellow]")
            return
        char_uuid, decode, summarize = PROFILES[name]
        char = find_characteristic(client, char_uuid)
        if char is None:
            console.print(f"[yellow]Device does not expose the {name} profile.[/yellow]")
            return

        def handler(_sender: Any, data: Any) -> None:
            try:
                console.print(f"[green]{name}:[/green] {summarize(decode(bytes(data)))}")
            except (IndexError, ValueError):
                console.print(f"[yellow]{name}: undecodable frame {bytes(data).hex(' ')}[/yellow]")

        if "read" in char.properties:
            console.print(
                f"[green]{name}:[/green] {summarize(decode(await client.read_gatt_char(char)))}"
            )
        if {"notify", "indicate"} & set(char.properties):
            await client.start_notify(char, handler)
            window = f"for {args.timeout:g}s" if args.timeout else "until Ctrl-C"
            console.print(f"[cyan]Reading {name} {window}...[/cyan]")
            try:
                await _wait(args.timeout)
            finally:
                with contextlib.suppress(Exception):
                    await client.stop_notify(char)
    finally:
        if client.is_connected:
            await client.disconnect()
            console.print("[dim]Disconnected.[/dim]")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Read and decode a SIG measurement profile.")
    parser.add_argument("device", help="Device address or name")
    parser.add_argument(
        "-p",
        "--profile",
        choices=sorted(PROFILES),
        help="Which profile to read (default: auto-detect)",
    )
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
    await run_profile(args)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/yellow]")
