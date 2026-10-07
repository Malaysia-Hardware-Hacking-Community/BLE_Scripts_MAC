"""Console-script entry points for WAMBLE.

Installing the project (``pip install .``) exposes each tool as a ``wamble-*``
command, so ``wamble-scan`` runs the same code as ``python3 scan_ble.py``. The
scripts stay runnable on their own; these thin wrappers only adapt each
asynchronous ``main()`` to a synchronous console entry point and give Ctrl-C the
same clean exit the scripts have when run directly.

Each tool is imported lazily inside its wrapper so a single command starts up
without importing the others.
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from ble_common import console


def _run(main_fn: Callable[[], Coroutine[Any, Any, None]], stopped: str = "Cancelled.") -> None:
    """Run an async ``main`` as a console entry point, exiting cleanly on Ctrl-C.

    *stopped* is the word shown on interrupt, matching the message each script
    prints when run directly (most say "Cancelled."; the live watcher says
    "Stopped.").
    """
    try:
        asyncio.run(main_fn())
    except KeyboardInterrupt:
        console.print(f"\n[yellow]{stopped}[/yellow]")


def scan() -> None:
    from scan_ble import main

    _run(main)


def watch() -> None:
    from watch_ble import main

    _run(main, "Stopped.")


def enum() -> None:
    from enum_ble import main

    _run(main)


def gatt() -> None:
    from gatt_cli import main

    _run(main)


def find() -> None:
    from gatt_find import main

    _run(main)


def battery() -> None:
    from gatt_battery import main

    _run(main)


def device_info() -> None:
    from read_device_info import main

    _run(main)


def mtu() -> None:
    from gatt_mtu import main

    _run(main)


def params() -> None:
    from gatt_params import main

    _run(main)


def ctf() -> None:
    from ble_ctf import main

    _run(main)
