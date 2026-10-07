"""Tests for the saved device-target profiles in wamble.common.

The resolution (@alias -> identifier) and the load/save round-trip are what let
every connecting tool accept a short target name, so they are unit-tested
without a Bluetooth adapter. Each test points at a temporary file via the
functions' explicit path argument, so a developer's real profiles are untouched.
"""

import json
import os
from pathlib import Path

from wamble.common import load_targets, resolve_target, save_targets, targets_path


class TestTargetsPath:
    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("WAMBLE_TARGETS", "/tmp/custom-targets.json")
        assert targets_path() == Path("/tmp/custom-targets.json")

    def test_default_location_is_under_config(self, monkeypatch):
        monkeypatch.delenv("WAMBLE_TARGETS", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", "/home/user/.config")
        if os.name != "nt":
            assert targets_path() == Path("/home/user/.config/wamble/targets.json")


class TestLoadSaveRoundTrip:
    def test_save_then_load_returns_same_map(self, tmp_path):
        p = tmp_path / "targets.json"
        targets = {"tv": "[TV] Samsung", "led": "GBK_H619A"}
        save_targets(targets, p)
        assert load_targets(p) == targets

    def test_save_creates_parent_directory(self, tmp_path):
        p = tmp_path / "nested" / "dir" / "targets.json"
        save_targets({"a": "b"}, p)
        assert p.exists()
        assert load_targets(p) == {"a": "b"}

    def test_missing_file_is_empty_map(self, tmp_path):
        assert load_targets(tmp_path / "does-not-exist.json") == {}

    def test_invalid_json_is_empty_map(self, tmp_path):
        p = tmp_path / "targets.json"
        p.write_text("{not valid json")
        assert load_targets(p) == {}

    def test_non_object_json_is_empty_map(self, tmp_path):
        p = tmp_path / "targets.json"
        p.write_text("[1, 2, 3]")
        assert load_targets(p) == {}

    def test_non_string_values_are_dropped(self, tmp_path):
        p = tmp_path / "targets.json"
        p.write_text(json.dumps({"good": "name", "bad": 123, "also_bad": None}))
        assert load_targets(p) == {"good": "name"}


class TestResolveTarget:
    def test_plain_identifier_passes_through(self, tmp_path):
        assert resolve_target("Living Room", tmp_path / "t.json") == "Living Room"

    def test_known_alias_resolves(self, tmp_path):
        p = tmp_path / "t.json"
        save_targets({"tv": "[TV] Samsung"}, p)
        assert resolve_target("@tv", p) == "[TV] Samsung"

    def test_unknown_alias_passes_through_unchanged(self, tmp_path):
        p = tmp_path / "t.json"
        save_targets({"tv": "[TV] Samsung"}, p)
        assert resolve_target("@missing", p) == "@missing"

    def test_address_like_identifier_is_untouched(self, tmp_path):
        addr = "AA:BB:CC:DD:EE:FF"
        assert resolve_target(addr, tmp_path / "t.json") == addr
