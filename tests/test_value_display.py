"""Tests for how a characteristic value is rendered as hex plus honest extras.

A read value is shown as a hex dump with interpretation lines beneath it. This
pins the behaviour that was wrong before:

* a binary value no longer decodes to a misleading scrap of text (``00 64 00``
  used to print an invisible-NUL "d");
* a value that is not text gets an honest ``Int:``/``Data:`` line instead of
  silently showing nothing; and
* readable ASCII embedded in an otherwise binary value is surfaced in an
  ``ASCII:`` gutter, so a firmware/model string buried in a binary field (for
  example ``00 00 41 01 33 33 34 00 00`` -> ``..A.334..``) is not lost.
"""

import re

from wamble.common import ascii_gutter, console, decode_bytes, describe_value, show_value

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# A real 32-byte binary value (a token/hash) that is not valid UTF-8.
BINARY32 = bytes.fromhex("77c2695a7bcf0a2d79dd0754438e3a6b7d7cc57f1934c7052469cc04510fdd7f")

# The "Firmware Revision String" value from the field report: mostly framing
# bytes with the text "A334" buried in the middle.
EMBEDDED_TEXT = bytes.fromhex("000041013333340000")


class TestDecodeBytes:
    def test_plain_text(self):
        assert decode_bytes(b"hello") == "hello"

    def test_trailing_nuls_stripped(self):
        assert decode_bytes(b"hello\x00\x00") == "hello"

    def test_whitespace_is_allowed(self):
        assert decode_bytes(b"line1\nline2\t!") == "line1\nline2\t!"

    def test_interior_nul_is_binary_not_text(self):
        # 00 64 00: the old behaviour decoded this to an invisible-NUL "d".
        assert decode_bytes(b"\x00\x64\x00") == ""

    def test_control_bytes_are_binary(self):
        assert decode_bytes(b"\x01\x02\x03") == ""

    def test_invalid_utf8_is_binary(self):
        assert decode_bytes(BINARY32) == ""

    def test_embedded_text_is_not_whole_text(self):
        # Part text, part binary is not a clean string, so decode_bytes declines.
        assert decode_bytes(EMBEDDED_TEXT) == ""

    def test_empty_and_none(self):
        assert decode_bytes(b"") == ""
        assert decode_bytes(None) == ""


class TestDescribeValue:
    def test_empty_has_no_description(self):
        assert describe_value(b"") is None
        assert describe_value(None) is None

    def test_single_byte_is_an_integer(self):
        assert describe_value(b"\x64") == "100 (uint8, little-endian)"

    def test_two_bytes_little_endian(self):
        assert describe_value(b"\x00\x64") == "25600 (uint16, little-endian)"

    def test_odd_width_is_a_byte_count(self):
        assert describe_value(b"\x00\x64\x00") == "binary data, 3 bytes"

    def test_long_value_is_a_byte_count(self):
        assert describe_value(BINARY32) == "binary data, 32 bytes"


class TestAsciiGutter:
    def test_surfaces_embedded_text(self):
        assert ascii_gutter(EMBEDDED_TEXT) == "..A.334.."

    def test_non_printable_bytes_become_dots(self):
        assert ascii_gutter(b"\x00\x01ab\x7f") == "..ab."

    def test_none_when_nothing_printable(self):
        # A pure-binary value (no ASCII) gets no gutter: it would be all dots.
        assert ascii_gutter(b"\x00\x01\x02") is None
        assert ascii_gutter(b"\x05") is None

    def test_space_is_printable(self):
        assert ascii_gutter(b"a b") == "a b"

    def test_empty_and_none(self):
        assert ascii_gutter(b"") is None
        assert ascii_gutter(None) is None


def _render(data) -> str:
    # rich auto-highlights numbers, so strip the ANSI styling before matching.
    with console.capture() as cap:
        show_value(data)
    return _ANSI.sub("", cap.get())


def _has(out: str, label: str, value: str) -> bool:
    # Match a labelled line regardless of the exact padding between the two.
    return re.search(rf"{re.escape(label)}\s+{re.escape(value)}", out) is not None


class TestShowValue:
    def test_text_value_gets_a_text_line_only(self):
        out = _render(b"hi")
        assert _has(out, "Hex:", "68 69")
        assert _has(out, "Text:", "hi")
        assert "Data:" not in out and "Int:" not in out and "ASCII:" not in out

    def test_binary_value_is_explained_and_has_no_text_line(self):
        out = _render(BINARY32)
        assert "Hex:" in out
        assert _has(out, "Data:", "binary data, 32 bytes")
        assert "Text:" not in out

    def test_embedded_text_is_surfaced_in_ascii_gutter(self):
        # The crux: the "firmware" value is not clean text, but the buried "334"
        # must still be visible rather than hidden behind "binary data".
        out = _render(EMBEDDED_TEXT)
        assert _has(out, "Data:", "binary data, 9 bytes")
        assert _has(out, "ASCII:", "..A.334..")
        assert "Text:" not in out

    def test_scalar_value_shows_integer_without_a_gutter(self):
        # 0x05 is a non-printable byte (e.g. a battery level of 5): an integer,
        # and no ASCII gutter because it has no printable bytes.
        out = _render(b"\x05")
        assert _has(out, "Int:", "5 (uint8, little-endian)")
        assert "Text:" not in out and "ASCII:" not in out

    def test_empty_value_has_only_a_hex_line(self):
        out = _render(b"")
        assert "(empty)" in out
        for label in ("Text:", "Data:", "Int:", "ASCII:"):
            assert label not in out
