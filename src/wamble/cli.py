"""Console-script entry points for WAMBLE.

Installing the project (``pip install .``) exposes each tool as a ``wamble-*``
command, so ``wamble-scan`` runs the same code as ``python -m wamble.scan``.
These thin wrappers only adapt each tool's asynchronous ``main()`` to a
synchronous console entry point and give Ctrl-C the same clean exit the tools
have when run as modules.

Each tool is imported lazily inside its wrapper so a single command starts up
without importing the others.
"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from wamble.common import console


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
    from wamble.scan import main

    _run(main)


def watch() -> None:
    from wamble.watch import main

    _run(main, "Stopped.")


def enum() -> None:
    from wamble.enum import main

    _run(main)


def gatt() -> None:
    from wamble.interactive import main

    _run(main)


def find() -> None:
    from wamble.find import main

    _run(main)


def battery() -> None:
    from wamble.battery import main

    _run(main)


def device_info() -> None:
    from wamble.device_info import main

    _run(main)


def mtu() -> None:
    from wamble.mtu import main

    _run(main)


def params() -> None:
    from wamble.params import main

    _run(main)


def ctf() -> None:
    from wamble.ctf import main

    _run(main)


def export() -> None:
    from wamble.export import main

    _run(main)


def batch() -> None:
    from wamble.batch import main

    _run(main)


def profile() -> None:
    from wamble.profiles import main

    _run(main, "Stopped.")


def adv_log() -> None:
    from wamble.adv_log import main

    _run(main, "Stopped.")


def notify_log() -> None:
    from wamble.notify_log import main

    _run(main, "Stopped.")


def targets() -> None:
    # The target-profile manager is synchronous (it only reads and writes a JSON
    # file), so it is called directly rather than through the asyncio _run helper.
    from wamble.targets import main

    main()
