"""Manage saved device-target profiles.

A target profile is a short alias for a device name or address. Once saved, any
connecting tool accepts ``@alias`` in place of the full identifier, which is
handy on macOS where the address is a long per-host UUID that changes between
reboots. For example::

    wamble-targets add tv "[TV] Samsung Q60 Series"
    wamble-enum @tv

Profiles live in a small JSON file (see the ``path`` command). This tool only
reads and writes that file; it does not touch Bluetooth.
"""

import argparse

from rich.console import Console
from rich.table import Table

from wamble.common import load_targets, save_targets, targets_path

console = Console()


def cmd_list(_args: argparse.Namespace) -> None:
    targets = load_targets()
    if not targets:
        console.print("[yellow]No targets saved.[/yellow] Add one with 'add NAME IDENTIFIER'.")
        return
    table = Table(title="Saved target profiles", header_style="bold cyan")
    table.add_column("Alias", style="cyan", no_wrap=True)
    table.add_column("Identifier (name or address)", style="green", overflow="fold")
    for alias in sorted(targets):
        table.add_row(alias, targets[alias])
    console.print(table)


def cmd_add(args: argparse.Namespace) -> None:
    alias = args.name.lstrip("@")
    if not alias:
        console.print("[red]Alias must not be empty.[/red]")
        return
    targets = load_targets()
    existed = alias in targets
    targets[alias] = args.identifier
    save_targets(targets)
    verb = "Updated" if existed else "Saved"
    console.print(f"[green]{verb} target '@{alias}' -> {args.identifier!r}.[/green]")


def cmd_remove(args: argparse.Namespace) -> None:
    alias = args.name.lstrip("@")
    targets = load_targets()
    if alias not in targets:
        console.print(f"[yellow]No target named '@{alias}'.[/yellow]")
        return
    del targets[alias]
    save_targets(targets)
    console.print(f"[green]Removed target '@{alias}'.[/green]")


def cmd_path(_args: argparse.Namespace) -> None:
    console.print(str(targets_path()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage saved device-target profiles.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List saved target profiles").set_defaults(func=cmd_list)

    add = sub.add_parser("add", help="Save or update a target: add NAME IDENTIFIER")
    add.add_argument("name", help="Alias to save (the part after '@')")
    add.add_argument("identifier", help="Device name substring or address the alias maps to")
    add.set_defaults(func=cmd_add)

    remove = sub.add_parser("remove", help="Delete a saved target by name")
    remove.add_argument("name", help="Alias to remove")
    remove.set_defaults(func=cmd_remove)

    sub.add_parser("path", help="Print the profiles file path").set_defaults(func=cmd_path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
