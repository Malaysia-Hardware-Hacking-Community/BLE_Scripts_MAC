import asyncio
from typing import Any, Optional, Callable, Dict
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


#: Standard 16-bit UUIDs for commonly-queried BLE services and characteristics
#: See https://www.bluetooth.com/specifications/assigned-numbers/
STANDARD_UUIDS: Dict[str, str] = {
    # Generic Access / Generic Attribute
    "1800": "Generic Access",
    "1801": "Generic Attribute",
    # Device Information
    "180a": "Device Information",
    # Alert
    "1802": "Alert",
    # Battery
    "180f": "Battery",
    # Health Thermometer
    "1809": "Health Thermometer",
    # Heart Rate
    "180d": "Heart Rate",
    # Cyclist Power
    "1818": "Cyclist Power",
    # Phone Alert
    "180e": "Phone Alert",
    # Running Cadence
    "1814": "Running Cadence",
    # Fitness Machine
    "1826": "Fitness Machine",
    # Continuous Spo2
    "1822": "Continuous SpO2",
    # Body Composition
    "181d": "Body Composition",
    # Alert Notification
    "1812": "Alert Notification",
    # Scan Parameters
    "1813": "Scan Parameters",
    # Device Name / Appearance, under Generic Access
    "2a00": "Device Name",
    "2a01": "Appearance",
    # Battery Level / Battery Power, under Battery
    "2a19": "Battery Level",
    "2a1a": "Battery Power",
    # Glucose
    "2a18": "Glucose Measurement",
    "2a39": "Heart Rate Control Point",
    # Heart Rate
    "2a37": "Heart Rate Measurement",
    "2a38": "Body Sensor Location",
    # Pulse Oximetry
    "2a6e": "Pulse Oximetry",
}


def uuid16_from_128(uuid_128: str) -> Optional[str]:
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


def is_standard_uuid(uuid_128: str) -> bool:
    """Return True if the UUID is a base UUID listed in :data:`STANDARD_UUIDS`."""
    hex_16 = uuid16_from_128(uuid_128)
    return hex_16 is not None and hex_16 in STANDARD_UUIDS


def short_uuid(uuid_128: str) -> str:
    """Render a UUID compactly: '180f' for SIG base UUIDs, else the full string."""
    hex_16 = uuid16_from_128(uuid_128)
    return hex_16 if hex_16 is not None else str(uuid_128)


async def find_device(
    identifier: str,
    timeout: float = 15.0,
    *,
    callback: Optional[Callable[[BLEDevice, Any], None]] = None,
) -> Optional[BLEDevice]:
    """Scan for a BLE device by address or name, returning as soon as it matches.

    *identifier* is matched case-insensitively against the device address and
    then as a substring of the advertised local name.

    Returns the BLEDevice on first match, or None if *timeout* elapses first.
    If *callback* is given it is invoked for every device seen before the match.

    Note:
        On Windows (and Linux) ``BLEDevice.address`` is the peripheral's real
        Bluetooth MAC, so either the address or a name substring works. On macOS
        it is a CoreBluetooth-generated UUID scoped to this Mac, not the real
        MAC, and it changes between reboots — there, prefer a name substring.
    """
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
) -> Optional[BleakClient]:
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
    except Exception as exc:
        console.print(f"[red]Connection failed: {exc!r}[/red]")
        return None


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
) -> Optional[Any]:
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
        matching = []
        for _svc, chars in enumerate_services(client):
            for ch in chars.values():
                if prop in set(ch.properties):
                    matching.append(ch)
        return matching or None

    found = resolve_target(client, specifier)
    if found is None or is_descriptor(found):
        return None
    return found


def find_descriptor(
    client: BleakClient,
    char: Any,
    specifier: str = "",
) -> Optional[Any]:
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

    @staticmethod
    def _format_props(props: set) -> str:
        """Render a characteristic's property set as a compact string."""
        ordered = []
        for p in ("broadcast", "read", "write-without-response", "write", "notify", "indicate"):
            if p in props:
                ordered.append(p.replace("-", " ").title())
        return ", ".join(ordered) if ordered else "—"

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
                    self._format_props(ch.properties),
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
                desc_table.add_row(
                    short_uuid(ch.uuid), short_uuid(desc.uuid), str(desc.handle)
                )
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
    val = await client.read_gatt_char(ch)
    return val


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
    "fmt_bytes",
    "decode_bytes",
    "show_value",
    "find_device",
    "connect",
    "enumerate_services",
    "find_characteristic",
    "find_descriptor",
    "GATTTableBuilder",
    "print_gatt_tables",
    "print_services_table",
    "print_characteristics_table",
    "print_descriptors_table",
    "read_gatt_char",
    "write_gatt_char",
    "parse_advertisement_data",
    "uuid16_from_128",
    "is_standard_uuid",
    "short_uuid",
    "BASE_UUID_SUFFIX",
    "STANDARD_UUIDS",
]