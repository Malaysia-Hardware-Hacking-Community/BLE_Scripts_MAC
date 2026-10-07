# Changelog

All notable changes to WAMBLE are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it starts
tagging releases.

## [Unreleased]

### Added

- `scan_ble` can write results as CSV with `--csv PATH`, one row per device,
  alongside the existing `--write-to` JSON export. The two options can be given
  together and share the same per-device fields (address, name, RSSI, local
  name, advertised service UUIDs, manufacturer data, service data).

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
