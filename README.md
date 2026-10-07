# WAMBLE: Windows And Mac BLE

[![CI](https://github.com/Malaysia-Hardware-Hacking-Community/WAMBLE/actions/workflows/ci.yml/badge.svg)](https://github.com/Malaysia-Hardware-Hacking-Community/WAMBLE/actions/workflows/ci.yml)
[![macOS](https://img.shields.io/badge/macOS-tested-success?logo=apple&logoColor=white)](https://github.com/Malaysia-Hardware-Hacking-Community/WAMBLE/actions/workflows/ci.yml)
[![Windows](https://img.shields.io/badge/Windows-tested-success?logo=windows&logoColor=white)](https://github.com/Malaysia-Hardware-Hacking-Community/WAMBLE/actions/workflows/ci.yml)

<p align="center">
  <img src="assets/WAMBLE-TUI.png" alt="WAMBLE terminal UI (ble_tui) showing the main menu" width="720">
</p>

Bluetooth Low Energy tooling for **macOS and Windows**, in the shape of the
Linux `gatttool` and BlueZ command-line utilities.

`gatttool`, `bluetoothctl`, `btmgmt` and `hciconfig` are part of the Linux BlueZ
stack. They do not exist on macOS (which talks to Bluetooth through
CoreBluetooth) or on Windows (which uses the WinRT Bluetooth API). WAMBLE
reimplements the parts of that toolkit that are useful for inspecting and poking
at BLE peripherals, using [bleak] for the Bluetooth work and [rich] for terminal
output. Because bleak puts one API in front of CoreBluetooth and WinRT, the same
scripts run on both operating systems.

No `sudo`, no `hcitool`, no BlueZ. Just Python.

> **Please use this responsibly.** WAMBLE can read from and write to real
> devices, and the `BLE-Exploits/` folder contains working proof-of-concept
> attacks. Only point it at devices you own or have written permission to test.
> See [SECURITY.md](SECURITY.md).

> **Platform status.** WAMBLE is developed and tested on macOS. Windows support
> runs on bleak's WinRT backend and is expected to work from PowerShell, but has
> not been verified on a Windows machine yet. If you run it on Windows, reports
> and pull requests are welcome. Where macOS and Windows differ, it is called out
> below.

[bleak]: https://github.com/hbldh/bleak
[rich]: https://github.com/Textualize/rich

---

## Requirements

- macOS 11 or newer, or Windows 10 (build 16299+) and Windows 11
- Python 3.11 or newer (uses `asyncio.timeout` and PEP 604 unions)
- Bluetooth enabled, and permission to use it

### macOS

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

bleak installs the CoreBluetooth bindings (`pyobjc-framework-corebluetooth`) for
you. The first time a script touches the adapter, macOS shows a Bluetooth
permission prompt. If you dismissed it, re-enable it under **System Settings >
Privacy & Security > Bluetooth** for your terminal app.

### Windows (PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

bleak uses the built-in WinRT Bluetooth API, so there are no extra native
packages. Make sure Bluetooth is turned on (**Settings > Bluetooth & devices**).
If PowerShell blocks the activate script, allow it for the session with
`Set-ExecutionPolicy -Scope Process RemoteSigned`. Use `python` (or `py`) in
place of `python3` in the examples below.

### Install as commands (optional)

The scripts run directly as shown below, with no install step. If you prefer to
call them from anywhere as `wamble-*` commands, install the project into your
environment:

```bash
pip install .            # or: pip install -e .  (editable, for development)
```

This adds `wamble-scan`, `wamble-watch`, `wamble-enum`, `wamble-gatt`,
`wamble-find`, `wamble-battery`, `wamble-device-info`, `wamble-mtu`,
`wamble-params` and `wamble-ctf`, each the same as running its script. For
example, `wamble-scan -t 15` is `python3 scan_ble.py -t 15`.

## Quick start

```bash
./ble_tui.sh                         # menu TUI driving every tool (macOS/Linux shells)
.\ble_tui.ps1                        # same menu TUI, native PowerShell (Windows)
python3 scan_ble.py                  # what is advertising near me?
python3 enum_ble.py "Device Name"    # what GATT attributes does it expose?
python3 gatt_cli.py "Device Name"    # poke at it interactively
```

## Scripts

| Script                                                         | Replaces (Linux)                       | What it does                                                                                                                           |
| -------------------------------------------------------------- | -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| [`scan_ble.py`](scan_ble.py)                                   | `bluetoothctl scan on`, `hcitool scan` | Scan advertisements for a fixed window. Filter by name, service UUID or RSSI. Optionally dump JSON.                                    |
| [`watch_ble.py`](watch_ble.py)                                 | `btmon`                                | Live-refreshing view of advertisements, strongest signal first, until interrupted.                                                     |
| [`enum_ble.py`](enum_ble.py)                                   | `gatttool -a`                          | Connect, list every service, characteristic and descriptor, and optionally read, list writable, or subscribe. Has a CTF-oriented mode. |
| [`gatt_cli.py`](gatt_cli.py)                                   | `gatttool` interactive mode            | REPL: read, write, subscribe and unsubscribe against a live connection. See the [cheatsheet](GATT-CLI-CHEATSHEET.md).                  |
| [`gatt_find.py`](gatt_find.py)                                 | `gatttool find`                        | Find characteristics or descriptors by UUID substring.                                                                                 |
| [`gatt_battery.py`](gatt_battery.py)                           | `gatttool -t Random -n 0x180f`         | Read the standard Battery Level characteristic (`0x2A19`).                                                                             |
| [`read_device_info.py`](read_device_info.py)                   | n/a                                    | Read the Device Information Service (`0x180A`): model, serial, firmware, hardware revisions.                                           |
| [`gatt_mtu.py`](gatt_mtu.py)                                   | `gatttool -m`                          | Report the negotiated ATT MTU. Read-only; see [MTU](#mtu-and-connection-parameters).                                                   |
| [`gatt_params.py`](gatt_params.py)                             | `btmgmt conn-update`                   | Read or request the Peripheral Preferred Connection Parameters characteristic (`0x2A04`).                                              |
| [`ble_targets.py`](ble_targets.py)                             | n/a                                    | Save short aliases for devices (`@name`), so any connecting tool can target them. See [Target profiles](#target-profiles).             |
| [`ble_common.py`](ble_common.py), [`ble_gatt.py`](ble_gatt.py) | n/a                                    | Shared libraries. Not entry points.                                                                                                    |

Every script takes `--help`.

## Usage

### Scanning

```bash
python3 scan_ble.py -t 15                          # 15 second scan
python3 scan_ble.py -n Fitbit                      # only names containing "Fitbit"
python3 scan_ble.py -s 180f                        # only devices advertising 0x180F
python3 scan_ble.py -m -70                         # ignore anything weaker than -70 dBm
python3 scan_ble.py --plain                        # no table, pipe-friendly
python3 scan_ble.py --write-to scan.json           # save results as JSON
python3 scan_ble.py --csv scan.csv                 # save results as CSV (one row per device)
```

`--write-to` and `--csv` can be combined to write both at once, and both carry
the same per-device fields.

### Watching advertisements live

```bash
python3 watch_ble.py                      # refresh until Ctrl-C
python3 watch_ble.py --name Acme --timeout 60
```

### Enumerating GATT attributes

```bash
python3 enum_ble.py "Acme Tracker"
python3 enum_ble.py "Acme Tracker" --readable       # read everything readable
python3 enum_ble.py "Acme Tracker" --filter-uuid 2a  # just UUIDs containing "2a"
python3 enum_ble.py "Acme Tracker" --notify          # subscribe and stream updates
```

### Interactive client

```bash
$ python3 gatt_cli.py "Acme Tracker"
[gatt] read 2a19
[gatt] notify 2a37
[gatt] write-req 6e000001 0100
[gatt] unnotify 2a37
[gatt] quit
```

Commands: `services`, `characteristics`, `descriptors`, `read`, `write-req`,
`write-cmd`, `notify`, `indicate`, `unnotify`, `reconnect`, `help`, `quit`. The
read, write and subscribe commands take a UUID substring or a handle, matched
case-insensitively. The [cheatsheet](GATT-CLI-CHEATSHEET.md) explains each command
and how to build payloads.

### Finding a UUID, device info, battery

```bash
python3 gatt_find.py "Acme Tracker" 2a19
python3 gatt_find.py "Acme Tracker" 2902 --target descr
python3 read_device_info.py "Acme Tracker"
python3 gatt_battery.py "Acme Tracker"
```

### Target profiles

Typing a device name or address every time gets old, especially on macOS where
the address is a long per-host UUID that changes between reboots. Save a short
alias once, then target it with `@name` from any connecting tool:

```bash
python3 ble_targets.py add tv "[TV] Samsung Q60 Series"   # save an alias
python3 ble_targets.py add led "GBK_H619A"
python3 ble_targets.py list                               # show saved aliases
python3 enum_ble.py @tv                                   # use it anywhere
python3 gatt_battery.py @led
python3 ble_targets.py remove tv                          # delete an alias
python3 ble_targets.py path                               # where the file lives
```

An alias maps to whatever you would otherwise type: a name substring or an
address. Aliases are stored in a small JSON file (run `ble_targets.py path` to
see where). An unknown `@name` is reported as "not found", the same as any other
target that is not nearby.

## Menu TUI, exploits, and CTF client

Beyond the individual scripts, WAMBLE ships three extras, all built on the same
`bleak` core, so the same cross-platform expectations apply:

- **[`ble_tui.sh`](ble_tui.sh)** and **[`ble_tui.ps1`](ble_tui.ps1)**: a
  keyboard-driven menu that launches every tool below, prompts for the device and
  arguments, and includes a captures viewer. Use the **`.sh`** on macOS and Linux
  shells (or WSL and Git Bash), and the **`.ps1`** natively in PowerShell on
  Windows. You can also call the Python tools directly. Both launchers have
  identical menus.
- **[`BLE-Exploits/`](BLE-Exploits/)**: a suite of authorized, non-destructive
  BLE vulnerability demonstrations (unauthenticated GATT harvest, posture
  assessment, LED control PoC, notification capture, capture-replay, persistence,
  device-name defacement, passive advertisement harvest), each targeting one
  named device, for hardware you own. See [`BLE-Exploits/README.md`](BLE-Exploits/README.md).
- **[`ble_ctf.py`](ble_ctf.py)**: a gatttool-style, scriptable client for a
  hackgnar-style BLE CTF (read, write and notify by handle, read-loop, score and
  submit). On macOS it solves 16 of 20 flags. The other 4 need Linux and BlueZ
  (set-MAC and force-MTU, plus two hidden-notification flags CoreBluetooth cannot
  subscribe to). On Windows the ATT handles match the Linux walkthrough directly.

These carry an authorization gate on anything that transmits. Use them only
against devices you own or are authorized to test.

## Platform differences and limits

This is the honest part. CoreBluetooth and WinRT both expose far less than BlueZ,
and some of `gatttool`'s most-used features have no cross-platform equivalent.

**Device address.** On **Windows** and **Linux**, `BLEDevice.address` is the
peripheral's real Bluetooth MAC. It is stable, and it is the thing you can pass as
a target. On **macOS**, CoreBluetooth hides the MAC and hands you a per-host UUID
instead, which changes across reboots. On macOS, prefer a **name substring**. On
Windows you can use either the name or the MAC. All scripts accept either.

**ATT handles.** BlueZ and `gatttool` expose the real ATT handle of each
attribute. WinRT exposes real handles. **CoreBluetooth does not**, so bleak
synthesizes a handle on macOS that is the characteristic _declaration_ handle, one
below the `gatttool` _value_ handle. If a handle from a Linux walkthrough does not
resolve on macOS, try one lower, or address the attribute by UUID, which always
works.

**No scripted pairing on macOS.** `bleak` exposes `BleakClient.pair()`. On Windows
it drives the OS pairing flow, but on CoreBluetooth pairing is OS-driven and
cannot be scripted the way `bluetoothctl pair <mac>` can on Linux.

**No raw packet capture.** Neither macOS nor Windows hands applications the raw
advertisement and HCI stream the way a BlueZ sniffer (`btmon`) does.

### MTU and connection parameters

`gatt_mtu.py` **reports** the negotiated MTU. It cannot set it. Both CoreBluetooth
and WinRT negotiate the ATT MTU themselves at connection setup and expose it
read-only (`BleakClient.mtu_size`). Linux `gatttool -m` can force an MTU because it
binds to BlueZ's HCI socket. There is no equivalent on macOS or Windows.

`gatt_params.py` reads the Peripheral Preferred Connection Parameters
characteristic (`0x2A04`) on the GAP service (`0x1800`). These are the values the
peripheral _prefers_, not the values in force. With `--set` it attempts to write
them, but PPCP is read-only on most peripherals, so the write is usually rejected.
Even a central that wants to change a live connection has to do it over the link
layer, which neither CoreBluetooth nor WinRT exposes. Many peripherals (including
cheap LED controllers) do not expose PPCP at all, and `gatt_params.py` says so
clearly when that is the case.

On Linux and BlueZ, `mtu_size` always reports 23 regardless of the real link MTU,
so `gatt_mtu.py` is only meaningful on macOS and Windows.

## Notes on bleak

Written against bleak 3.x.

- `BleakScanner.find_device_by_name()` matches `local_name` exactly. These scripts
  match on a substring, so `ble_common.find_device()` scans advertisements and
  returns as soon as one matches.
- Matching on first sight returns as soon as a device matches rather than sleeping
  for the full timeout.

## Troubleshooting

**Nothing is found, or no permission prompt.**

- macOS: Bluetooth access is off for your terminal. Enable it under
  **System Settings > Privacy & Security > Bluetooth**.
- Windows: make sure Bluetooth is on in **Settings > Bluetooth & devices**, and
  that the app has Bluetooth permission.

**Connects then drops, or `Services discovery failed`.** Some cheap devices need a
moment after connect. Retry, or raise `--connect-timeout`.

**Reads return empty, or `Insufficient Authentication`.** The characteristic
requires bonding or encryption, and neither OS lets you force that pairing from a
script.

**A handle from a Linux writeup does not resolve on macOS.** See _ATT handles_
above. Address by UUID, or try the handle one lower.

## Tests

The pure logic (UUID handling, GATT target resolution, long writes, advertisement
parsing) is tested without a Bluetooth adapter and runs on any OS:

```bash
python -m pytest -q        # no hardware required
```

## Contributing

Contributions of every kind are welcome, including bug reports, device
compatibility reports, docs, and code. See [CONTRIBUTING.md](CONTRIBUTING.md) to
get started, and please read the [Code of Conduct](CODE_OF_CONDUCT.md).

In short: keep each script runnable on its own, put shared helpers in
`ble_common.py` and `ble_gatt.py`, run `python -m pytest -q` before you open a
pull request, and only test against devices you own or are allowed to test.

## Project files

- [CONTRIBUTING.md](CONTRIBUTING.md): how to set up, test, and submit a change
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md): the community standards we follow
- [SECURITY.md](SECURITY.md): responsible use and how to report a security problem
- [SUPPORT.md](SUPPORT.md): where to get help
- [GOVERNANCE.md](GOVERNANCE.md): how decisions are made
- [CHANGELOG.md](CHANGELOG.md): notable changes over time

## License

[MIT](LICENSE). Copyright (c) 2026 Malaysia Hardware Hacking Community.
