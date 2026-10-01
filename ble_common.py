import asyncio
from typing import Any, Optional, Callable, Dict
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from rich.console import Console
from rich.table import Table

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
    # Device Information Service
    "180a": "Device Information",
    # Generic Access
    "1800": "Generic Access",
    "1801": "Generic Attribute",
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
    # Glucose
    "180e": "Glucose",
    # Heart Rate Control Point
    "2a39": "Heart Rate Control Point",
    # Glucose Measurement
    "2a18": "Glucose Measurement",
    # Heart Rate Measurement
    "2a37": "Heart Rate Measurement",
    # Pulse Oximetry
    "2a6e": "Pulse Oximetry",
    # Alert Notification
    "1812": "Alert Notification",
    # Scan Parameters
    "1813": "Scan Parameters",
}


def uuid16_from_128(uuid_128: str) -> Optional[str]:
    """Convert a 128-bit UUID string to its 16-bit representation if one exists.

    The Bluetooth spec stores 16-bit UUIDs in the first 2 bytes (octets 2-3)
    of a 128-bit UUID. After stripping the well-known prefix "0000", the next
    4 hex characters represent the 16-bit UUID.

    Returns the 16-bit hex string (without '0x' prefix) or None if no 16-bit
    equivalent is registered.
    """
    if not uuid_128:
        return None
    # Accept with or without dashes / braces
    clean = uuid_128.replace("-", "").replace("{", "").replace("}", "")
    if len(clean) != 32:
        return None
    # Remove the standard "0000" prefix (first 4 hex chars)
    # Valid 128-bit UUIDs in BLE have the form: 0000<16-bit>-...
    if clean.startswith("0000"):
        hex_16 = clean[4:8]  # the 16-bit UUID is here
    else:
        # Try without prefix - last 4 hex chars may be the 16-bit
        hex_16 = clean[-4:]
    try:
        val = int(hex_16, 16)
    except ValueError:
        return None
    # Check against known standard UUIDs (keys are 4-char lowercase hex)
    hex_key = f"{val:04x}"
    if hex_key in STANDARD_UUIDS:
        return hex_key
    # Also try the value as-is (might already be formatted)
    if hex_key.upper() in STANDARD_UUIDS:
        return hex_key.upper()
    return None


def is_standard_uuid(uuid_128: str) -> bool:
    """Return True if the 128-bit UUID resolves to a known 16-bit UUID."""
    return uuid16_from_128(uuid_128) is not None


async def find_device(
    identifier: str,
    timeout: float = 15.0,
    *,
    callback: Optional[Callable[[BLEDevice, Any], None]] = None,
) -> Optional[BLEDevice]:
    """Scan for a BLE device by address or name substring.

    Returns the BLEDevice if found within *timeout* seconds, else None.
    If *callback* is given it will be invoked for each discovered device
    (callback(device, advertisement)).
    """
    found: Optional[BLEDevice] = None

    def _cb(device: BLEDevice, adv: Any) -> None:
        nonlocal found
        if found is None:
            name = (device.name or adv.local_name or "").casefold()
            needle = str(identifier).casefold()
            if needle in name:
                found = device
        if callback is not None:
            callback(device, adv)

    scanner = BleakScanner(detection_callback=_cb)
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()
    return found


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
    """Find a characteristic by UUID substring or by property name.

    *specifier*: string to match against characteristic UUIDs (case-insensitive,
    substring match).  Use "readable" to find all characteristics with the
    ``read`` property, "writable" for write, "notify" for notify, "indicate"
    for indicate.
    *by*: "uuid" (default) or "property".
    """
    specifier = str(specifier).lower()
    services = enumerate_services(client)

    if by == "property":
        prop = specifier  # "read", "write", "notify", "indicate", etc.
        matching = []
        for _svc, chars in services:
            for ch in chars.values():
                props = {p for p in ch.properties}
                if prop in props:
                    matching.append(ch)
        return matching if matching else None

    # UUID/substring match
    for _svc, chars in services:
        for ch in chars.values():
            if specifier in str(ch.uuid).lower():
                return ch
    return None


def find_descriptor(
    client: BleakClient,
    char: Any,
    specifier: str = "",
) -> Optional[Any]:
    """Find a descriptor on a characteristic by UUID substring match."""
    if not specifier:
        # Return first descriptor if available
        descriptors = char.descriptors
        return descriptors[0] if descriptors else None
    specifier = str(specifier).lower()
    for d in char.descriptors:
        if specifier in str(d.uuid).lower():
            return d
    return None


class GATTTableBuilder:
    """Build a rich Table of GATT services/characteristics/descriptors.

    Usage:
        builder = GATTTableBuilder(title="GATT Services")
        builder.add_services(client)
        console.print(builder.table)
    """

    def __init__(self, title: str = "GATT Services", header_style: str = "bold cyan"):
        self.title = title
        self.header_style = header_style
        self._rows: list[tuple[str, ...]] = []
        self._services: list = []

    def add_services(self, client: BleakClient) -> "GATTTableBuilder":
        """Populate from a connected BleakClient."""
        self._services = enumerate_services(client)
        return self

    def _format_props(self, props: set[str]) -> str:
        """Render a characteristic's property set as a compact string."""
        ordered = []
        for p in ("broadcast", "read", "write-without-response", "write", "notify", "indicate"):
            if p in props:
                ordered.append(p.replace("-", " ").title())
        return ", ".join(ordered) if ordered else "—"

    def build(self) -> Table:
        table = Table(title=self.title, header_style=self.header_style)
        table.add_column("UUID", style="magenta", no_wrap=True)
        table.add_column("Handle", justify="right", style="dim")
        table.add_column("Properties", justify="center", style="green")
        table.add_column("Value", overflow="fold")

        for _svc, chars in self._services:
            for ch in chars.values():
                uuid_short = (
                    ch.uuid.split("-")[-1]
                    if "-" in str(ch.uuid)
                    else str(ch.uuid)[-4:]
                )
                self._rows.append((
                    uuid_short,
                    str(ch.handle),
                    self._format_props(ch.properties),
                    ""  # value placeholder
                ))

        for row in self._rows:
            table.add_row(*row)
        return table


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
    """Parse advertisement data from a Bleak advertisement object.

    Returns a dict with keys: 'local_name', 'service_uuids', 'manufacturer',
    'service_data' (maps 16-bit UUID hex -> bytes).
    """
    result = {
        "local_name": adv.local_name or "",
        "service_uuids": list(adv.service_uuids) if adv.service_uuids else [],
        "manufacturer": "",
        "service_data": {},
    }

    # Manufacturer data: adv.manufacturer_data is a dict of ad_type -> bytes
    md = adv.manufacturer_data or {}
    for ad_type, data in md.items():
        # Bleak uses the Bluetooth SIG company_id as the key
        # We'll just hex-encode it
        result["manufacturer"] = fmt_bytes(data)

    # Service data
    sd = adv.service_data or {}
    for uuid, data in sd.items():
        # uuid may be a 128-bit UUID object or string
        uuid_str = str(uuid).lower().replace("-", "")
        result["service_data"][uuid_str] = fmt_bytes(data)

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
    "read_gatt_char",
    "write_gatt_char",
    "parse_advertisement_data",
    "uuid16_from_128",
    "is_standard_uuid",
    "STANDARD_UUIDS",
]