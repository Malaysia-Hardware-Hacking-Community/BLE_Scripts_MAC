import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bleak import BleakClient, BleakScanner, normalize_uuid_str
from bleak.backends.device import BLEDevice
from rich.console import Console
from rich.table import Table

#: Everything after the first dash of a Bluetooth SIG base UUID, i.e. the tail
#: of ``0000xxxx-0000-1000-8000-00805f9b34fb``.
BASE_UUID_SUFFIX = "0000-1000-8000-00805f9b34fb"

console = Console()


def fmt_bytes(data: Any) -> str:
    """Format bytes as hex string with spacing. Returns '(empty)' for empty/None."""
    if data is None:
        return "(empty)"
    try:
        b = bytes(data)
    except Exception:
        return "(invalid)"
    if len(b) == 0:
        return "(empty)"
    return b.hex(" ")


def decode_bytes(data: Any) -> str:
    """Decode bytes to UTF-8 string, stripping null bytes. Returns '' on failure."""
    if data is None:
        return ""
    try:
        b = bytes(data)
    except Exception:
        return ""
    try:
        return b.decode("utf-8").rstrip("\x00")
    except UnicodeDecodeError:
        return ""


def show_value(data: Any, label: str = "") -> None:
    """Print hex and text representation of a characteristic value."""
    hex_str = fmt_bytes(data)
    console.print(f"  {label}Hex:  {hex_str}" if label else f"  Hex:  {hex_str}")
    text = decode_bytes(data)
    if text:
        console.print(f"  {label}Text: {text}" if label else f"  Text: {text}")


#: Canonical display order for the GATT characteristic properties we surface.
#: Any vendor or extended-property flags outside this set are not shown.
DISPLAYED_PROPERTIES = (
    "broadcast",
    "read",
    "write-without-response",
    "write",
    "notify",
    "indicate",
)


def format_properties(props, empty: str = "—") -> str:
    """Render a characteristic's property set in canonical order, Title-Cased.

    Only the properties in :data:`DISPLAYED_PROPERTIES` are shown, each with its
    hyphen turned to a space and title-cased (``"write-without-response"`` ->
    ``"Write Without Response"``). Returns *empty* when none are present. This is
    the single formatter behind every characteristic table in the toolkit.
    """
    present = set(props)
    ordered = [p.replace("-", " ").title() for p in DISPLAYED_PROPERTIES if p in present]
    return ", ".join(ordered) if ordered else empty


#: Standard Bluetooth ATT error codes (Core Spec Vol 3, Part F, 3.4.1.1) that a
#: peripheral returns to reject a request. Codes outside this table, including the
#: 0x80-0x9F application range and the 0xE0-0xFF profile range, are vendor defined;
#: a locked-down consumer device commonly returns one of those to mean the same
#: thing as "authentication required", that is, pair with me first.
ATT_ERROR_NAMES = {
    0x01: "invalid handle",
    0x02: "read not permitted",
    0x03: "write not permitted",
    0x04: "invalid request",
    0x05: "authentication required",
    0x06: "request not supported",
    0x07: "invalid offset",
    0x08: "authorization required",
    0x09: "prepare queue full",
    0x0A: "attribute not found",
    0x0B: "attribute not long",
    0x0C: "encryption key size too short",
    0x0D: "invalid value length",
    0x0E: "unlikely error",
    0x0F: "encryption required",
    0x10: "unsupported group type",
    0x11: "insufficient resources",
    0x12: "database out of sync",
    0x13: "value not allowed",
}

#: Standard ATT codes that mean the device understood the request and chose to
#: refuse it on permission or security grounds, rather than a transport or tooling
#: fault. The vendor ranges above are treated the same way by :func:`is_gatt_refusal`.
_ATT_REFUSAL_CODES = frozenset({0x02, 0x03, 0x05, 0x08, 0x0C, 0x0F})


def gatt_error_code(exc: BaseException) -> int | None:
    """Return the ATT error code carried by a bleak GATT exception, or None.

    bleak exposes the code as ``exc.code`` on most backends; on some it only
    appears as the first element of ``exc.args``. This checks both.
    """
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None


def is_gatt_refusal(exc: BaseException) -> bool:
    """True when *exc* is the device deliberately refusing a read or write.

    A refusal is a normal answer from a device that wants pairing or has a
    characteristic locked down, so callers report it as information rather than as
    a tool error. Covers the standard permission and security ATT codes and the
    vendor code ranges that consumer devices return to mean the same thing.
    """
    code = gatt_error_code(exc)
    if code is None:
        return False
    return code in _ATT_REFUSAL_CODES or 0x80 <= code <= 0x9F or 0xE0 <= code <= 0xFF


def describe_gatt_error(exc: BaseException) -> str:
    """Render a GATT read or write failure as a short, plain reason.

    Standard ATT codes become their spec name. Vendor codes (the 0x80-0x9F and
    0xE0-0xFF ranges) are reported as the device declining the request, which on a
    consumer device almost always means it wants pairing or a vendor handshake
    first. Anything without a code falls back to the exception's own message.
    """
    code = gatt_error_code(exc)
    if code is None:
        return str(exc) or type(exc).__name__
    name = ATT_ERROR_NAMES.get(code)
    if name is not None:
        return f"{name} (0x{code:02X})"
    if 0x80 <= code <= 0x9F or 0xE0 <= code <= 0xFF:
        return f"device declined, likely needs pairing (0x{code:02X})"
    return f"device declined (0x{code:02X})"


def uuid16_from_128(uuid_128: str) -> str | None:
    """Reduce a 128-bit UUID to its 16-bit form, if it is a Bluetooth SIG base UUID.

    Accepts 16-bit, 32-bit or 128-bit input. Returns the lowercase 16-bit hex
    string (no ``0x`` prefix), or None if *uuid_128* is not a SIG base UUID.

    >>> uuid16_from_128("0000180f-0000-1000-8000-00805f9b34fb")
    '180f'
    >>> uuid16_from_128("180F")
    '180f'
    >>> uuid16_from_128("12345678-0000-1234-1234-1234567890ab") is None
    True
    """
    try:
        normalized = normalize_uuid_str(str(uuid_128).strip())
    except (AttributeError, TypeError, ValueError):
        return None
    prefix, _, suffix = normalized.partition("-")
    if suffix != BASE_UUID_SUFFIX:
        return None
    hex_16 = prefix[4:]
    return hex_16 if len(hex_16) == 4 else None


def short_uuid(uuid_128: str) -> str:
    """Render a UUID compactly: '180f' for SIG base UUIDs, else the full string."""
    hex_16 = uuid16_from_128(uuid_128)
    return hex_16 if hex_16 is not None else str(uuid_128)


def targets_path() -> Path:
    """Location of the saved device-target profiles file.

    Overridable with ``$WAMBLE_TARGETS`` (which the tests use). Otherwise it is
    ``$XDG_CONFIG_HOME/wamble/targets.json`` (``~/.config/wamble/targets.json``
    by default) on macOS and Linux, and ``%APPDATA%\\wamble\\targets.json`` on
    Windows.
    """
    override = os.environ.get("WAMBLE_TARGETS")
    if override:
        return Path(override)
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "wamble" / "targets.json"


def load_targets(path: Path | None = None) -> dict[str, str]:
    """Return the saved ``alias -> identifier`` map, or ``{}`` if none is saved.

    A missing or unreadable file, or one whose contents are not a JSON object,
    yields an empty map rather than an error, so a corrupt file never stops a
    tool from running. Only string values are kept.
    """
    path = path or targets_path()
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, str)}


def save_targets(targets: dict[str, str], path: Path | None = None) -> None:
    """Write the ``alias -> identifier`` map, creating the parent directory."""
    path = path or targets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(targets, f, indent=2, sort_keys=True)


def resolve_target(identifier: str, path: Path | None = None) -> str:
    """Expand a saved ``@alias`` to its identifier; pass anything else through.

    A leading ``@`` marks a saved target name (see :func:`targets_path`). An
    unknown alias is returned unchanged, so the caller's own "not found"
    handling still applies.

    >>> resolve_target("Living Room")
    'Living Room'
    """
    text = str(identifier)
    if not text.startswith("@"):
        return text
    return load_targets(path).get(text[1:], text)


async def find_device(
    identifier: str,
    timeout: float = 15.0,
    *,
    callback: Callable[[BLEDevice, Any], None] | None = None,
) -> BLEDevice | None:
    """Scan for a BLE device by address or name, returning as soon as it matches.

    *identifier* is matched case-insensitively against the device address and
    then as a substring of the advertised local name.

    Returns the BLEDevice on first match, or None if *timeout* elapses first.
    If *callback* is given it is invoked for every device seen before the match.

    Note:
        On Windows (and Linux) ``BLEDevice.address`` is the peripheral's real
        Bluetooth MAC, so either the address or a name substring works. On macOS
        it is a CoreBluetooth-generated UUID scoped to this Mac, not the real
        MAC, and it changes between reboots, so prefer a name substring there.
    """
    # Expand a saved "@alias" to the real name or address before matching, so
    # every connecting tool accepts a target profile with no extra work.
    identifier = resolve_target(identifier)
    # Strip surrounding whitespace: an address pasted from a wrapped table cell
    # or a shell prompt often carries a leading/trailing space or newline, which
    # would otherwise defeat the exact address comparison below.
    needle = str(identifier).strip().casefold()

    def _matches(device: BLEDevice, adv: Any) -> bool:
        if needle == str(device.address).strip().casefold():
            return True
        name = (device.name or adv.local_name or "").casefold()
        return bool(needle) and needle in name

    scanner = BleakScanner()
    try:
        async with scanner:
            async with asyncio.timeout(timeout):
                async for device, adv in scanner.advertisement_data():
                    if callback is not None:
                        callback(device, adv)
                    if _matches(device, adv):
                        return device
    except TimeoutError:
        pass
    return None


async def connect(
    identifier: str,
    scan_timeout: float = 15.0,
    connect_timeout: float = 30.0,
    *,
    background: bool = False,
) -> BleakClient | None:
    """Connect to a BLE device identified by address or name.

    Returns a BleakClient on success, or None on failure.
    """
    device = await find_device(identifier, scan_timeout)
    if device is None:
        console.print(f"[red]Device '{identifier}' not found.[/red]")
        return None

    console.print(f"[green]Found device: {device.name!r} [{device.address}][/green]")
    try:
        client = BleakClient(device)
        await client.connect(timeout=connect_timeout)
        if background:
            return client
        # Verify connection
        if not client.is_connected:
            console.print("[red]Connection not confirmed.[/red]")
            return None
        console.print("[green]Connected.[/green]")
        return client
    except TimeoutError:
        console.print(
            f"[red]Connection timed out after {connect_timeout:g}s. The device may be "
            f"out of range, already connected elsewhere, or not accepting connections.[/red]"
        )
        return None
    except Exception as exc:
        # bleak error messages are usually descriptive; fall back to the type name
        # for the rare one that stringifies to empty.
        console.print(f"[red]Connection failed: {exc or type(exc).__name__}[/red]")
        return None


def add_connection_args(parser, *, scan_default: float = 15, connect_default: float = 30) -> None:
    """Add the standard ``--scan-timeout`` and ``--connect-timeout`` options.

    Every connecting tool takes the same two options, so defining them in one
    place keeps their names, defaults, and help text identical across the toolkit.
    """
    parser.add_argument(
        "--scan-timeout",
        type=float,
        default=scan_default,
        help=f"Seconds to scan for the device (default: {scan_default:g})",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=connect_default,
        help=f"Seconds to wait for the connection (default: {connect_default:g})",
    )


def enumerate_services(client: BleakClient) -> list:
    """Return a flat list of (service, characteristics_dict) tuples.

    Each characteristics_dict maps uuid -> characteristic object for quick lookup.
    """
    results = []
    for service in client.services:
        chars = {}
        for ch in service.characteristics:
            chars[ch.uuid] = ch
        results.append((service, chars))
    return results


def find_characteristic(
    client: BleakClient,
    specifier: str,
    *,
    by: str = "uuid",
) -> Any | None:
    """Find a characteristic by handle, UUID substring, or property name.

    *specifier*: matched case-insensitively against characteristic UUIDs, or
    resolved as a handle when it is all digits or ``0x``-prefixed hex.  Use
    "readable" to find all characteristics with the ``read`` property,
    "writable" for write, "notify" for notify, "indicate" for indicate.
    *by*: "uuid" (default) or "property".

    Note:
        ``by="property"`` still returns a *list*; the other modes return a
        single characteristic or ``None``.
    """
    # Imported here, not at module scope: ble_gatt imports short_uuid from this
    # module, so a top-level import would be circular.
    from ble_gatt import is_descriptor, resolve_target

    if by == "property":
        prop = str(specifier).lower()  # "read", "write", "notify", "indicate", etc.
        matching = [
            ch
            for _svc, chars in enumerate_services(client)
            for ch in chars.values()
            if prop in ch.properties
        ]
        return matching or None

    found = resolve_target(client, specifier)
    if found is None or is_descriptor(found):
        return None
    return found


def find_descriptor(
    char: Any,
    specifier: str = "",
) -> Any | None:
    """Find a descriptor on a characteristic by UUID substring or handle.

    With no *specifier*, returns the characteristic's first descriptor.
    A handle-shaped *specifier* is matched against ``desc.handle`` first, then
    as a UUID substring.
    """
    from ble_gatt import as_handle

    if not specifier:
        descriptors = char.descriptors
        return descriptors[0] if descriptors else None

    text = str(specifier).strip()
    needle = text.casefold()
    handle = as_handle(text)
    if handle is not None:
        for desc in char.descriptors:
            if desc.handle == handle:
                return desc

    for desc in char.descriptors:
        if needle in str(desc.uuid).casefold():
            return desc
    return None


class GATTTableBuilder:
    """Build a rich Table of a connected client's GATT characteristics.

    Usage:
        builder = GATTTableBuilder(title="GATT Attributes")
        builder.add_services(client)
        console.print(builder.build())
    """

    def __init__(self, title: str = "GATT Services", header_style: str = "bold cyan"):
        self.title = title
        self.header_style = header_style
        self._services: list = []

    @property
    def services(self) -> list:
        """The (service, characteristics_dict) pairs loaded by :meth:`add_services`."""
        return self._services

    def add_services(self, client: BleakClient) -> "GATTTableBuilder":
        """Populate from a connected BleakClient."""
        self._services = enumerate_services(client)
        return self

    def build(self) -> Table:
        """Render the loaded characteristics as a rich Table.

        Safe to call more than once; rows are rebuilt from scratch each call.
        """
        table = Table(title=self.title, header_style=self.header_style)
        table.add_column("Service", style="cyan", no_wrap=True)
        table.add_column("UUID", style="magenta", no_wrap=True)
        table.add_column("Name", style="blue", overflow="fold")
        table.add_column("Handle", justify="right", style="dim")
        table.add_column("Properties", justify="center", style="green")

        for _svc, chars in self._services:
            for ch in chars.values():
                table.add_row(
                    short_uuid(_svc.uuid),
                    short_uuid(ch.uuid),
                    ch.description or "—",
                    str(ch.handle),
                    format_properties(ch.properties),
                )
        return table


def print_services_table(client: BleakClient) -> None:
    """Print just the services: UUID, handle, description and characteristic count."""
    table = Table(title="GATT Services", header_style="bold cyan")
    # One UUID column via short_uuid: compact "1800" for SIG services, full
    # 128-bit for vendor ones. Two UUID columns would crowd out the rest.
    table.add_column("UUID", style="cyan", no_wrap=True)
    table.add_column("Handle", justify="right", style="dim")
    table.add_column("Description", style="blue", overflow="fold")
    table.add_column("Chars", justify="right", style="green")

    count = 0
    for service in client.services:
        table.add_row(
            short_uuid(service.uuid),
            str(getattr(service, "handle", "—")),
            getattr(service, "description", None) or "—",
            str(len(service.characteristics)),
        )
        count += 1
    if count:
        console.print(table)
    else:
        console.print("[dim]No services exposed.[/dim]")


def print_characteristics_table(client: BleakClient) -> None:
    """Print just the characteristics table."""
    builder = GATTTableBuilder(title="GATT Characteristics")
    builder.add_services(client)
    console.print(builder.build())


def print_descriptors_table(client: BleakClient) -> None:
    """Print just the descriptors table, or a note when there are none."""
    desc_table = Table(title="GATT Descriptors", header_style="bold cyan")
    desc_table.add_column("Characteristic", style="cyan", no_wrap=True)
    desc_table.add_column("Descriptor", style="magenta", no_wrap=True)
    desc_table.add_column("Handle", justify="right", style="dim")

    rows = 0
    for _svc, chars in enumerate_services(client):
        for ch in chars.values():
            for desc in ch.descriptors:
                desc_table.add_row(short_uuid(ch.uuid), short_uuid(desc.uuid), str(desc.handle))
                rows += 1

    if rows:
        console.print(desc_table)
    else:
        console.print("[dim]No descriptors exposed.[/dim]")


def print_gatt_tables(client: BleakClient) -> None:
    """Print a connected client's full GATT tree: characteristics, then descriptors.

    Used by the CTF client's ``enum`` to show the complete picture at once.
    """
    print_characteristics_table(client)
    print_descriptors_table(client)


async def read_gatt_char(client: BleakClient, uuid_or_handle: str | int) -> Any:
    """Read a characteristic value by UUID or handle, with pretty printing.

    Returns the raw bytes value.
    """
    ch = find_characteristic(client, str(uuid_or_handle), by="uuid")
    if ch is None:
        raise RuntimeError(f"Characteristic {uuid_or_handle!r} not found")
    return await client.read_gatt_char(ch)


async def write_gatt_char(
    client: BleakClient,
    uuid_or_handle: str | int,
    data: bytes | str,
    without_response: bool = False,
) -> None:
    """Write data to a characteristic.

    *without_response*: use WRITE without response (default False → WRITE with response).
    """
    ch = find_characteristic(client, str(uuid_or_handle), by="uuid")
    if ch is None:
        raise RuntimeError(f"Characteristic {uuid_or_handle!r} not found")
    data_bytes = bytes(data) if not isinstance(data, bytes) else data
    await client.write_gatt_char(ch, data_bytes, response=not without_response)


def parse_advertisement_data(adv: Any) -> dict:
    """Extract display-ready fields from a bleak AdvertisementData.

    Returns a dict with keys ``local_name``, ``service_uuids`` (list of compact
    UUID strings), ``manufacturer`` (a ``"0xCOMPANY: bytes"`` string covering
    every manufacturer block, or "") and ``service_data`` (maps compact UUID
    string -> hex string).
    """
    result = {
        "local_name": adv.local_name or "",
        "service_uuids": [short_uuid(u) for u in (adv.service_uuids or [])],
        "manufacturer": "",
        "service_data": {},
    }

    # manufacturer_data maps Bluetooth SIG company identifier -> payload.
    # Apple is 0x004C, which is the interesting one for iBeacon/AirDrop-style
    # devices, so keep the company id rather than dumping the bytes alone.
    parts = []
    for company_id, data in (adv.manufacturer_data or {}).items():
        parts.append(f"0x{int(company_id):04X}: {fmt_bytes(data)}")
    result["manufacturer"] = "; ".join(parts)

    for uuid, data in (adv.service_data or {}).items():
        result["service_data"][short_uuid(uuid)] = fmt_bytes(data)

    return result


__all__ = [
    "ATT_ERROR_NAMES",
    "BASE_UUID_SUFFIX",
    "DISPLAYED_PROPERTIES",
    "GATTTableBuilder",
    "add_connection_args",
    "connect",
    "decode_bytes",
    "describe_gatt_error",
    "enumerate_services",
    "find_characteristic",
    "find_descriptor",
    "find_device",
    "fmt_bytes",
    "format_properties",
    "gatt_error_code",
    "is_gatt_refusal",
    "load_targets",
    "parse_advertisement_data",
    "print_characteristics_table",
    "print_descriptors_table",
    "print_gatt_tables",
    "print_services_table",
    "read_gatt_char",
    "resolve_target",
    "save_targets",
    "short_uuid",
    "show_value",
    "targets_path",
    "uuid16_from_128",
    "write_gatt_char",
]
