"""Export a device's GATT tree to JSON, and diff two exports.

`wamble-export "Device"` connects, walks every service, characteristic and
descriptor, and writes a structured JSON snapshot (to a file with `-o`, or to
stdout). `wamble-export --diff old.json new.json` compares two snapshots offline
and reports what a firmware update (or a different unit) changed: services and
characteristics added or removed, descriptors added or removed, and
characteristic properties that changed.

The snapshot is deliberately stable and sorted so two exports of the same device
diff cleanly.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from bleak import BleakClient
from rich.console import Console

from wamble.common import add_connection_args, connect, short_uuid, uuid_name

console = Console()


def _descriptor_entry(desc: Any) -> dict:
    return {
        "uuid": str(desc.uuid),
        "short": short_uuid(desc.uuid),
        "name": uuid_name(desc.uuid),
        "handle": desc.handle,
    }


def _characteristic_entry(char: Any) -> dict:
    return {
        "uuid": str(char.uuid),
        "short": short_uuid(char.uuid),
        "name": uuid_name(char.uuid),
        "handle": char.handle,
        "properties": sorted(char.properties),
        "descriptors": sorted(
            (_descriptor_entry(d) for d in char.descriptors),
            key=lambda d: d["uuid"],
        ),
    }


def _service_entry(svc: Any) -> dict:
    return {
        "uuid": str(svc.uuid),
        "short": short_uuid(svc.uuid),
        "name": uuid_name(svc.uuid),
        "handle": getattr(svc, "handle", None),
        "characteristics": sorted(
            (_characteristic_entry(c) for c in svc.characteristics),
            key=lambda c: c["uuid"],
        ),
    }


def build_tree(client: BleakClient) -> dict:
    """Build the JSON-ready GATT snapshot for a connected *client*."""
    services = sorted(
        (_service_entry(s) for s in client.services),
        key=lambda s: s["uuid"],
    )
    return {
        "device": {"name": client.name, "address": str(client.address)},
        "exported_at": datetime.now(UTC).isoformat(),
        "services": services,
    }


def _char_map(tree: dict) -> dict[tuple[str, str], dict]:
    """Map (service uuid, characteristic uuid) -> characteristic entry."""
    out: dict[tuple[str, str], dict] = {}
    for svc in tree.get("services", []):
        for char in svc.get("characteristics", []):
            out[(svc["uuid"], char["uuid"])] = char
    return out


def _descriptor_keys(tree: dict) -> set[tuple[str, str, str]]:
    """Set of (service uuid, characteristic uuid, descriptor uuid)."""
    keys: set[tuple[str, str, str]] = set()
    for svc in tree.get("services", []):
        for char in svc.get("characteristics", []):
            for desc in char.get("descriptors", []):
                keys.add((svc["uuid"], char["uuid"], desc["uuid"]))
    return keys


def diff_trees(old: dict, new: dict) -> dict:
    """Compare two GATT snapshots and return a structured diff.

    The result lists services and characteristics added or removed, descriptors
    added or removed, and characteristics whose property set changed. UUIDs
    identify attributes, so a reordered export produces no spurious diff.
    """
    old_svcs = {s["uuid"] for s in old.get("services", [])}
    new_svcs = {s["uuid"] for s in new.get("services", [])}
    old_chars, new_chars = _char_map(old), _char_map(new)
    old_descs, new_descs = _descriptor_keys(old), _descriptor_keys(new)

    properties_changed = []
    for key in old_chars.keys() & new_chars.keys():
        before = old_chars[key]["properties"]
        after = new_chars[key]["properties"]
        if before != after:
            properties_changed.append(
                {
                    "service": key[0],
                    "characteristic": key[1],
                    "from": before,
                    "to": after,
                }
            )

    return {
        "services_added": sorted(new_svcs - old_svcs),
        "services_removed": sorted(old_svcs - new_svcs),
        "characteristics_added": sorted(new_chars.keys() - old_chars.keys()),
        "characteristics_removed": sorted(old_chars.keys() - new_chars.keys()),
        "descriptors_added": sorted(new_descs - old_descs),
        "descriptors_removed": sorted(old_descs - new_descs),
        "properties_changed": properties_changed,
    }


def diff_is_empty(diff: dict) -> bool:
    """True when the two snapshots are equivalent."""
    return not any(diff.values())


def render_diff(diff: dict) -> None:
    """Print a structured diff as readable lines."""
    if diff_is_empty(diff):
        console.print("[green]No differences: the two snapshots match.[/green]")
        return

    for uuid in diff["services_added"]:
        console.print(f"[green]+ service[/green] {short_uuid(uuid)}")
    for uuid in diff["services_removed"]:
        console.print(f"[red]- service[/red] {short_uuid(uuid)}")
    for svc, char in diff["characteristics_added"]:
        console.print(f"[green]+ char[/green] {short_uuid(char)} (service {short_uuid(svc)})")
    for svc, char in diff["characteristics_removed"]:
        console.print(f"[red]- char[/red] {short_uuid(char)} (service {short_uuid(svc)})")
    for _svc, char, desc in diff["descriptors_added"]:
        console.print(f"[green]+ descr[/green] {short_uuid(desc)} (char {short_uuid(char)})")
    for _svc, char, desc in diff["descriptors_removed"]:
        console.print(f"[red]- descr[/red] {short_uuid(desc)} (char {short_uuid(char)})")
    for change in diff["properties_changed"]:
        before = ",".join(change["from"]) or "(none)"
        after = ",".join(change["to"]) or "(none)"
        console.print(
            f"[yellow]~ char[/yellow] {short_uuid(change['characteristic'])} "
            f"properties: {before} -> {after}"
        )


def load_tree(path: str) -> dict:
    """Load a snapshot JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_diff(old_path: str, new_path: str) -> None:
    """Load two snapshots and print their diff."""
    old, new = load_tree(old_path), load_tree(new_path)
    console.print(f"[dim]diff {old_path} -> {new_path}[/dim]")
    render_diff(diff_trees(old, new))


async def run_export(args: argparse.Namespace) -> None:
    """Connect, build the snapshot, and write it to a file or stdout."""
    client = await connect(args.device, args.scan_timeout, args.connect_timeout)
    if client is None:
        return
    try:
        tree = build_tree(client)
    finally:
        if client.is_connected:
            await client.disconnect()
            console.print("[dim]Disconnected.[/dim]")

    text = json.dumps(tree, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        console.print(f"[green]GATT snapshot written to {args.output}[/green]")
    else:
        print(text)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a device's GATT tree to JSON, or diff two exports."
    )
    parser.add_argument("device", nargs="?", help="Device address or name (omit with --diff)")
    parser.add_argument("-o", "--output", help="Write the snapshot to this file (default: stdout)")
    parser.add_argument(
        "--diff",
        nargs=2,
        metavar=("OLD", "NEW"),
        help="Compare two snapshot files and print the differences (no device needed)",
    )
    add_connection_args(parser)
    args = parser.parse_args()

    if args.diff:
        run_diff(args.diff[0], args.diff[1])
        return
    if not args.device:
        parser.error("a device is required unless --diff is given")
    await run_export(args)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
