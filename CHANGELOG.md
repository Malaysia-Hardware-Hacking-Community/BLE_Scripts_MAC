# Changelog

All notable changes to WAMBLE are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it starts
tagging releases.

## [Unreleased]

### Added

- `wamble-pair`: pair or unpair a device via the OS. On Windows it uses the WinRT
  pairing API (`bleak.pair()`/`unpair()`); on macOS, which has no explicit pairing
  API, it triggers CoreBluetooth's auto-pairing by reading an encryption-protected
  characteristic given with `--char`, and directs you to System Settings for
  unpairing. WAMBLE does not implement SMP itself (no OS exposes the raw channel to
  apps on the target platforms); it drives the OS pairing and reports the outcome.
  Tier 3.
- `wamble-range`: track one device's RSSI live as a "hotter / colder" finder, with
  a sparkline of recent samples, a coarse signal label, a warmer/cooler trend, and
  a rough log-distance estimate. Reads the per-advertisement RSSI the scanner
  already reports, so it behaves the same on macOS and Windows. Tier 3.
- `wamble-bench`: benchmark a device's connection performance. Times connection
  establishment over repeated samples (min/median/mean/max), reports connect
  reliability and the negotiated ATT MTU, and measures read and notification
  throughput over a window. Uses only cross-platform `bleak` calls, so it behaves
  the same on macOS and Windows. First feature of Tier 3 (see `docs/ROADMAP.md`).
- `docs/ROADMAP.md`: the living 4-tier feature plan (shipped Tiers 1-2, proposed
  Tier 3, and the out-of-scope Tier 4 boundary, including why BlueZ-style explicit
  pairing needs a bring-your-own-radio backend on macOS/Windows).

## [0.1.3] - 2026-10-08

### Fixed

- All text files are now read and written as UTF-8 explicitly. On Windows (a
  target platform) the default encoding is cp1252, which cannot decode some bytes
  the TUI launcher contains (the `←` glyph) and would mangle non-ASCII device
  names in exported CSV/JSON or a batch script. This had broken the Windows CI
  run. Every `open()` in the toolkit and tests now passes `encoding="utf-8"`.
- The TUI launchers (`ble_tui.sh`, `ble_tui.ps1`) showed a stale `v0.1.2` banner
  because the version was hardcoded in four places and drifted. The version now
  has a single source of truth, `wamble.__version__`: `pyproject.toml` reads it
  dynamically, and both launchers read it at runtime, so a release only ever
  edits one file. A test guards against reintroducing a hardcoded version.
- Reading a characteristic value now shows honest, lossless interpretation lines
  under the hex dump. A non-text value is reported as `Int:` for a 1/2/4/8-byte
  little-endian scalar or `Data: binary data, N bytes` otherwise, and whenever it
  contains readable ASCII an `ASCII:` hexdump gutter surfaces it, so text buried
  in a binary field (for example a firmware value `00 00 41 01 33 33 34 00 00`
  shows `..A.334..`) is no longer hidden behind a "binary data" summary. Text
  decoding is stricter too: a value only counts as `Text:` when every byte is
  printable, so `00 64 00` is no longer mis-decoded to an invisible-NUL `"d"`.
  Affects `wamble-enum`, `wamble-gatt`, `wamble-device-info` and the CTF reads.
- `wamble-gatt`'s `read` now prints which characteristic it read (UUID, assigned
  name and value handle) before the value, so reading a handle that resolves to a
  different characteristic than expected (e.g. the binary PnP ID rather than the
  Firmware Revision String) is obvious instead of an unexplained hex dump.

### Added

- The TUIs (`ble_tui.sh`, `ble_tui.ps1`) now save scans as timestamped JSON files
  in a `scans/` directory inside the project instead of a hidden temp dir, so
  results are easy to find and reuse. The bash device picker reads the most recent
  scan. Both TUIs gain a "Delete saved scans" action to clear the directory.
  `scans/` is gitignored.
- Learned-identity cache. When `wamble-enum` connects to a device and reads its
  real name from the Device Information Service, it now remembers that name
  against the device address (`identities.json`, next to `targets.json`). A later
  `wamble-scan` or `wamble-watch` reads it back, so a device that advertises no
  name is labelled with what you enumerated it as instead of repeating
  `(unnamed)`. The advertised name always wins when present; the learned name
  only fills the blank. Overridable with `$WAMBLE_IDENTITIES`. The TUI device
  picker (`ble_tui.sh`) resolves the same way and re-reads the cache each time it
  is shown, so after you enumerate an unnamed device its row updates without a
  re-scan. The scan JSON gains a `display` field carrying this resolved label
  (the raw `name` field is unchanged).
- `wamble-profile`: subscribe to and decode a standard SIG measurement profile,
  the way `wamble-battery` reads one characteristic. Handles Heart Rate
  Measurement (`0x2A37`), Temperature Measurement (`0x2A1C`, Health Thermometer)
  and CSC Measurement (`0x2A5B`), decoding each flags-driven layout (including
  the IEEE-11073 float for temperature) and printing a reading per update.
  Auto-detects the profile when `-p` is omitted.
- `wamble-batch`: run a script of GATT commands non-interactively, from a file
  or stdin, against one connection. It uses exactly the same commands as
  `wamble-gatt` (reusing its dispatcher), plus a `wait <seconds>` line for
  holding the link open, for example to capture notifications after `notify`.
- Advertisement identification. `wamble-scan` and `wamble-watch` now say what an
  unnamed device actually is: they decode the manufacturer company ID to a vendor
  name (a curated subset of the Bluetooth SIG list, e.g. Apple, Samsung, Google,
  Microsoft, Xiaomi), recognise iBeacon and Eddystone frames, and fill a
  `(unnamed)` row with a derived identity such as `· Apple · Nearby Info`. For
  Apple devices it decodes the Continuity message type (Nearby, AirDrop, Handoff,
  Find My, Proximity Pairing, ...), and for Proximity Pairing it names the
  accessory model from a curated table (AirPods, AirPods Pro, Beats, ...). A
  passive scan cannot reveal a phone's exact model (iPhone 15 vs 13); that is not
  broadcast. The advertised-services column now names known UUIDs (16-bit and
  128-bit alike), and the manufacturer column names the vendor. New
  `wamble.identify` module.
- `wamble-enum` now prints a prominent `Device:` line with the manufacturer and
  model read from the Device Information Service (0x180A) when the device exposes
  it, which is the reliable place a real model string lives (phones do not
  expose it to an unpaired central).
- `wamble-notify-log`: subscribe to a device's notify/indicate characteristics
  and log each notification to CSV with timestamps (`timestamp, elapsed,
  characteristic, handle, length, value_hex, text`). Subscribes to all
  notifiable characteristics by default, or named ones with repeated `-c`, and
  runs until Ctrl-C or `--timeout`.
- `wamble-adv-log`: log BLE advertisements to CSV over time, one timestamped row
  per sighting (`timestamp, address, name, rssi, service_uuids, manufacturer`),
  until Ctrl-C or `--timeout`. Writes to a file with `-o` or to stdout for
  piping (status stays on stderr), with `--name`/`--min-rssi` filters and a
  per-device `--min-interval` throttle.
- `wamble-export`: dump a device's full GATT tree (services, characteristics,
  descriptors, properties) to stable, sorted JSON with `-o`, and compare two
  snapshots offline with `--diff OLD NEW`. The diff reports services and
  characteristics added or removed, descriptors added or removed, and
  characteristic properties that changed, so a firmware update or a difference
  between two units is easy to spot.

## [0.1.2] - 2026-10-07

### Added

- A `wamble-targets` console command for the device-target profile manager, so
  it is a first-class command alongside the other tools (previously it was only
  runnable as `python -m wamble.targets`).

### Changed

- Reorganised the repository into a `src/` layout. The toolkit is now the
  `wamble` package (`src/wamble/`, one module per tool), the exploit
  demonstrations live in `wamble.exploits`, and the community-health docs moved
  to `.github/` with reference docs under `docs/`. Tools now run as the
  installed `wamble-*` commands or `python -m wamble.<tool>` rather than
  `python3 <script>.py`. The menu front-ends and tests were updated to match.

## [0.1.1] - 2026-10-07

### Added

- Human-readable Bluetooth SIG and vendor names now appear next to UUIDs. The
  GATT enumeration (`enum_ble`), the interactive client (`gatt_cli` services,
  characteristics and descriptors tables) and `gatt_find` show the assigned name
  for a UUID (for example `2a19` as "Battery Level" and the `2902` descriptor as
  "Client Characteristic Configuration"). The descriptors table gained a Name
  column, and `gatt_find` now reports the compact UUID and the name.
- `uuid_name()` in `ble_common`, a single wrapper over bleak's assigned-numbers
  table that returns a caller-supplied placeholder instead of the literal
  "Unknown" for a UUID with no known name.
- `scan_ble` can write results as CSV with `--csv PATH`, one row per device,
  alongside the existing `--write-to` JSON export. The two options can be given
  together and share the same per-device fields (address, name, RSSI, local
  name, advertised service UUIDs, manufacturer data, service data).
- The project can be installed (`pip install .`) to expose each tool as a
  `wamble-*` console command: `wamble-scan`, `wamble-watch`, `wamble-enum`,
  `wamble-gatt`, `wamble-find`, `wamble-battery`, `wamble-device-info`,
  `wamble-mtu`, `wamble-params` and `wamble-ctf`. Each runs the same code as its
  script, which still runs directly with no install step.
- `pyproject.toml` now carries the packaging metadata (`[project]`,
  `[project.scripts]`, `[build-system]`) and `wamble_cli.py` holds the thin
  entry-point wrappers.
- Saved device-target profiles. `ble_targets.py` saves short aliases for a
  device name or address (`add`, `list`, `remove`, `path`), and every connecting
  tool then accepts `@alias` in place of the full identifier. This is handy on
  macOS, where the address is a long per-host UUID that changes between reboots.
  Aliases are resolved in `ble_common.find_device()`, so all tools pick them up.
- `targets_path()`, `load_targets()`, `save_targets()` and `resolve_target()` in
  `ble_common`. The profiles file location honours `$WAMBLE_TARGETS` and
  otherwise lives under the platform config directory.

### Fixed

- Attribute tables no longer print the literal word "Unknown" for a UUID with no
  assigned name; they show the normal placeholder instead.

## [0.1.0] - 2026-10-07

### Added

- A wombat mascot and the toolkit version (`v0.1.0`) in the banner of both menu
  front-ends (`ble_tui.sh` and `ble_tui.ps1`).
- The menu now centers itself and scales its panel width to the terminal, and
  drops the mascot for a one-line banner on a small window, so it reads well from
  narrow to wide terminals.

- GitHub Actions CI that runs the test suite on Linux, macOS, and Windows across
  Python 3.11 to 3.13, plus a strict quality job: ruff (redundancy,
  simplifications, slow patterns, import order, complexity), ruff format, vulture
  (dead code), and pylint duplicate-code (copy-paste detection).
- `pyproject.toml` holding the lint and duplicate-code configuration.
- `add_connection_args()` in `ble_common`, so every connecting tool shares one
  definition of `--scan-timeout` and `--connect-timeout`.
- Project community files: `LICENSE` (MIT), `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, `GOVERNANCE.md`, `SUPPORT.md`, a changelog,
  and GitHub issue and pull request templates.
- `GATT-CLI-CHEATSHEET.md`, a reference for the `gatt_cli` commands and the LED
  control payloads.
- Device picker in the text UI, so scanned devices can be chosen by number.
- Keepalive option in `gatt_cli` to hold a connection open while idle.
- `reconnect` and `help` commands in the `gatt_cli` prompt.

### Fixed

- A read or write that a device refuses is now reported as a plain reason
  instead of a raw protocol error. When a device returns an ATT error (for
  example a TV that answers a read with code `0xF7` because it wants pairing
  first), the tools print "device declined, likely needs pairing (0xF7)" in
  muted text rather than a red "GATT read failed" with an exception dump. This
  covers `enum_ble`, `read_device_info`, `gatt_params`, `gatt_cli`, `ble_ctf`,
  and the recon scripts in `BLE-Exploits`.
- `ble_ctf` no longer lets a refused read or write escape as a Python traceback;
  it prints the plain reason and disconnects cleanly.
- A failed connection now explains itself. A timeout says so and names the
  likely cause instead of printing `TimeoutError()`.
- `ble_posture_scan` now counts a refused read by its ATT error code, so it
  recognises the vendor "needs pairing" codes (such as macOS reporting `0xF7`)
  that a text match on the message would miss.
- `gatt_cli` no longer hangs on Ctrl-C and no longer leaves the terminal in an
  unusable state. The prompt now uses the canonical line discipline so a typed
  Ctrl-C raises an interrupt, and terminal settings are restored on exit.
- Added a clean Ctrl-C handler to `gatt_find`, `gatt_mtu`, `gatt_battery`,
  `read_device_info`, and `gatt_params`.
- `scan_ble` no longer prints "Scan interrupted" after a normal timed scan.
- `gatt_params` now reads the correct Peripheral Preferred Connection Parameters
  characteristic (0x2A04) instead of the wrong attribute.
- Scan output shows full device addresses and untruncated names so they can be
  copied back in as a target.

### Changed

- Removed dead and duplicated code across the toolkit, including an unused UUID
  table and a repeated property formatter that now lives in one place.
- `services`, `characteristics`, and `descriptors` in `gatt_cli` now show
  distinct output.
