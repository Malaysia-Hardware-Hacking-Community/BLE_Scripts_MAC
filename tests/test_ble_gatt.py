import pytest

from ble_gatt import (
    as_handle,
    chunk_payload,
    is_descriptor,
    read_target,
    resolve_target,
    target_label,
    write_chunk_size,
    write_long,
    write_target,
)


class TestIsDescriptor:
    def test_descriptor_is_detected(self, gatt_env):
        assert is_descriptor(gatt_env.config_desc) is True

    def test_characteristic_is_not_a_descriptor(self, gatt_env):
        assert is_descriptor(gatt_env.battery_char) is False


class TestTargetLabel:
    def test_labels_a_characteristic_with_short_uuid(self, gatt_env):
        assert target_label(gatt_env.battery_char) == "Characteristic 2a19 (handle 32)"

    def test_labels_a_descriptor(self, gatt_env):
        assert target_label(gatt_env.config_desc) == "Descriptor 2902 (handle 16)"


class TestAsHandle:
    def test_parses_decimal_and_hex_handles(self):
        assert as_handle("32") == 32
        assert as_handle("0x20") == 32
        assert as_handle("0X20") == 32
        assert as_handle("0020") == 20

    def test_rejects_anything_that_is_not_handle_shaped(self):
        for text in ("", " ", "0x", "-1", "1.5", "+32", "2a19", "180f"):
            assert as_handle(text) is None, text


class TestResolveTargetByHandle:
    def test_resolves_characteristic_by_decimal_handle(self, gatt_env):
        assert resolve_target(gatt_env.client, "32") is gatt_env.battery_char

    def test_resolves_characteristic_by_hex_handle(self, gatt_env):
        assert resolve_target(gatt_env.client, "0x0020") is gatt_env.battery_char

    def test_resolves_descriptor_by_handle(self, gatt_env):
        assert resolve_target(gatt_env.client, "16") is gatt_env.config_desc

    def test_characteristic_wins_when_handle_is_ambiguous(self, gatt_env):
        gatt_env.client.services.get_characteristic = lambda spec: (
            gatt_env.battery_char if spec == 0x0020 else None
        )
        gatt_env.config_desc.handle = 0x0020
        assert resolve_target(gatt_env.client, "32") is gatt_env.battery_char

    def test_a_non_handle_specifier_is_matched_as_a_uuid_fragment(self, gatt_env):
        # "2a19" is not a handle, but it is a UUID fragment.
        assert resolve_target(gatt_env.client, "2a19") is gatt_env.battery_char


class TestResolveTargetByUuid:
    def test_full_128_bit_uuid_matches(self, gatt_env):
        # The characteristic's OWN UUID, expanded to 128 bits. Note this is
        # deliberately not the Battery Service UUID: a parent's UUID must never
        # match one of its children (see the next-but-one test).
        assert (
            resolve_target(gatt_env.client, "00002a19-0000-1000-8000-00805f9b34fb")
            is gatt_env.battery_char
        )

    def test_full_128_bit_service_uuid_does_not_match_its_characteristic(self, gatt_env):
        # The parent service UUID, expanded to 128 bits, must resolve to nothing.
        assert resolve_target(gatt_env.client, "0000180f-0000-1000-8000-00805f9b34fb") is None

    def test_match_is_case_insensitive(self, gatt_env):
        assert resolve_target(gatt_env.client, "2A19") is gatt_env.battery_char

    def test_service_uuid_does_not_match_a_characteristic(self, gatt_env):
        # "181d" is a service UUID. resolve_target must not return that service's
        # characteristics just because the service UUID contains the fragment.
        assert resolve_target(gatt_env.client, "181d") is None

    def test_descriptor_uuid_fragment_matches_descriptor(self, gatt_env):
        assert resolve_target(gatt_env.client, "2902") is gatt_env.config_desc

    def test_unknown_specifier_returns_none(self, gatt_env):
        assert resolve_target(gatt_env.client, "zzzz") is None

    def test_integer_specifier_is_accepted(self, gatt_env):
        assert resolve_target(gatt_env.client, 32) is gatt_env.battery_char

    def test_characteristic_match_precedes_descriptor_match(self, gatt_env):
        # "1000" occurs in the 128-bit form of both the characteristic and its
        # descriptor, so only the documented scan order can pick the former.
        assert resolve_target(gatt_env.client, "1000") is gatt_env.battery_char

    def test_hex_prefixed_uuid_matches_the_characteristic(self, gatt_env):
        assert resolve_target(gatt_env.client, "0x2a19") is gatt_env.battery_char
        assert resolve_target(gatt_env.client, "0X2A19") is gatt_env.battery_char

    def test_hex_prefixed_uuid_matches_the_descriptor(self, gatt_env):
        assert resolve_target(gatt_env.client, "0x2902") is gatt_env.config_desc

    def test_hex_prefixed_service_uuid_still_matches_nothing(self, gatt_env):
        # Stripping the "0x" must not turn a parent into a match for its child.
        assert resolve_target(gatt_env.client, "0x180f") is None

    def test_a_lone_hex_prefix_matches_nothing(self, gatt_env):
        # Stripping the "0x" would leave nothing to search for.
        assert resolve_target(gatt_env.client, "0x") is None

    def test_an_empty_specifier_matches_nothing(self, gatt_env):
        assert resolve_target(gatt_env.client, "") is None

    def test_a_whitespace_specifier_matches_nothing(self, gatt_env):
        assert resolve_target(gatt_env.client, "   ") is None


class TestUuidFormSymmetry:
    """A UUID typed in either form must match the other.

    CoreBluetooth reports SIG UUIDs as full 128-bit strings, while users type
    16-bit short forms and paste 128-bit ones. Matching has to work in both
    directions or the REPL looks broken on exactly one of those habits.
    """

    def test_short_needle_matches_a_128_bit_uuid(self, gatt_env):
        gatt_env.battery_char.uuid = "00002a19-0000-1000-8000-00805f9b34fb"
        assert resolve_target(gatt_env.client, "2a19") is gatt_env.battery_char

    def test_128_bit_needle_matches_a_genuinely_short_uuid(self, gatt_env):
        # Assigned after construction, so it bypasses the fake's normalisation:
        # without the 16-bit normalisation line this is the only test in the
        # file that would notice its removal.
        gatt_env.battery_char.uuid = "2a19"
        assert (
            resolve_target(gatt_env.client, "00002a19-0000-1000-8000-00805f9b34fb")
            is gatt_env.battery_char
        )

    def test_mixed_case_uuid_matches_either_way_round(self, gatt_env):
        # Deliberately not a SIG base UUID, so short_uuid() cannot fold the case
        # for us and the explicit casefolding is the only thing carrying it.
        lower = "abcd1234-1234-1234-1234-1234567890ab"
        upper = "ABCD1234-1234-1234-1234-1234567890AB"
        gatt_env.battery_char.uuid = upper
        assert resolve_target(gatt_env.client, lower) is gatt_env.battery_char
        gatt_env.battery_char.uuid = lower
        assert resolve_target(gatt_env.client, upper) is gatt_env.battery_char

    def test_both_forms_are_case_insensitive(self, gatt_env):
        gatt_env.battery_char.uuid = "00002A19-0000-1000-8000-00805F9B34FB"
        assert resolve_target(gatt_env.client, "2A19") is gatt_env.battery_char

    def test_a_partial_fragment_still_matches(self, gatt_env):
        # Substring matching must survive the normalisation: "2a1" is not a
        # valid UUID and so passes through unchanged.
        assert resolve_target(gatt_env.client, "2a1") is gatt_env.battery_char

    def test_a_partial_fragment_of_a_128_bit_uuid_still_matches(self, gatt_env):
        gatt_env.battery_char.uuid = "0000abcd-0000-1000-8000-00805f9b34fb"
        assert resolve_target(gatt_env.client, "abcd-0000") is gatt_env.battery_char

    def test_128_bit_needle_matches_a_128_bit_descriptor(self, gatt_env):
        assert (
            resolve_target(gatt_env.client, "00002902-0000-1000-8000-00805f9b34fb")
            is gatt_env.config_desc
        )


class TestBleCommonDelegates:
    def test_find_characteristic_resolves_by_handle(self, gatt_env):
        from ble_common import find_characteristic

        assert find_characteristic(gatt_env.client, "32") is gatt_env.battery_char

    def test_find_characteristic_rejects_a_descriptor_handle(self, gatt_env):
        from ble_common import find_characteristic

        assert find_characteristic(gatt_env.client, "16") is None

    def test_find_descriptor_resolves_by_handle(self, gatt_env):
        from ble_common import find_descriptor

        found = find_descriptor(gatt_env.battery_char, "16")
        assert found is gatt_env.config_desc

    def test_find_descriptor_resolves_by_hex_handle(self, gatt_env):
        from ble_common import find_descriptor

        found = find_descriptor(gatt_env.battery_char, "0x10")
        assert found is gatt_env.config_desc

    def test_find_descriptor_defaults_to_first(self, gatt_env):
        from ble_common import find_descriptor

        assert find_descriptor(gatt_env.battery_char) is gatt_env.config_desc

    def test_find_characteristic_by_property_still_returns_a_list(self, gatt_env):
        from ble_common import find_characteristic

        found = find_characteristic(gatt_env.client, "write", by="property")
        assert [c.handle for c in found] == [0x0030]


class TestChunkPayload:
    def test_empty_payload_yields_no_chunks(self):
        assert chunk_payload(b"", 4) == []

    def test_payload_smaller_than_chunk_is_one_chunk(self):
        assert chunk_payload(b"abc", 8) == [b"abc"]

    def test_payload_splits_evenly(self):
        assert chunk_payload(b"abcdefgh", 4) == [b"abcd", b"efgh"]

    def test_final_chunk_is_the_remainder(self):
        assert chunk_payload(b"abcdefg", 4) == [b"abcd", b"efg"]

    def test_payload_exactly_one_chunk(self):
        assert chunk_payload(b"abcd", 4) == [b"abcd"]

    def test_bytearray_input_is_accepted(self):
        assert chunk_payload(bytearray(b"ab"), 4) == [b"ab"]

    def test_zero_chunk_size_is_rejected(self):
        with pytest.raises(ValueError):
            chunk_payload(b"abc", 0)

    def test_negative_chunk_size_is_rejected(self):
        with pytest.raises(ValueError):
            chunk_payload(b"abc", -1)


class TestWriteChunkSize:
    def test_write_without_response_uses_max_write_without_response_size(self, gatt_env):
        gatt_env.battery_char.max_write_without_response_size = 512
        assert write_chunk_size(gatt_env.client, gatt_env.battery_char, response=False) == 512

    def test_write_with_response_subtracts_att_overhead(self, gatt_env):
        gatt_env.client.mtu_size = 185
        assert write_chunk_size(gatt_env.client, gatt_env.battery_char, response=True) == 182

    def test_tiny_mtu_never_yields_a_non_positive_size(self, gatt_env):
        gatt_env.client.mtu_size = 3
        assert write_chunk_size(gatt_env.client, gatt_env.battery_char, response=True) == 1


class TestWriteLong:
    async def test_chunks_on_the_max_write_size(self, gatt_env):
        gatt_env.battery_char.max_write_without_response_size = 4
        payload = b"0123456789"
        written = await write_long(gatt_env.client, gatt_env.battery_char, payload, response=False)
        assert written == 10
        writes = [c for c in gatt_env.client.calls if c[0] == "write_gatt_char"]
        assert [c[2] for c in writes] == [b"0123", b"4567", b"89"]
        assert all(c[3] is False for c in writes)

    async def test_explicit_chunk_size_overrides_the_property(self, gatt_env):
        gatt_env.battery_char.max_write_without_response_size = 512
        written = await write_long(
            gatt_env.client, gatt_env.battery_char, b"0123456789", response=False, chunk_size=3
        )
        assert written == 10
        writes = [c for c in gatt_env.client.calls if c[0] == "write_gatt_char"]
        assert [c[2] for c in writes] == [b"012", b"345", b"678", b"9"]

    async def test_write_with_response_is_chunked_to_the_mtu(self, gatt_env):
        gatt_env.client.mtu_size = 8
        written = await write_long(
            gatt_env.client, gatt_env.battery_char, b"0123456789", response=True
        )
        assert written == 10
        writes = [c for c in gatt_env.client.calls if c[0] == "write_gatt_char"]
        assert [len(c[2]) for c in writes] == [5, 5]
        assert all(c[3] is True for c in writes)

    async def test_empty_payload_writes_nothing(self, gatt_env):
        written = await write_long(gatt_env.client, gatt_env.battery_char, b"", response=False)
        assert written == 0
        assert gatt_env.client.calls == []

    async def test_descriptor_target_is_rejected(self, gatt_env):
        with pytest.raises(ValueError, match="descriptor"):
            await write_long(gatt_env.client, gatt_env.config_desc, b"abc", response=False)


class TestReadAndWriteTarget:
    async def test_read_target_reads_a_characteristic(self, gatt_env):
        gatt_env.client.responses[("char", 0x0020)] = b"\x64"
        assert await read_target(gatt_env.client, gatt_env.battery_char) == b"\x64"

    async def test_read_target_reads_a_descriptor(self, gatt_env):
        assert await read_target(gatt_env.client, gatt_env.config_desc) == b"\x00\x00"

    async def test_write_target_writes_a_characteristic(self, gatt_env):
        await write_target(gatt_env.client, gatt_env.writable_char, b"\x01", response=False)
        assert gatt_env.client.calls[-1] == (
            "write_gatt_char",
            gatt_env.writable_char,
            b"\x01",
            False,
        )

    async def test_write_target_writes_a_descriptor_without_a_response_flag(self, gatt_env):
        await write_target(gatt_env.client, gatt_env.config_desc, b"\x01\x00")
        assert gatt_env.client.calls[-1] == (
            "write_gatt_descriptor",
            gatt_env.config_desc,
            b"\x01\x00",
            None,
        )
