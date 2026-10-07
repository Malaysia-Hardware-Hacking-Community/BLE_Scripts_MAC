"""Tests for the pure logic in wamble.notify_log.

Subscribing needs a device, but the row shape and the text rendering are pure
and are what a saved log depends on, so they are pinned here without hardware.
"""

from types import SimpleNamespace

from wamble.notify_log import NOTIFY_LOG_FIELDS, as_text, notify_row


class TestAsText:
    def test_printable_utf8_is_returned(self):
        assert as_text(b"hello") == "hello"

    def test_non_text_bytes_return_empty(self):
        assert as_text(b"\x00\x01\x02") == ""

    def test_control_characters_are_not_printable(self):
        assert as_text(b"\x07\x08") == ""


class TestNotifyRow:
    def _sender(self, uuid="00002a37-0000-1000-8000-00805f9b34fb", handle=42):
        return SimpleNamespace(uuid=uuid, handle=handle)

    def test_row_has_exactly_the_declared_fields(self):
        row = notify_row("t", 1.0, self._sender(), b"\x01\x02")
        assert sorted(row) == sorted(NOTIFY_LOG_FIELDS)

    def test_hex_and_length_reflect_the_payload(self):
        row = notify_row("t", 1.0, self._sender(), b"\x48\x49")
        assert row["value_hex"] == "48 49"
        assert row["length"] == 2

    def test_characteristic_is_shortened(self):
        row = notify_row("t", 1.0, self._sender(), b"\x00")
        assert row["characteristic"] == "2a37"

    def test_text_column_decodes_text_payloads(self):
        row = notify_row("t", 1.0, self._sender(), b"OK")
        assert row["text"] == "OK"

    def test_elapsed_is_formatted_to_milliseconds(self):
        row = notify_row("2026-01-01T00:00:00+00:00", 2.5, self._sender(), b"\x00")
        assert row["elapsed"] == "2.500"
        assert row["timestamp"] == "2026-01-01T00:00:00+00:00"

    def test_handle_is_carried_through(self):
        row = notify_row("t", 0.0, self._sender(handle=7), b"\x00")
        assert row["handle"] == 7


class TestSelectCharacteristics:
    def test_no_specs_returns_notifiable_characteristics(self, gatt_env):
        from wamble.notify_log import select_characteristics

        chosen = select_characteristics(gatt_env.client, None)
        # Always a list (regression: property mode returns None, not []), and
        # every chosen characteristic can actually notify or indicate.
        assert isinstance(chosen, list)
        assert chosen
        assert all({"notify", "indicate"} & set(c.properties) for c in chosen)

    def test_unknown_spec_is_skipped(self, gatt_env):
        from wamble.notify_log import select_characteristics

        assert select_characteristics(gatt_env.client, ["ffffffff"]) == []
