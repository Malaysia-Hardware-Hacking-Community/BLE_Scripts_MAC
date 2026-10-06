# Changelog

All notable changes to WAMBLE are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it starts
tagging releases.

## [Unreleased]

### Added

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
