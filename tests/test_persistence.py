"""Tests for the persistence verdict + state round-trip in BLE-Exploits.

persistence_verdict decides whether an unauthenticated write survived a reboot,
from either an automated readback or the operator's attestation. Getting the
precedence and normalisation right is what makes the PoC's conclusion trustworthy.
"""

import sys
from pathlib import Path

_EXPLOITS = Path(__file__).resolve().parent.parent / "BLE-Exploits"
if str(_EXPLOITS) not in sys.path:
    sys.path.insert(0, str(_EXPLOITS))

from ble_persistence_test import (
    load_state,
    persistence_verdict,
    save_state,
    state_path,
)


class TestPersistenceVerdict:
    def test_attestation_yes_is_persisted(self):
        assert persistence_verdict("33 01 01", None, "yes") == "persisted"

    def test_attestation_no_is_not_persisted(self):
        assert persistence_verdict("33 01 01", None, "no") == "not-persisted"

    def test_readback_equal_to_armed_is_persisted(self):
        assert persistence_verdict("01 02 03", "01 02 03", "unknown") == "persisted"

    def test_readback_differs_is_not_persisted(self):
        assert persistence_verdict("01 02 03", "00 00 00", "unknown") == "not-persisted"

    def test_readback_comparison_ignores_spacing_and_case(self):
        assert persistence_verdict("AA BB", "aabb", "unknown") == "persisted"

    def test_no_readback_no_attestation_is_unknown(self):
        assert persistence_verdict("33 01 01", None, "unknown") == "unknown"

    def test_attestation_wins_over_readback(self):
        # Operator says it persisted even though readback differs (e.g. the
        # readback char does not reflect the behavioural state).
        assert persistence_verdict("01", "99", "yes") == "persisted"


class TestStateRoundTrip:
    def test_save_then_load_returns_same_dict(self, tmp_path):
        p = tmp_path / "s.json"
        state = {"device": "Govee", "write_hex": "33 01 01", "original_hex": None}
        save_state(p, state)
        assert load_state(p) == state

    def test_state_path_is_filesystem_safe(self):
        p = state_path("Govee H61E0 (50)")
        assert p.name == "persistence-state-Govee_H61E0__50_.json"
