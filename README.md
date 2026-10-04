# BLE_Scripts_MAC

Bluetooth Low Energy tooling for macOS, in the shape of the Linux `gatttool` / BlueZ
command-line utilities.

`gatttool`, `bluetoothctl`, `btmgmt` and `hciconfig` are part of the Linux BlueZ
stack. They do not exist on macOS, which talks to Bluetooth through CoreBluetooth
instead. This repository reimplements the parts of that toolkit that are useful
for inspecting and poking at BLE peripherals, using [bleak] for the Bluetooth
work and [rich] for terminal output.

No `sudo`, no `hcitool`, no BlueZ. Just Python.

[bleak]: https://github.com/hbldh/bleak
[rich]: https://github.com/Textualize/rich

---

## Requirements

- macOS 11 or newer
- Python 3.11 or newer
- Bluetooth enabled, and permission to use it

```bash
git clone https://github.com/Malaysia-Hardware-Hacking-Community/BLE_Scripts_MAC.git
cd BLE_Scripts_MAC
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

On macOS, bleak installs the CoreBluetooth bindings (`pyobjc-framework-corebluetooth`)
for you. The first time a script touches the Bluetooth adapter, macOS shows a
permission prompt — if you dismissed it, re-enable it under
**System Settings → Privacy & Security → Bluetooth**.

## Quick start

```bash
python3 scan_ble.py                  # what is advertising near me?
python3 enum_ble.py "Device Name"    # what GATT attributes does it expose?
python3 gatt_cli.py "Device Name"    # poke at it interactively
```

## Scripts

| Script | Replaces | What it does |
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
| [`ble_common.py`](ble_common.py) | — | Shared library. Not an entry point. |

Every script takes `--help`.

## Usage

### Scanning

```bash
python3 scan_ble.py -t 15                          # 15 second scan
python3 scan_ble.py -n Fitbit                      # only names containing "Fitbit"
python3 scan_ble.py -s 180f                       # only devices advertising 0x180F
python3 scan_ble.py -m -70                        # ignore anything weaker than -70 dBm
python3 scan_ble.py --plain                       # no table, pipe-friendly
python3 scan_ble.py --write-to scan.json          # save results as JSON
```

```
                                 Nearby BLE Devices
┏━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃  # ┃ Name         ┃ Address /         ┃ RSSI ┃ Advertised       ┃ Manufacturer data    ┃
┃    ┃              ┃ Identifier        ┃      ┃ services         ┃                      ┃
┡━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│  1 │ Acme Tracker ┆ F4:FE:FB:B7:AF:32 ┆ -52  ┆ 180f, 181a       ┆ 0x004C: 02 15 …    │
└────┴──────────────┴────────────────────┴──────┴──────────────────┴──────────────────────┘
```

### Watching advertisements live

```bash
python3 watch_ble.py                      # refresh until Ctrl-C
python3 watch_ble.py --name Acme --timeout 60
```

The screen redraws in place at `--refresh` frames per second (default 4) instead of
scrolling a new table every couple of seconds.

### Enumerating GATT attributes

```bash
python3 enum_ble.py "Acme Tracker"
python3 enum_ble.py "Acme Tracker" --readable       # read everything readable
python3 enum_ble.py "Acme Tracker" --filter-uuid 2a  # just UUIDs containing "2a"
python3 enum_ble.py "Acme Tracker" --notify          # subscribe and stream updates
python3 enum_ble.py "Acme Tracker" --ctf-mode        # highlight interesting UUIDs
```

`--notify` and `--indicate` both go through bleak's `start_notify`, which writes the
CCCD; the peripheral picks notify versus indicate from the value written. bleak has
no separate indication call, and does not need one.

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
`write-cmd`, `notify`, `indicate`, `unnotify`, `quit`. The read, write and
subscribe commands take a UUID substring, matched case-insensitively. The first
three print the same full enumeration, so nothing is hidden behind a narrower view.
Writes take hex bytes, e.g. `write-cmd 6e000001 0100`.

### Finding a UUID

```bash
python3 gatt_find.py "Acme Tracker" 2a19
python3 gatt_find.py "Acme Tracker" 2902 --target descr
```

### Device information and battery

```bash
python3 read_device_info.py "Acme Tracker"
python3 gatt_battery.py "Acme Tracker"
python3 gatt_battery.py "Acme Tracker" -f raw
```

## Things that do not work on macOS

This is the honest part. CoreBluetooth exposes far less than BlueZ, and some of
`gatttool`'s most-used features have no equivalent.

**There is no `bluetoothctl` pairing flow.** `bleak` exposes `BleakClient.pair()`,
but on CoreBluetooth pairing is driven by the OS and cannot be scripted the way
`bluetoothctl pair <mac>` can on Linux.

**MAC addresses are not MAC addresses.** On macOS, `BLEDevice.address` is a UUID
that CoreBluetooth generates per Mac per peripheral. It is *not* the peripheral's
real MAC, and it changes across reboots. Prefer a name substring. On Linux the same
field is the real MAC.

**Service data is limited.** macOS does not hand applications the raw advertisement
payload the way a BlueZ HCI sniffer does, so `btmon`-grade packet capture has no
equivalent here.

### MTU and connection parameters

`gatt_mtu.py` **reports** the negotiated MTU. It cannot set it.

CoreBluetooth negotiates the ATT MTU itself during connection setup, and bleak
exposes `BleakClient.mtu_size` as a read-only property. Linux `gatttool -m` can force
an MTU because it binds to BlueZ's HCI socket and issues an MTU Exchange Request
directly; there is no CoreBluetooth equivalent. An earlier version of this script
printed a success message without doing anything — that was a lie, and it is gone.

`gatt_params.py --set` writes descriptor `0x2A0E` on the GAP service (`0x1800`),
which is the correct place to request a connection parameter range. But the write is
only a *request*: the peripheral may accept, clamp, or ignore it, and the values
actually in force are negotiated in HCI, which macOS does not expose. `--get` reads
back what the peripheral *advertises*, which is not the same as what is in force, and
says so.

On Linux, `mtu_size` always reports 23 regardless of the real link MTU, so
`gatt_mtu.py` is only meaningful on macOS.

## Notes on bleak

Written against bleak 3.x. Two API details worth knowing if you extend this:

- `BleakScanner.find_device_by_name()` matches `local_name` **exactly**. These
  scripts match on a *substring*, so `ble_common.find_device()` uses
  `find_device_by_filter()` instead — using the built-in would silently break every
  partial-name lookup.
- `find_device_by_filter()` resolves as soon as a device matches rather than
  sleeping for the full timeout. A device that advertises immediately is found in
  milliseconds instead of after the entire `--scan-timeout`.

## Troubleshooting

**`BleakError: BleakClient requires a connected BleakDevice` / nothing is found.**
Check the device is actually advertising. Many peripherals stop advertising once
they have a connection, so close any app that is connected to it, or power-cycle it.

**No output at all, no permission prompt.** macOS has Bluetooth access switched off
for your terminal. Check **System Settings → Privacy & Security → Bluetooth** and
make sure your terminal (Terminal, iTerm, VS Code) is listed and enabled.

**`BleakError: Services discovery failed` / connects then drops.** The peripheral
refused service discovery. Some cheap devices need a moment after connect — retry,
or use `--connect-timeout 60`.

**Reads return empty or `Insufficient Authentication`.** The characteristic requires
bonding or encryption, and macOS will not let you force that pairing. `enum_ble.py`
prints the GATT error code when the peripheral answers with one.

**`read_gatt_char` hangs.** Raise `--connect-timeout`, or narrow with
`--filter-uuid` to avoid reading a characteristic that never answers.

**Everything is slow on first run.** The first connection to a peripheral pays for
CoreBluetooth service discovery and the system Bluetooth permission check. Later runs
are faster.

## Contributing

Pull requests are welcome.

- Keep each script runnable on its own with no arguments beyond its own flags.
- Shared helpers belong in `ble_common.py`; do not copy them between scripts.
- Verify changes against the installed bleak, not an assumed API:
  ```bash
  python3 -m py_compile *.py
  python3 scan_ble.py --help
  ```
- If you change GATT parsing or UUID handling, the pure functions in
  `ble_common.py` (`short_uuid`, `uuid16_from_128`, `parse_advertisement_data`) are
  testable without a Bluetooth adapter. Please keep them free of I/O.

## License

[MIT](LICENSE)