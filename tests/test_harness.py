"""Proves the fakes in conftest match the interfaces Bleak actually exposes.

Every assertion below runs against both a fake from ``conftest`` and a real
Bleak object built from the same handles and UUIDs, so a fake that drifts
from Bleak fails here instead of misleading the tests that build on it.
"""

import inspect

import pytest
from bleak import normalize_uuid_str
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.client import BaseBleakClient
from bleak.backends.descriptor import BleakGATTDescriptor
from bleak.backends.service import (
    BleakGATTService,
    BleakGATTServiceCollection,
)
from conftest import (
    FakeCharacteristic,
    FakeClient,
    FakeDescriptor,
    FakeService,
    FakeServiceCollection,
)

DESCRIPTOR_ATTRS = (
    "uuid",
    "handle",
    "description",
    "characteristic_handle",
    "characteristic_uuid",
)
CHARACTERISTIC_ATTRS = (
    "uuid",
    "handle",
    "properties",
    "description",
    "service_uuid",
    "service_handle",
    "descriptors",
    "max_write_without_response_size",
)
SERVICE_ATTRS = ("uuid", "handle", "characteristics")
COLLECTION_ATTRS = (
    "services",
    "characteristics",
    "descriptors",
    "get_characteristic",
    "get_descriptor",
)


def _real_collection(fake_collection):
    """Build a ``BleakGATTServiceCollection`` mirroring a fake collection."""
    real = BleakGATTServiceCollection()
    for fake_service in fake_collection:
        real_service = BleakGATTService(None, fake_service.handle, fake_service.uuid)
        real.add_service(real_service)
        for fake_char in fake_service.characteristics:
            real_char = BleakGATTCharacteristic(
                None,
                fake_char.handle,
                fake_char.uuid,
                list(fake_char.properties),
                fake_char.max_write_without_response_size,
                real_service,
            )
            real.add_characteristic(real_char)
            for fake_desc in fake_char.descriptors:
                real.add_descriptor(
                    BleakGATTDescriptor(None, fake_desc.handle, fake_desc.uuid, real_char)
                )
    return real


def _real_objects():
    """Build a real service, characteristic and descriptor for shape checks."""
    service = BleakGATTService(None, 0x0001, normalize_uuid_str("180f"))
    characteristic = BleakGATTCharacteristic(
        None,
        0x0020,
        normalize_uuid_str("2a19"),
        ["read", "notify"],
        20,
        service,
    )
    service.add_characteristic(characteristic)
    descriptor = BleakGATTDescriptor(None, 0x0010, normalize_uuid_str("2902"), characteristic)
    characteristic.add_descriptor(descriptor)
    return service, characteristic, descriptor


def _resolution(collection, specifier):
    """Describe what a collection returned, including a raised ValueError."""
    try:
        char = collection.get_characteristic(specifier)
    except ValueError:
        return "ValueError"
    return None if char is None else char.handle


def test_fixture_uuids_are_normalized_128_bit_like_real_bleak(gatt_env):
    assert gatt_env.battery_char.uuid == normalize_uuid_str("2a19")
    assert gatt_env.writable_char.uuid == normalize_uuid_str("2a3d")
    assert gatt_env.config_desc.uuid == normalize_uuid_str("2902")
    assert gatt_env.battery_char.service_uuid == normalize_uuid_str("180f")
    assert [s.uuid for s in gatt_env.client.services] == [
        normalize_uuid_str("180f"),
        normalize_uuid_str("181d"),
    ]


def test_fake_descriptor_attributes_exist_on_both_real_and_fake(gatt_env):
    real_descriptor = _real_objects()[2]
    fake_descriptor = gatt_env.config_desc
    for attr in DESCRIPTOR_ATTRS:
        assert hasattr(real_descriptor, attr), f"Bleak descriptor is missing {attr}"
        assert hasattr(fake_descriptor, attr), f"FakeDescriptor is missing {attr}"


def test_fake_characteristic_attributes_exist_on_both_real_and_fake(gatt_env):
    real_characteristic = _real_objects()[1]
    fake_characteristic = gatt_env.battery_char
    for attr in CHARACTERISTIC_ATTRS:
        assert hasattr(real_characteristic, attr), f"Bleak characteristic is missing {attr}"
        assert hasattr(fake_characteristic, attr), f"FakeCharacteristic is missing {attr}"


def test_fake_service_attributes_exist_on_both_real_and_fake(gatt_env):
    real_service = _real_objects()[0]
    fake_service = next(iter(gatt_env.client.services))
    for attr in SERVICE_ATTRS:
        assert hasattr(real_service, attr), f"Bleak service is missing {attr}"
        assert hasattr(fake_service, attr), f"FakeService is missing {attr}"


def test_fake_collection_attributes_exist_on_both_real_and_fake(gatt_env):
    real_collection = _real_collection(gatt_env.client.services)
    fake_collection = gatt_env.client.services
    for attr in COLLECTION_ATTRS:
        assert hasattr(real_collection, attr), f"Bleak collection is missing {attr}"
        assert hasattr(fake_collection, attr), f"FakeServiceCollection is missing {attr}"


def test_is_descriptor_duck_typing_matches_real_bleak_shape(gatt_env):
    _, real_characteristic, real_descriptor = _real_objects()
    assert hasattr(real_descriptor, "characteristic_handle") is True
    assert hasattr(real_characteristic, "characteristic_handle") is False
    assert hasattr(gatt_env.config_desc, "characteristic_handle") is True
    assert hasattr(gatt_env.battery_char, "characteristic_handle") is False


def test_fake_collection_iterates_the_services_like_real_bleak(gatt_env):
    fake_collection = gatt_env.client.services
    real_collection = _real_collection(fake_collection)
    assert [s.handle for s in fake_collection] == [0x0001, 0x0002]
    assert [s.handle for s in fake_collection] == [s.handle for s in real_collection]
    assert [s.uuid for s in fake_collection] == [s.uuid for s in real_collection]


def test_fake_collection_mappings_are_keyed_by_handle_like_real_bleak(gatt_env):
    fake_collection = gatt_env.client.services
    real_collection = _real_collection(fake_collection)

    assert set(fake_collection.services) == {0x0001, 0x0002}
    assert set(fake_collection.services) == set(real_collection.services)
    assert set(fake_collection.characteristics) == {0x0020, 0x0030}
    assert {h: c.uuid for h, c in fake_collection.characteristics.items()} == {
        h: c.uuid for h, c in real_collection.characteristics.items()
    }
    assert set(fake_collection.descriptors) == {0x0010}
    assert {h: d.uuid for h, d in fake_collection.descriptors.items()} == {
        h: d.uuid for h, d in real_collection.descriptors.items()
    }


class TestGetCharacteristic:
    def test_resolves_an_integer_specifier_by_handle(self, gatt_env):
        collection = gatt_env.client.services
        assert collection.get_characteristic(0x0020) is gatt_env.battery_char
        assert collection.get_characteristic(0x9999) is None

    def test_resolves_a_uuid_string_by_exact_match(self, gatt_env):
        collection = gatt_env.client.services
        assert collection.get_characteristic("2a19") is gatt_env.battery_char
        assert collection.get_characteristic("2A19") is gatt_env.battery_char
        assert (
            collection.get_characteristic("00002a19-0000-1000-8000-00805f9b34fb")
            is gatt_env.battery_char
        )

    def test_returns_none_for_an_unknown_uuid(self, gatt_env):
        collection = gatt_env.client.services
        assert collection.get_characteristic("0000abcd-0000-1000-8000-00805f9b34fb") is None
        assert collection.get_characteristic(normalize_uuid_str("180f")) is None

    def test_raises_for_a_malformed_partial_uuid(self, gatt_env):
        collection = gatt_env.client.services
        with pytest.raises(ValueError):
            collection.get_characteristic("2a")
        with pytest.raises(ValueError):
            collection.get_characteristic("zzzz")

    @pytest.mark.parametrize(
        "specifier",
        [0x0020, 0x0030, "2a19", "2A19", "2a3d", "180f", "abcd", "2a", "zzzz"],
    )
    def test_fake_and_real_resolve_identically(self, gatt_env, specifier):
        fake_collection = gatt_env.client.services
        real_collection = _real_collection(fake_collection)
        assert _resolution(fake_collection, specifier) == _resolution(real_collection, specifier)


def test_fake_collection_resolves_descriptors_by_handle_like_real_bleak(gatt_env):
    fake_collection = gatt_env.client.services
    real_collection = _real_collection(fake_collection)

    fake_descriptor = fake_collection.get_descriptor(0x0010)
    real_descriptor = real_collection.get_descriptor(0x0010)

    assert fake_descriptor is gatt_env.config_desc
    assert fake_descriptor.uuid == real_descriptor.uuid
    assert fake_descriptor.characteristic_handle == real_descriptor.characteristic_handle == 0x0020
    assert fake_descriptor.characteristic_uuid == real_descriptor.characteristic_uuid
    assert fake_collection.get_descriptor(0x9999) is None
    assert real_collection.get_descriptor(0x9999) is None


def test_fake_collection_normalizes_short_uuid_arguments():
    descriptor = FakeDescriptor(
        "2902", 0x0010, characteristic_handle=0x0020, characteristic_uuid="2a19"
    )
    characteristic = FakeCharacteristic(
        "2a19",
        0x0020,
        properties=["read"],
        descriptors=[descriptor],
        service_uuid="180f",
        service_handle=0x0001,
    )
    service = FakeService("180f", 0x0001, [characteristic])
    collection = FakeServiceCollection([service])

    assert characteristic.uuid == normalize_uuid_str("2a19")
    assert characteristic.service_uuid == normalize_uuid_str("180f")
    assert descriptor.uuid == normalize_uuid_str("2902")
    assert descriptor.characteristic_uuid == characteristic.uuid
    assert collection.get_characteristic(0x0020) is characteristic
    assert collection.get_characteristic("2a19") is characteristic
    assert collection.get_characteristic("00002a19-0000-1000-8000-00805f9b34fb") is characteristic
    assert collection.get_descriptor(0x0010) is descriptor
    assert list(collection) == [service]


async def test_fake_client_records_read_gatt_char_and_returns_the_response(gatt_env):
    gatt_env.client.responses[("char", 0x0020)] = b"\x64"
    assert await gatt_env.client.read_gatt_char(gatt_env.battery_char) == b"\x64"
    assert gatt_env.client.calls == [("read_gatt_char", gatt_env.battery_char, None, None)]


async def test_fake_client_records_write_gatt_char_with_the_response_flag(gatt_env):
    client = gatt_env.client
    await client.write_gatt_char(gatt_env.writable_char, b"\x01", response=True)
    await client.write_gatt_char(gatt_env.writable_char, b"\x02", response=False)
    assert client.calls == [
        ("write_gatt_char", gatt_env.writable_char, b"\x01", True),
        ("write_gatt_char", gatt_env.writable_char, b"\x02", False),
    ]


async def test_fake_client_write_gatt_char_requires_the_response_flag(gatt_env):
    with pytest.raises(TypeError):
        await gatt_env.client.write_gatt_char(gatt_env.writable_char, b"\x01")
    assert gatt_env.client.calls == []


def test_write_gatt_char_response_is_required_in_fake_and_backend():
    fake_param = inspect.signature(FakeClient.write_gatt_char).parameters["response"]
    backend_param = inspect.signature(BaseBleakClient.write_gatt_char).parameters["response"]
    assert fake_param.default is inspect.Parameter.empty
    assert backend_param.default is inspect.Parameter.empty


async def test_fake_client_records_descriptor_and_notify_calls(gatt_env):
    client = gatt_env.client
    await client.read_gatt_descriptor(gatt_env.config_desc)
    await client.write_gatt_descriptor(gatt_env.config_desc, b"\x01\x00")

    def _on_notify(sender, data):
        pass

    await client.start_notify(gatt_env.battery_char, _on_notify)
    assert client.notifications[0x0020] is _on_notify
    await client.stop_notify(gatt_env.battery_char)

    assert client.calls == [
        ("read_gatt_descriptor", gatt_env.config_desc, None, None),
        ("write_gatt_descriptor", gatt_env.config_desc, b"\x01\x00", None),
        ("start_notify", gatt_env.battery_char, None, None),
        ("stop_notify", gatt_env.battery_char, None, None),
    ]
    assert 0x0020 not in client.notifications


def test_fake_client_starts_connected_with_no_recorded_calls(gatt_env):
    assert gatt_env.client.calls == []
    assert gatt_env.client.mtu_size == 185


async def test_async_tests_run_without_markers(gatt_env):
    assert gatt_env.client.is_connected is True
