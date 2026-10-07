"""Tests that the console-script entry points stay wired to real functions.

These do not install the project; they check that every ``wamble-*`` command
declared in pyproject.toml points at a callable that actually exists in
``wamble.cli``, so a renamed or deleted wrapper fails here instead of at install
time for a user.
"""

import tomllib
from pathlib import Path

from wamble import cli

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _declared_scripts() -> dict[str, str]:
    with open(_PYPROJECT, "rb") as f:
        return tomllib.load(f)["project"]["scripts"]


class TestConsoleScripts:
    def test_pyproject_declares_scripts(self):
        assert _declared_scripts(), "no [project.scripts] declared"

    def test_every_script_targets_an_existing_callable(self):
        for command, target in _declared_scripts().items():
            module, _, func = target.partition(":")
            assert module == "wamble.cli", f"{command} should live in wamble.cli"
            assert callable(getattr(cli, func, None)), f"{command} -> {target} is not a callable"

    def test_each_wrapper_imports_a_real_main(self):
        # The wrappers import their tool lazily; importing the referenced module
        # and finding an async main() is what makes the command do anything.
        import asyncio
        import importlib

        tool_modules = {
            "scan": "wamble.scan",
            "watch": "wamble.watch",
            "enum": "wamble.enum",
            "gatt": "wamble.interactive",
            "find": "wamble.find",
            "battery": "wamble.battery",
            "device_info": "wamble.device_info",
            "mtu": "wamble.mtu",
            "params": "wamble.params",
            "ctf": "wamble.ctf",
            "export": "wamble.export",
            "batch": "wamble.batch",
            "adv_log": "wamble.adv_log",
            "notify_log": "wamble.notify_log",
        }
        for func, module_name in tool_modules.items():
            assert callable(getattr(cli, func)), func
            main = importlib.import_module(module_name).main
            assert asyncio.iscoroutinefunction(main), f"{module_name}.main must be async"

    def test_targets_wrapper_targets_a_sync_main(self):
        # Unlike the other tools, the target-profile manager is synchronous, so
        # its wrapper calls main() directly rather than via asyncio.
        import asyncio

        from wamble.targets import main

        assert callable(cli.targets)
        assert not asyncio.iscoroutinefunction(main)
