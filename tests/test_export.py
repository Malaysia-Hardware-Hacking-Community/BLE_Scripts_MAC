"""Tests for the GATT-snapshot diff logic in wamble.export.

Connecting and building a snapshot needs a device, but comparing two snapshots
is pure dict work, which is where the value (and the risk of a subtle bug) is.
These pin the diff down without a Bluetooth adapter.
"""

import json

from wamble.export import diff_is_empty, diff_trees, load_tree


def _tree(*services):
    return {"device": {"name": "x", "address": "y"}, "services": list(services)}


def _svc(uuid, *chars):
    return {"uuid": uuid, "short": uuid, "name": "", "characteristics": list(chars)}


def _char(uuid, properties=("read",), descriptors=()):
    return {
        "uuid": uuid,
        "short": uuid,
        "name": "",
        "handle": 1,
        "properties": list(properties),
        "descriptors": [{"uuid": d, "short": d, "name": "", "handle": 2} for d in descriptors],
    }


BAT = "0000180f-0000-1000-8000-00805f9b34fb"
LVL = "00002a19-0000-1000-8000-00805f9b34fb"
GAP = "00001800-0000-1000-8000-00805f9b34fb"
NAME = "00002a00-0000-1000-8000-00805f9b34fb"
CCCD = "00002902-0000-1000-8000-00805f9b34fb"


class TestDiffTrees:
    def test_identical_trees_have_empty_diff(self):
        tree = _tree(_svc(BAT, _char(LVL)))
        assert diff_is_empty(diff_trees(tree, tree))

    def test_reordering_does_not_diff(self):
        a = _tree(_svc(BAT, _char(LVL)), _svc(GAP, _char(NAME)))
        b = _tree(_svc(GAP, _char(NAME)), _svc(BAT, _char(LVL)))
        assert diff_is_empty(diff_trees(a, b))

    def test_added_and_removed_service(self):
        old = _tree(_svc(BAT, _char(LVL)))
        new = _tree(_svc(GAP, _char(NAME)))
        d = diff_trees(old, new)
        assert d["services_added"] == [GAP]
        assert d["services_removed"] == [BAT]

    def test_added_and_removed_characteristic(self):
        old = _tree(_svc(BAT, _char(LVL)))
        new = _tree(_svc(BAT, _char(LVL), _char(NAME)))
        d = diff_trees(old, new)
        assert d["characteristics_added"] == [(BAT, NAME)]
        assert d["characteristics_removed"] == []

    def test_property_change_is_detected(self):
        old = _tree(_svc(BAT, _char(LVL, properties=("read",))))
        new = _tree(_svc(BAT, _char(LVL, properties=("read", "notify"))))
        d = diff_trees(old, new)
        assert d["properties_changed"] == [
            {"service": BAT, "characteristic": LVL, "from": ["read"], "to": ["read", "notify"]}
        ]

    def test_descriptor_added(self):
        old = _tree(_svc(BAT, _char(LVL)))
        new = _tree(_svc(BAT, _char(LVL, descriptors=(CCCD,))))
        d = diff_trees(old, new)
        assert d["descriptors_added"] == [(BAT, LVL, CCCD)]

    def test_not_empty_when_anything_changed(self):
        old = _tree(_svc(BAT, _char(LVL)))
        new = _tree(_svc(BAT, _char(LVL, properties=("read", "write"))))
        assert not diff_is_empty(diff_trees(old, new))


class TestLoadTree:
    def test_round_trips_a_written_snapshot(self, tmp_path):
        tree = _tree(_svc(BAT, _char(LVL)))
        p = tmp_path / "snap.json"
        p.write_text(json.dumps(tree))
        assert load_tree(str(p)) == tree
