"""Hardware-free fakes mirroring the Bleak interfaces this project uses.

Every fake carries the same attribute names Bleak uses, so production code
cannot tell the difference. Names and shapes are asserted by
``tests/test_harness.py``.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from bleak import normalize_uuid_str

# The scripts live in the repository root, not in ``tests/``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Normalised once at import so they are not recomputed in default arguments.
_BATTERY_LEVEL_UUID = normalize_uuid_str("2a19")
_BATTERY_SERVICE_UUID = normalize_uuid_str("180f")


class FakeDescriptor:
    def __init__(
        self,
        uuid,
        handle,
        characteristic_handle=1,
        characteristic_uuid=_BATTERY_LEVEL_UUID,
    ):
        self.uuid = normalize_uuid_str(uuid)
        self.handle = handle
        self.characteristic_handle = characteristic_handle
        self.characteristic_uuid = normalize_uuid_str(characteristic_uuid)
        self.description = f"Descriptor {self.uuid}"

    def __repr__(self):
        return f"FakeDescriptor({self.uuid!r}, {self.handle})"


class FakeCharacteristic:
    def __init__(
        self,
        uuid,
        handle,
        properties=(),
        descriptors=(),
        service_uuid=_BATTERY_SERVICE_UUID,
        service_handle=1,
        max_write_without_response_size=20,
    ):
        self.uuid = normalize_uuid_str(uuid)
        self.handle = handle
        self.properties = list(properties)
        self.description = f"Characteristic {self.uuid}"
        self.service_uuid = normalize_uuid_str(service_uuid)
        self.service_handle = service_handle
        self.descriptors = list(descriptors)
        self.max_write_without_response_size = max_write_without_response_size

    def __repr__(self):
        return f"FakeCharacteristic({self.uuid!r}, {self.handle})"


class FakeService:
    def __init__(self, uuid, handle, characteristics=()):
        self.uuid = normalize_uuid_str(uuid)
        self.handle = handle
        self.characteristics = list(characteristics)

    def __repr__(self):
        return f"FakeService({self.uuid!r}, {self.handle})"


class FakeServiceCollection:
    """Mimics ``BleakGATTServiceCollection`` resolution semantics."""

    def __init__(self, services=()):
        self._services = list(services)

    @property
    def services(self):
        return {s.handle: s for s in self._services}

    @property
    def characteristics(self):
        return {c.handle: c for s in self._services for c in s.characteristics}

    @property
    def descriptors(self):
        return {
            d.handle: d for s in self._services for c in s.characteristics for d in c.descriptors
        }

    def __iter__(self):
        return iter(self._services)

    def get_characteristic(self, specifier):
        if isinstance(specifier, int):
            return self.characteristics.get(specifier)
        uuid = normalize_uuid_str(str(specifier))
        for char in self.characteristics.values():
            if char.uuid == uuid:
                return char
        return None

    def get_descriptor(self, handle):
        return self.descriptors.get(handle)


class FakeClient:
    """Records every GATT call in ``calls`` for assertions."""

    def __init__(self, services, mtu_size=185):
        self.services = FakeServiceCollection(services)
        self.mtu_size = mtu_size
        self.is_connected = True
        self.calls = []
        self.responses = {}
        self.notifications = {}

    async def read_gatt_char(self, char, **kwargs):
        self.calls.append(("read_gatt_char", char, None, None))
        return self.responses.get(("char", char.handle), b"\x01")

    async def write_gatt_char(self, char, data, response, **kwargs):
        self.calls.append(("write_gatt_char", char, bytes(data), response))

    async def read_gatt_descriptor(self, desc, **kwargs):
        self.calls.append(("read_gatt_descriptor", desc, None, None))
        return self.responses.get(("desc", desc.handle), b"\x00\x00")

    async def write_gatt_descriptor(self, desc, data, **kwargs):
        self.calls.append(("write_gatt_descriptor", desc, bytes(data), None))

    async def start_notify(self, char, callback, **kwargs):
        self.calls.append(("start_notify", char, None, None))
        self.notifications[char.handle] = callback

    async def stop_notify(self, char, **kwargs):
        self.calls.append(("stop_notify", char, None, None))
        self.notifications.pop(char.handle, None)

    async def disconnect(self, **kwargs):
        self.calls.append(("disconnect", None, None, None))


class FakeAdvertisementData:
    def __init__(
        self,
        local_name=None,
        manufacturer_data=None,
        service_data=None,
        service_uuids=None,
        tx_power=None,
        rssi=-55,
    ):
        self.local_name = local_name
        self.manufacturer_data = manufacturer_data or {}
        self.service_data = service_data or {}
        self.service_uuids = service_uuids or []
        self.tx_power = tx_power
        self.rssi = rssi
        self.platform_data = ()


class FakeDevice:
    def __init__(self, address="AA:BB:CC:DD:EE:FF", name="FakeDevice"):
        self.address = address
        self.name = name
        self.details = {}


@pytest.fixture
def gatt_env():
    """A connected client exposing a Battery service, as most real peripherals do."""
    config_desc = FakeDescriptor(
        normalize_uuid_str("2902"), handle=0x0010, characteristic_handle=0x0020
    )
    battery_char = FakeCharacteristic(
        normalize_uuid_str("2a19"),
        handle=0x0020,
        properties=["read", "notify"],
        descriptors=[config_desc],
        service_uuid=normalize_uuid_str("180f"),
        service_handle=0x0001,
        max_write_without_response_size=20,
    )
    writable_char = FakeCharacteristic(
        normalize_uuid_str("2a3d"),
        handle=0x0030,
        properties=["read", "write", "write-without-response"],
        service_uuid=normalize_uuid_str("181d"),
        service_handle=0x0002,
        max_write_without_response_size=20,
    )
    client = FakeClient(
        [
            FakeService(normalize_uuid_str("180f"), 0x0001, [battery_char]),
            FakeService(normalize_uuid_str("181d"), 0x0002, [writable_char]),
        ],
        mtu_size=185,
    )
    return SimpleNamespace(
        client=client,
        battery_char=battery_char,
        writable_char=writable_char,
        config_desc=config_desc,
        mtu_size=185,
    )
