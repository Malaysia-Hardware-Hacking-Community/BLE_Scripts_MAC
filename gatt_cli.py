import argparse
import asyncio
import shlex

from rich.console import Console

from ble_common import (
    connect,
    find_characteristic,
    print_gatt_tables,
    show_value,
)

console = Console()


async def main():
    parser = argparse.ArgumentParser(description="Interactive BLE GATT client.")
    parser.add_argument("device")
    parser.add_argument("--scan-timeout", type=float, default=15)
    parser.add_argument("--connect-timeout", type=float, default=30)
    args = parser.parse_args()

    client = None
    subscriptions = set()

    try:
        client = await connect(args.device, args.scan_timeout, args.connect_timeout)
        console.print("[green]Connected.[/green]")
        print_gatt_tables(client)
        console.print(
            "\nCommands:\n"
            "  services\n"
            "  characteristics\n"
            "  descriptors\n"
            "  read HANDLE_OR_UUID\n"
            "  write-req HANDLE_OR_UUID HEX_BYTES\n"
            "  write-cmd HANDLE_OR_UUID HEX_BYTES\n"
            "  notify HANDLE_OR_UUID\n"
            "  indicate HANDLE_OR_UUID\n"
            "  unnotify HANDLE_OR_UUID\n"
            "  quit"
        )

        while True:
            try:
                parts = shlex.split(input("[gatt] ").strip())
            except (EOFError, KeyboardInterrupt):
                console.print()
                break

            if not parts:
                continue

            cmd = parts[0].lower()
            if cmd in {"quit", "exit"}:
                break
            if cmd == "services":
                print_gatt_tables(client)
                continue

            if cmd in {"characteristics", "descriptors"}:
                # Reuse the full, clear enumeration rather than hiding handles.
                print_gatt_tables(client)
                continue

            if cmd == "read" and len(parts) == 2:
                char = find_characteristic(client, parts[1])
                if char is None:
                    console.print("[red]Characteristic not found.[/red]")
                elif "read" not in char.properties:
                    console.print("[red]Not readable.[/red]")
                else:
                    try:
                        show_value(await client.read_gatt_char(char))
                    except Exception as exc:
                        console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
                continue

            if cmd in {"write-req", "write-cmd"} and len(parts) == 3:
                char = find_characteristic(client, parts[1])
                if char is None:
                    console.print("[red]Characteristic not found.[/red]")
                    continue

                response = cmd == "write-req"
                required = "write" if response else "write-without-response"
                if required not in char.properties:
                    console.print(f"[red]Characteristic lacks {required}.[/red]")
                    continue

                try:
                    payload = bytes.fromhex(parts[2])
                    await client.write_gatt_char(char, payload, response=response)
                    console.print(f"[green]Sent {len(payload)} byte(s).[/green]")
                except Exception as exc:
                    console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
                continue

            if cmd in {"notify", "indicate", "unnotify"} and len(parts) == 2:
                char = find_characteristic(client, parts[1])
                if char is None:
                    console.print("[red]Characteristic not found.[/red]")
                    continue

                key = char.handle
                if cmd == "unnotify":
                    if key not in subscriptions:
                        console.print(
                            "[yellow]No active subscription for that handle.[/yellow]"
                        )
                    else:
                        await client.stop_notify(char)
                        subscriptions.discard(key)
                        console.print("[green]Subscription stopped.[/green]")
                    continue

                acceptable = "notify" if cmd == "notify" else "indicate"
                if acceptable not in char.properties:
                    console.print(
                        f"[red]Characteristic lacks {acceptable} property.[/red]"
                    )
                    continue
                if key in subscriptions:
                    console.print("[yellow]Already subscribed.[/yellow]")
                    continue

                def callback(sender, data):
                    console.print(
                        f"\n[cyan]Update from {sender.uuid} "
                        f"(handle {sender.handle}):[/cyan]"
                    )
                    show_value(data)

                try:
                    await client.start_notify(char, callback)
                    subscriptions.add(key)
                    console.print("[green]Subscribed; use unnotify to stop.[/green]")
                except Exception as exc:
                    console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
                continue

            console.print("[yellow]Invalid command or arguments.[/yellow]")

    except Exception as exc:
        console.print(f"[red]{type(exc).__name__}: {exc!r}[/red]")
    finally:
        if client and client.is_connected:
            for service in client.services:
                for char in service.characteristics:
                    if char.handle in subscriptions:
                        try:
                            await client.stop_notify(char)
                        except Exception:
                            pass
            await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
