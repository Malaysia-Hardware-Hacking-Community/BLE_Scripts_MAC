"""GATT operations that are more than a one-line Bleak call.

Kept separate from :mod:`ble_common` so the interactive front-ends
(``btgatt.py``, ``gatt_cli.py``) hold no GATT logic of their own and cannot
drift apart.

Import direction is one-way: this module imports from ``ble_common`` at module
level, and ``ble_common`` imports from here *inside function bodies* only.
"""

import re
from typing import Any

from ble_common import short_uuid

#: ATT MTU is the whole packet; a write carries a 3-byte ATT header.
ATT_MTU_OVERHEAD: int = 3

#: A specifier made only of decimal digits, or 0x-prefixed hex, is a handle.
_HANDLE_RE = re.compile(r"^(?:0[xX][0-9a-fA-F]+|[0-9]+)$")


def is_descriptor(target: Any) -> bool:
    """True when *target* is a descriptor rather than a characteristic.

    Duck-typed on ``characteristic_handle``: Bleak descriptors have it and
    characteristics do not, and this keeps working with test fakes.
    """
    return hasattr(target, "characteristic_handle")


def target_label(target: Any) -> str:
    """Human-readable identity for a characteristic or descriptor."""
    kind = "Descriptor" if is_descriptor(target) else "Characteristic"
    return f"{kind} {short_uuid(target.uuid)} (handle {target.handle})"


def as_handle(text: str) -> int | None:
    """Parse *text* as a handle, or return None if it is not handle-shaped."""
    if not _HANDLE_RE.match(text):
        return None
    return int(text, 16) if text[:2].lower() == "0x" else int(text, 10)


def _uuid_matches(needle: str, uuid_value: str) -> bool:
    """True when *needle* identifies *uuid_value*, in either UUID form.

    CoreBluetooth reports SIG UUIDs in their full 128-bit form, while users
    habitually type the 16-bit short form, and ``btgatt`` users often paste the
    full form. Comparing the raw text alone makes that asymmetric: a 16-bit
    needle matches a 128-bit UUID but not the reverse. So also compare the
    16-bit normalisations, which makes the two forms interchangeable while
    still allowing a plain substring such as ``2a1`` to match ``2a19``.

    A ``0x`` prefix is compared with and without it, since that is how
    ``gatttool`` users habitually write a UUID and ``normalize_uuid_str``
    rejects the prefixed form outright.
    """
    target = str(uuid_value).strip().casefold()
    needle = needle.casefold()
    bare = needle.removeprefix("0x")
    if needle in target or (bare and bare in target):
        return True
    return short_uuid(needle).casefold() in short_uuid(target).casefold()


def resolve_target(client, specifier: str | int) -> Any | None:
    """Find a characteristic or descriptor by handle or UUID.

    Resolution order:

    1. A specifier of only decimal digits, or ``0x``-prefixed hex, is a
       **handle**. Characteristics are searched before descriptors, so a
       collision resolves in favour of the characteristic. If no handle
       matches, resolution falls through to UUID matching so a numeric UUID
       fragment still works.
    2. Otherwise the specifier is a case-insensitive substring of the
       attribute's own ``uuid``. A parent service UUID never matches, because
       searching by service is what ``search-service`` is for.

    Returns ``None`` when nothing matches.
    """
    text = str(specifier).strip()
    if not text:
        return None

    handle = as_handle(text)
    if handle is not None:
        char = client.services.get_characteristic(handle)
        if char is not None:
            return char
        desc = client.services.get_descriptor(handle)
        if desc is not None:
            return desc
        # Handle-shaped but no handle matched. Only fall through to UUID
        # matching when the token is long enough to be a real 16-bit UUID
        # (>=4 hex digits); otherwise a bare handle like "8" would spuriously
        # match a digit inside a 128-bit UUID (e.g. the "8" in ...0809...).
        bare = text[2:] if text[:2].lower() == "0x" else text
        if len(bare) < 4:
            return None

    for service in client.services:
        for char in service.characteristics:
            if _uuid_matches(text, char.uuid):
                return char

    for service in client.services:
        for char in service.characteristics:
            for desc in char.descriptors:
                if _uuid_matches(text, desc.uuid):
                    return desc

    return None


def chunk_payload(data: bytes, size: int) -> list[bytes]:
    """Split *data* into consecutive chunks of at most *size* bytes.

    Returns ``[]`` for an empty payload and ``[data]`` when it already fits.
    Raises ``ValueError`` when *size* is less than 1, which would otherwise
    loop forever.
    """
    if size < 1:
        raise ValueError(f"chunk size must be >= 1, got {size}")
    payload = bytes(data)
    return [payload[i : i + size] for i in range(0, len(payload), size)]


def write_chunk_size(client, char: Any, *, response: bool) -> int:
    """Largest payload one write to *char* can carry.

    Write-without-response is bounded by the negotiated GATT limit, which
    Bleak exposes as ``max_write_without_response_size``. That value can be
    stale (it reports 20 until the peripheral has answered) and is always 20 on
    BlueZ older than 5.62, so callers can override it.

    Write-with-response is bounded by the ATT MTU less its 3-byte header.
    """
    if response:
        return max(1, int(client.mtu_size) - ATT_MTU_OVERHEAD)
    return max(1, int(char.max_write_without_response_size))


async def write_long(
    client,
    char: Any,
    data: bytes,
    *,
    response: bool,
    chunk_size: int | None = None,
) -> int:
    """Write a payload larger than one ATT packet, in order. Returns bytes written.

    Raises:
        ValueError: if *char* is a descriptor. Descriptors have no
            write-without-response mode and long descriptor writes require the
            prepare/execute procedure, which CoreBluetooth does not expose.
    """
    if is_descriptor(char):
        raise ValueError(
            "Long writes are not supported for descriptors: they have no "
            "write-without-response mode, and long descriptor writes need "
            "prepare/execute, which CoreBluetooth does not expose."
        )

    payload = bytes(data)
    if not payload:
        return 0

    if chunk_size is None:
        chunk_size = write_chunk_size(client, char, response=response)

    written = 0
    for chunk in chunk_payload(payload, chunk_size):
        await client.write_gatt_char(char, chunk, response=response)
        written += len(chunk)
    return written


async def read_target(client, target: Any) -> bytes:
    """Read a characteristic or descriptor, whichever *target* is."""
    if is_descriptor(target):
        return await client.read_gatt_descriptor(target)
    return await client.read_gatt_char(target)


async def write_target(client, target: Any, data: bytes, *, response: bool = True) -> None:
    """Write to a characteristic or descriptor, whichever *target* is.

    Descriptors have no response mode, so *response* is ignored for them.
    """
    payload = bytes(data)
    if is_descriptor(target):
        await client.write_gatt_descriptor(target, payload)
        return
    await client.write_gatt_char(target, payload, response=response)
