"""Identify what an advertising device actually is, from its advertisement data.

A BLE advertisement rarely carries a friendly name, but it usually carries a
manufacturer company ID and, for beacons, a recognisable frame. This module
turns those into something readable: the vendor's name, the beacon type, and a
short identity label used to fill in the blank for ``(unnamed)`` devices.

The company-ID table is a curated subset of the Bluetooth SIG assigned numbers,
covering the vendors seen most often in a consumer scan. It is deliberately not
the full ~3,500-entry list; an unknown ID is shown as its hex code rather than
guessed at.
"""

from typing import Any

from wamble.common import fmt_bytes

#: Curated Bluetooth SIG company identifiers (company ID -> name). Common
#: consumer vendors only; extend as needed.
COMPANY_IDS: dict[int, str] = {
    0x0001: "Nokia",
    0x0006: "Microsoft",
    0x000D: "Texas Instruments",
    0x0059: "Nordic Semiconductor",
    0x0075: "Samsung Electronics",
    0x0078: "Nike",
    0x0087: "Garmin",
    0x00E0: "Google",
    0x0157: "Anhui Huami (Amazfit / Mi Band)",
    0x0171: "Amazon",
    0x038F: "Xiaomi",
    0x0499: "Ruuvi Innovations",
    0x004C: "Apple",
    0x02E5: "Espressif",
    0x05A7: "Sonos",
    0x0822: "Adafruit",
}

#: Eddystone service UUID (16-bit) and the Apple company ID used by iBeacon.
EDDYSTONE_UUID_16 = "feaa"
APPLE_COMPANY_ID = 0x004C

_EDDYSTONE_FRAMES = {0x00: "Eddystone-UID", 0x10: "Eddystone-URL", 0x20: "Eddystone-TLM"}
_URL_SCHEMES = {0x00: "http://www.", 0x01: "https://www.", 0x02: "http://", 0x03: "https://"}
_URL_EXPANSIONS = {
    0x00: ".com/",
    0x01: ".org/",
    0x02: ".edu/",
    0x03: ".net/",
    0x04: ".info/",
    0x05: ".biz/",
    0x06: ".gov/",
    0x07: ".com",
    0x08: ".org",
    0x09: ".edu",
    0x0A: ".net",
    0x0B: ".info",
    0x0C: ".biz",
    0x0D: ".gov",
}


def company_name(company_id: int) -> str | None:
    """Return the vendor name for a SIG company ID, or None if not in the table."""
    return COMPANY_IDS.get(company_id)


def _short_of(uuid: Any) -> str:
    """The 16-bit tail of a service-data UUID key, lowercased (or the key itself)."""
    text = str(uuid).lower()
    return text[4:8] if len(text) >= 8 and text.endswith("-0000-1000-8000-00805f9b34fb") else text


def parse_ibeacon(payload: bytes) -> dict | None:
    """Parse an Apple-manufacturer payload as an iBeacon, or None if it is not one.

    An iBeacon payload is ``02 15`` then a 16-byte proximity UUID, a 2-byte
    major, a 2-byte minor and a 1-byte signed measured power.
    """
    if len(payload) < 23 or payload[0] != 0x02 or payload[1] != 0x15:
        return None
    uuid = payload[2:18].hex()
    return {
        "uuid": f"{uuid[0:8]}-{uuid[8:12]}-{uuid[12:16]}-{uuid[16:20]}-{uuid[20:32]}",
        "major": int.from_bytes(payload[18:20], "big"),
        "minor": int.from_bytes(payload[20:22], "big"),
        "tx_power": int.from_bytes(payload[22:23], "big", signed=True),
    }


def ibeacon_from_adv(adv: Any) -> dict | None:
    """Return the iBeacon fields from *adv*, or None if it is not an iBeacon."""
    payload = (adv.manufacturer_data or {}).get(APPLE_COMPANY_ID)
    return parse_ibeacon(bytes(payload)) if payload else None


def _expand_url_byte(byte: int) -> str:
    return _URL_EXPANSIONS.get(byte, chr(byte) if 0x20 <= byte < 0x7F else "")


def _decode_eddystone_url(body: bytes) -> str:
    scheme = _URL_SCHEMES.get(body[0], "") if body else ""
    return scheme + "".join(_expand_url_byte(b) for b in body[1:])


def eddystone_from_adv(adv: Any) -> dict | None:
    """Return the Eddystone frame from *adv* service data, or None."""
    for uuid, data in (adv.service_data or {}).items():
        if _short_of(uuid) != EDDYSTONE_UUID_16 or not data:
            continue
        data = bytes(data)
        frame = {"type": _EDDYSTONE_FRAMES.get(data[0], f"Eddystone-0x{data[0]:02x}")}
        if data[0] == 0x10 and len(data) > 2:
            frame["url"] = _decode_eddystone_url(data[2:])
        return frame
    return None


def beacon_label(adv: Any) -> str | None:
    """A short beacon label for *adv* (e.g. "iBeacon", "Eddystone-URL"), or None."""
    if ibeacon_from_adv(adv) is not None:
        return "iBeacon"
    eddystone = eddystone_from_adv(adv)
    return eddystone["type"] if eddystone else None


def vendor_label(adv: Any) -> str | None:
    """The first recognised vendor name in *adv* manufacturer data, or None."""
    for company_id in adv.manufacturer_data or {}:
        name = company_name(company_id)
        if name:
            return name
    return None


def identify(adv: Any) -> str:
    """A short "what is this" label for *adv*: vendor and/or beacon, or "".

    Examples: "Apple · iBeacon", "Samsung Electronics", "Eddystone-URL".
    """
    parts = [p for p in (vendor_label(adv), beacon_label(adv)) if p]
    return " · ".join(dict.fromkeys(parts))


def decode_manufacturer(adv: Any) -> str:
    """Render manufacturer data for display, naming the vendor where known.

    "Apple (0x004C): <hex>" when the company is in the table, otherwise
    "0x004C: <hex>". Empty string when there is no manufacturer data.
    """
    parts = []
    for company_id, data in (adv.manufacturer_data or {}).items():
        name = company_name(company_id)
        prefix = f"{name} (0x{company_id:04X})" if name else f"0x{company_id:04X}"
        parts.append(f"{prefix}: {fmt_bytes(data)}")
    return "; ".join(parts)
