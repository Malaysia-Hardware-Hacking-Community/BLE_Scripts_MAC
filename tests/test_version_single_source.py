"""Guard that the project version has exactly one source of truth.

The version used to be copied into pyproject.toml, the package, and both TUI
launchers, and they drifted (the launchers were left on an old version after a
release). Now ``src/wamble/__init__.py`` is the only place the version is
written: pyproject reads it dynamically and the launchers read it at runtime.
These tests fail if anyone reintroduces a hardcoded version literal.
"""

import re
import tomllib
from pathlib import Path

import wamble

_ROOT = Path(__file__).resolve().parent.parent


def _pyproject() -> dict:
    with open(_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


class TestSingleSource:
    def test_package_has_a_version(self):
        assert re.fullmatch(r"\d+\.\d+\.\d+", wamble.__version__), wamble.__version__

    def test_pyproject_reads_version_dynamically(self):
        project = _pyproject()["project"]
        # No static version key: it must be declared dynamic instead.
        assert "version" not in project, "pyproject should not hardcode a version"
        assert "version" in project.get("dynamic", []), "version must be dynamic"

    def test_pyproject_points_dynamic_version_at_the_package(self):
        dynamic = _pyproject()["tool"]["setuptools"]["dynamic"]
        assert dynamic["version"] == {"attr": "wamble.__version__"}


class TestLaunchersDeriveVersion:
    # A hardcoded "0.1.2"-style assignment in a launcher is exactly the bug.
    def test_bash_launcher_does_not_hardcode_version(self):
        # Read as UTF-8 explicitly: the launcher has non-ASCII glyphs and Windows
        # would otherwise decode it as cp1252 and raise (byte 0x90 from "←").
        text = (_ROOT / "ble_tui.sh").read_text(encoding="utf-8")
        assert not re.search(r'VERSION=["\']\d+\.\d+', text), "ble_tui.sh hardcodes a version"
        assert "__version__" in text, "ble_tui.sh should read wamble.__version__"

    def test_powershell_launcher_does_not_hardcode_version(self):
        text = (_ROOT / "ble_tui.ps1").read_text(encoding="utf-8")
        assert not re.search(r"\$Version\s*=\s*['\"]\d+\.\d+", text), (
            "ble_tui.ps1 hardcodes a version"
        )
        assert "__version__" in text, "ble_tui.ps1 should read wamble.__version__"


class TestLaunchersAreUtf8:
    # The launchers carry non-ASCII glyphs (arrows, box drawing). They must stay
    # valid UTF-8 so reading them with encoding="utf-8" never raises, including on
    # Windows, whose default cp1252 cannot even decode some of these bytes - the
    # failure that broke Windows CI once.
    def test_bash_launcher_is_valid_utf8(self):
        (_ROOT / "ble_tui.sh").read_bytes().decode("utf-8")

    def test_powershell_launcher_is_valid_utf8(self):
        (_ROOT / "ble_tui.ps1").read_bytes().decode("utf-8")
