"""gatttool-compatible connection parameter management.

Provides connection parameter update/query functionality
matching bluez gatttool's ability to read/write connection parameters.
"""
import argparse
import asyncio
from bleak import BleakClient
from rich.console import Console

console = Console()

# UUIDs for connection parameters (Bluetooth Core Specification)
# Legacy Connection Parameter UUID: 0x2006 (in the Link Layer)
# But typically exposed via GATT:
CONN_PARAM_UUID = "00002006-0000-1000-8000-00805f9b34fb"

# These are the fields in the Connection Parameters Request PDU:
# - interval_min (16-bit, in 1.25ms units)
# - interval_max (16-bit, in 1.25ms units)
# - latency (16-bit, in number of events)
# - timeout (16-bit, in 10ms units)


async def read_connection_params(client: BleakClient) -> dict | None:
    """Read current connection parameters.

    Returns dict with interval_min, interval_max, latency, timeout,
    or None if not available.
    """
    try:
        # Bleak doesn't directly expose connection params.
        # We try reading the characteristic if it exists.
        try:
            value = await client.read_gatt_char(CONN_PARAM_UUID)
            if isinstance(value, (bytes, bytearray)) and len(value) >= 8:
                # Parse: interval_min, interval_max, latency, timeout
                # Each is 2 bytes big-endian
                import struct
                interval_min = struct.unpack("<H", value[0:2])[0]
                interval_max = struct.unpack("<H", value[2:4])[0]
                latency = struct.unpack("<H", value[4:6])[0]
                timeout = struct.unpack("<H", value[6:8])[0]
                # Convert to actual values
                # interval: 1.25ms units, so divide by 8 to get ms
                # latency: number of events
                # timeout: 10ms units
                return {
                    "interval_min": interval_min,
                    "interval_max": interval_max,
                    "latency": latency,
                    "timeout": timeout,
                    "interval_min_ms": interval_min * 1.25,
                    "interval_max_ms": interval_max * 1.25,
                }
        except Exception:
            pass

        # Also try 16-bit version
        try:
            value = await client.read_gatt_char("2006")
            if isinstance(value, (bytes, bytearray)) and len(value) >= 8:
                import struct
                interval_min = struct.unpack("<H", value[0:2])[0]
                interval_max = struct.unpack("<H", value[2:4])[0]
                latency = struct.unpack("<H", value[4:6])[0]
                timeout = struct.unpack("<H", value[6:8])[0]
                return {
                    "interval_min": interval_min,
                    "interval_max": interval_max,
                    "latency": latency,
                    "timeout": timeout,
                    "interval_min_ms": interval_min * 1.25,
                    "interval_max_ms": interval_max * 1.25,
                }
        except Exception:
            pass

    except Exception:
        pass
    return None


async def write_connection_params(
    client: BleakClient,
    interval_min: int,
    interval_max: int,
    latency: int,
    timeout: int,
) -> bool:
    """Write connection parameters to the device.

    Args:
        client: Connected BleakClient
        interval_min: Minimum connection interval (1.25ms units)
        interval_max: Maximum connection interval (1.25ms units)
        latency: Connection latency (number of events)
        timeout: Connection supervision timeout (10ms units)

    Returns:
        True if write succeeded
    """
    import struct
    # Pack as 8 bytes big-endian
    data = struct.pack("<HHHH", interval_min, interval_max, latency, timeout)
    try:
        # Write without response to the connection param characteristic
        await client.write_gatt_char(CONN_PARAM_UUID, data, response=False)
        console.print(
            f"[green]Connection parameters written:[/green]"
        )
        console.print(f"  interval_min: {interval_min} ({interval_min * 1.25:.1f}ms)")
        console.print(f"  interval_max: {interval_max} ({interval_max * 1.25:.1f}ms)")
        console.print(f"  latency: {latency}")
        console.print(f"  timeout: {timeout} ({(timeout * 10):.1f}ms)")
        return True
    except Exception as exc:
        console.print(f"[red]Failed to write connection params: {exc!r}[/red]")
        return False


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gatttool-compatible connection parameter management."
    )
    parser.add_argument("device", help="Device address or name")
    parser.add_argument(
        "--get", action="store_true",
        help="Read current connection parameters"
    )
    parser.add_argument(
        "--set", action="store_true",
        help="Set new connection parameters"
    )
    parser.add_argument(
        "--interval-min", type=int, default=None,
        help="Minimum connection interval (1.25ms units, default: 6-100 range)"
    )
    parser.add_argument(
        "--interval-max", type=int, default=None,
        help="Maximum connection interval (1.25ms units, default: 6-100 range)"
    )
    parser.add_argument(
        "--latency", type=int, default=None,
        help="Connection latency (number of events, default: 0-499)"
    )
    parser.add_argument(
        "--timeout", type=int, default=None,
        help="Supervision timeout (10ms units, default: 100-3200)"
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
        from ble_common import connect
        client = await connect(
            args.device,
            args.scan_timeout,
            args.connect_timeout,
        )
        if client is None:
            console.print("[red]Failed to connect.[/red]")
            return

        if args.get:
            params = await read_connection_params(client)
            if params:
                console.print("[cyan]Current connection parameters:[/cyan]")
                console.print(f"  interval_min: {params['interval_min']} ({params['interval_min_ms']:.1f}ms)")
                console.print(f"  interval_max: {params['interval_max']} ({params['interval_max_ms']:.1f}ms)")
                console.print(f"  latency: {params['latency']}")
                console.print(f"  timeout: {params['timeout']} ({params['timeout'] * 10:.1f}ms)")
            else:
                console.print(
                    "[yellow]Could not read connection parameters.[/yellow]"
                )

        elif args.set:
            if not all([args.interval_min, args.interval_max, args.latency, args.timeout]):
                console.print(
                    "[red]--set requires --interval-min, --interval-max, --latency, and --timeout[/red]"
                )
                return
            success = await write_connection_params(
                client,
                args.interval_min,
                args.interval_max,
                args.latency,
                args.timeout,
            )
            if not success:
                console.print("[red]Failed to set connection parameters.[/red]")

        else:
            console.print(
                "[cyan]Usage: gatt_params.py <device> [--get] | [--set ...][/cyan]"
            )
            console.print("  --get      Read current connection parameters")
            console.print(
                "  --set      Set new connection parameters (requires all 4 values)"
            )
            console.print(
                "    --interval-min: Min conn interval (1.25ms units)"
            )
            console.print(
                "    --interval-max: Max conn interval (1.25ms units)"
            )
            console.print(
                "    --latency: Connection latency (events)"
            )
            console.print(
                "    --timeout: Supervision timeout (10ms units)"
            )

    except Exception as exc:
        console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
    finally:
        if client is not None and client.is_connected:
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())