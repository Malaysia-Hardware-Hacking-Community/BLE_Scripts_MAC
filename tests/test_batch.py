"""Tests for the script parsing in wamble.batch.

Running commands needs a device, but tokenising the script and parsing the
`wait` directive are pure and are what decides which commands run, so they are
pinned here.
"""

import pytest

from wamble.batch import iter_commands, parse_wait


class TestIterCommands:
    def test_splits_lines_into_token_lists(self):
        assert iter_commands("services\nread 2a19") == [["services"], ["read", "2a19"]]

    def test_blank_lines_and_comments_are_skipped(self):
        text = "services\n\n# a comment\nread 2a19   # inline comment\n"
        assert iter_commands(text) == [["services"], ["read", "2a19"]]

    def test_quotes_are_honoured(self):
        assert iter_commands('write-cmd 2a00 "01 02"') == [["write-cmd", "2a00", "01 02"]]

    def test_empty_script_is_no_commands(self):
        assert iter_commands("\n  \n# only a comment\n") == []


class TestParseWait:
    def test_parses_seconds(self):
        assert parse_wait(["wait", "2.5"]) == 2.5

    def test_rejects_missing_argument(self):
        with pytest.raises(ValueError, match="one argument"):
            parse_wait(["wait"])

    def test_rejects_extra_arguments(self):
        with pytest.raises(ValueError, match="one argument"):
            parse_wait(["wait", "1", "2"])

    def test_rejects_non_positive(self):
        with pytest.raises(ValueError, match="positive"):
            parse_wait(["wait", "0"])

    def test_rejects_non_numeric(self):
        with pytest.raises(ValueError):
            parse_wait(["wait", "soon"])
