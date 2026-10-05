# WAMBLE — Windows And Mac BLE

Bluetooth Low Energy tooling for **macOS and Windows**, in the shape of the
Linux `gatttool` / BlueZ command-line utilities.

`gatttool`, `bluetoothctl`, `btmgmt` and `hciconfig` are part of the Linux BlueZ
stack. They do not exist on macOS (which talks to Bluetooth through
CoreBluetooth) or on Windows (which uses the WinRT Bluetooth API). WAMBLE
reimplements the parts of that toolkit that are useful for inspecting and poking
at BLE peripherals, using [bleak] for the Bluetooth work and [rich] for terminal
output. Because bleak abstracts CoreBluetooth and WinRT behind one API, the same
scripts run on both operating systems.

No `sudo`, no `hcitool`, no BlueZ. Just Python.

> **Platform status.** WAMBLE is developed and tested on macOS. The Windows
> support is by way of bleak's WinRT backend and is expected to work from
> PowerShell, but has not yet been verified on a Windows machine — if you run it
> on Windows, reports (and PRs) are welcome. Where macOS and Windows differ, it
> is called out below.

[bleak]: https://github.com/hbldh/bleak
[rich]: https://github.com/Textualize/rich

---

## Requirements

- **macOS 11+** *or* **Windows 10 (build 16299+) / Windows 11**
- Python 3.11 or newer (uses `asyncio.timeout` and PEP 604 unions)
- Bluetooth enabled, and permission to use it

### macOS

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

bleak installs the CoreBluetooth bindings (`pyobjc-framework-corebluetooth`) for
you. The first time a script touches the adapter, macOS shows a Bluetooth
permission prompt — if you dismissed it, re-enable it under **System Settings →
Privacy & Security → Bluetooth** for your terminal app.

### Windows (PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

bleak uses the built-in WinRT Bluetooth API — no extra native packages. Make
sure Bluetooth is turned on (**Settings → Bluetooth & devices**). If PowerShell
blocks the activate script, allow it for the session with
`Set-ExecutionPolicy -Scope Process RemoteSigned`. Use `python` (or `py`) in
place of `python3` in the examples below.

## Quick start

```bash
./ble_tui.sh                         # menu TUI driving every tool (macOS/Linux shells)
.\ble_tui.ps1                        # same menu TUI, native PowerShell (Windows)
python3 scan_ble.py                  # what is advertising near me?
python3 enum_ble.py "Device Name"    # what GATT attributes does it expose?
python3 gatt_cli.py "Device Name"    # poke at it interactively
```

## Scripts

| Script | Replaces (Linux) | What it does |
| --- | --- | --- |
| [`scan_ble.py`](scan_ble.py) | `bluetoothctl scan on`, `hcitool scan` | Scan advertisements for a fixed window. Filter by name, service UUID or RSSI. Optionally dump JSON. |
| [`watch_ble.py`](watch_ble.py) | `btmon` | Live-refreshing view of advertisements, strongest signal first, until interrupted. |
| [`enum_ble.py`](enum_ble.py) | `gatttool -a` | Connect, list every service/characteristic/descriptor, and optionally read, list writable, or subscribe. Has a CTF-oriented mode. |
| [`gatt_cli.py`](gatt_cli.py) | `gatttool` interactive mode | REPL: read, write, subscribe and unsubscribe against a live connection. |
| [`gatt_find.py`](gatt_find.py) | `gatttool find` | Find characteristics or descriptors by UUID substring. |
| [`gatt_battery.py`](gatt_battery.py) | `gatttool -t Random -n 0x180f` | Read the standard Battery Level characteristic (`0x2A19`). |
| [`read_device_info.py`](read_device_info.py) | — | Read the Device Information Service (`0x180A`): model, serial, firmware, hardware revisions. |
| [`gatt_mtu.py`](gatt_mtu.py) | `gatttool -m` | Report the negotiated ATT MTU. Read-only — see [MTU](#mtu-and-connection-parameters). |
| [`gatt_params.py`](gatt_params.py) | `btmgmt conn-update` | Read or request a connection parameter range via descriptor `0x2A0E`. |
| [`ble_common.py`](ble_common.py) · [`ble_gatt.py`](ble_gatt.py) | — | Shared libraries. Not entry points. |

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
```

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
`write-cmd`, `notify`, `indicate`, `unnotify`, `quit`. The read/write/subscribe
commands take a UUID substring or a handle, matched case-insensitively.

### Finding a UUID, device info, battery

```bash
python3 gatt_find.py "Acme Tracker" 2a19
python3 gatt_find.py "Acme Tracker" 2902 --target descr
python3 read_device_info.py "Acme Tracker"
python3 gatt_battery.py "Acme Tracker"
```

## Menu TUI, exploits, and CTF client

Beyond the individual scripts, WAMBLE ships three extras, all built on the same
`bleak` core (so the same cross-platform expectations apply):

- **[`ble_tui.sh`](ble_tui.sh)** / **[`ble_tui.ps1`](ble_tui.ps1)** — a
  keyboard-driven menu that launches every tool below, prompts for the
  device/arguments, and includes a captures viewer. Use the **`.sh`** on
  macOS/Linux shells (or WSL/Git Bash), the **`.ps1`** natively in PowerShell on
  Windows; or just call the Python tools directly. Both are thin launchers with
  identical menus.
- **[`BLE-Exploits/`](BLE-Exploits/)** — a suite of **authorized, non-destructive**
  BLE vulnerability demonstrations (unauthenticated GATT harvest, posture
  assessment, LED control PoC, notification capture, capture-replay, persistence,
  device-name defacement, passive advertisement harvest), each targeting one
  named device, for hardware you own. See [`BLE-Exploits/README.md`](BLE-Exploits/README.md).
- **[`ble_ctf.py`](ble_ctf.py)** — a gatttool-style, scriptable client for a
  hackgnar-style BLE CTF (read/write/notify by handle, read-loop, score/submit).
  On macOS it solves 16/20 flags (4 need Linux/BlueZ — set-MAC and force-MTU, and
  two "hidden notification" flags CoreBluetooth can't subscribe to); on Windows
  the ATT handles match the Linux walkthrough directly.

These carry an authorization gate on anything that transmits. Use them only
against devices you own or are authorized to test.

## Platform differences and limits

This is the honest part. CoreBluetooth and WinRT both expose far less than BlueZ,
and some of `gatttool`'s most-used features have no cross-platform equivalent.

**Device address.** On **Windows** and **Linux**, `BLEDevice.address` is the
peripheral's real Bluetooth MAC — stable, and the thing you can pass as a target.
On **macOS**, CoreBluetooth hides the MAC and hands you a per-host UUID instead,
which changes across reboots. On macOS, prefer a **name substring**; on Windows
you can use either the name or the MAC. All scripts accept either.

**ATT handles.** BlueZ/`gatttool` expose the real ATT handle of each attribute.
WinRT exposes real handles; **CoreBluetooth does not** — bleak synthesizes a
handle on macOS that is the characteristic *declaration* handle, one below the
`gatttool` *value* handle. If a handle from a Linux walkthrough does not resolve
on macOS, try one lower, or address the attribute by UUID (always reliable).

**No scripted pairing on macOS.** `bleak` exposes `BleakClient.pair()`; on
Windows it drives the OS pairing flow, but on CoreBluetooth pairing is OS-driven
and cannot be scripted the way `bluetoothctl pair <mac>` can on Linux.

**No raw packet capture.** Neither macOS nor Windows hands applications the raw
advertisement/HCI stream the way a BlueZ sniffer (`btmon`) does.

### MTU and connection parameters

`gatt_mtu.py` **reports** the negotiated MTU; it cannot set it. Both
CoreBluetooth and WinRT negotiate the ATT MTU themselves at connection setup and
expose it read-only (`BleakClient.mtu_size`). Linux `gatttool -m` can force an
MTU because it binds to BlueZ's HCI socket; there is no equivalent on macOS or
Windows.

`gatt_params.py --set` writes descriptor `0x2A0E` on the GAP service (`0x1800`),
the correct place to *request* a connection parameter range — but it is only a
request. The values actually in force are negotiated in HCI, which neither
CoreBluetooth nor WinRT exposes, so `--get` reports what the peripheral
*advertises*, not what is in force, and says so.

On Linux/BlueZ `mtu_size` always reports 23 regardless of the real link MTU, so
`gatt_mtu.py` is only meaningful on macOS and Windows.

## Notes on bleak

Written against bleak 3.x.

- `BleakScanner.find_device_by_name()` matches `local_name` **exactly**; these
  scripts match on a *substring*, so `ble_common.find_device()` uses
  `find_device_by_filter()` instead.
- `find_device_by_filter()` resolves as soon as a device matches rather than
  sleeping for the full timeout.

## Troubleshooting

**Nothing is found / no permission prompt.**
- *macOS:* Bluetooth access is off for your terminal — enable it under
  **System Settings → Privacy & Security → Bluetooth**.
- *Windows:* make sure Bluetooth is on in **Settings → Bluetooth & devices**,
  and that the app has Bluetooth permission.

**Connects then drops / `Services discovery failed`.** Some cheap devices need a
moment after connect — retry, or raise `--connect-timeout`.

**Reads return empty or `Insufficient Authentication`.** The characteristic
requires bonding/encryption; neither OS lets you force that pairing from a script.

**A handle from a Linux writeup doesn't resolve on macOS.** See *ATT handles*
above — address by UUID, or try the handle one lower.

## Tests

The pure logic — UUID handling, GATT target resolution, long writes,
advertisement parsing — is tested without a Bluetooth adapter and runs on any OS:

```bash
python -m pytest -q        # no hardware required
```

## Contributing

- Keep each script runnable on its own.
- Shared helpers belong in `ble_common.py` / `ble_gatt.py`.
- Verify changes against the installed bleak:
  `python -m py_compile *.py` and `python scan_ble.py --help`.
- Keep the pure functions in `ble_common.py`/`scan_ble.py` free of I/O and tested.

## License

[MIT](LICENSE)
