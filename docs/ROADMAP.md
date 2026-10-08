# WAMBLE Roadmap

This is the living feature plan for WAMBLE. Features are grouped into tiers by how
feasible they are to build on the libraries WAMBLE stands on (chiefly `bleak`,
which is a BLE **central** on macOS CoreBluetooth and Windows WinRT) and by their
value and risk. Lower tiers are easier and land first; higher tiers are harder or
need capabilities `bleak` does not expose on the target platforms.

The ranking criteria:

- **Feasibility**: can it be built with `bleak` on macOS and Windows without a
  custom adapter, kernel access, or peripheral-role support?
- **Value**: does it add a capability the toolkit does not already have?
- **Risk**: is it security-sensitive? If so it is gated and lives in
  `wamble.exploits`, for authorized, own-device use only.

## Tier 1 - shipped (v0.1.1)

Easiest, highest-confidence additions.

- **uuid-name-resolution**: resolve Bluetooth SIG and vendor UUID names in GATT
  output (`wamble.common.uuid_name`).
- **scan-csv-export**: CSV/JSON export from `wamble-scan`.
- **console-scripts**: installable `wamble-*` commands.
- **target-profiles**: saved device-target aliases (`@alias`) and the
  `wamble-targets` manager.

## Tier 2 - shipped (v0.1.2 / v0.1.3)

Moderate additions, built on Tier 1.

- **gatt-export-diff** (`wamble-export`): GATT tree snapshot to JSON plus an
  offline diff of two snapshots.
- **adv-logger** (`wamble-adv-log`): timestamped advertisement logging to CSV.
- **notify-logger** (`wamble-notify-log`): notification/indication logging to CSV.
- **adv-identify** (`wamble.identify`): name an unnamed device from its
  advertisement (vendor company ID, iBeacon/Eddystone, Apple Continuity message
  type, accessory model), surfaced in `wamble-scan`/`wamble-watch`.
- **gatt-batch-runner** (`wamble-batch`): run a script of GATT commands.
- **sig-profile-readers** (`wamble-profile`): decode Heart Rate, Health
  Thermometer, and CSC measurement profiles.
- Refinements in v0.1.3: learned-identity cache (enum teaches scan what a device
  is), lossless value decoding (ASCII gutter), single-source version, project
  `scans/` directory with a clear action, and UTF-8 everywhere.

## Tier 3 - proposed (next)

Harder but feasible, and chosen so that **every one behaves the same on macOS and
Windows** (WAMBLE's whole point). Anything that would work on only one platform is
pushed to Tier 4. Each is net-new capability, not a variation of an existing tool.

1. **connection-benchmark** (`wamble-bench`) - diagnostics.
   Measure connection establishment time, the negotiated ATT MTU, and read /
   notification throughput over repeated samples, then report min/median/max and
   reconnect reliability. Pure timing around `bleak` calls that behave the same on
   both platforms; no new permissions. *Cross-platform, low risk. Recommended first.*

2. **rssi-monitor** (`wamble-range`) - live signal tracking.
   Follow one device's RSSI over time with a sparkline and a rough path-loss
   distance estimate, as a "hotter / colder" finder for locating hardware. Uses
   the scanner's per-advertisement RSSI, which `bleak` exposes identically on both
   platforms. *Cross-platform, low risk.*

3. **pairing-helper** (`wamble-pair`) - pairing and bonding.
   Pair a device and report its bond / encryption state. WAMBLE does not ship its
   own pairing (SMP) implementation and cannot: neither macOS nor Windows exposes
   the raw SMP / L2CAP channel or HCI to an app, so the OS Bluetooth stack always
   performs the key exchange (on Windows, too - `bleak.pair()` just calls the WinRT
   pairing API, which delegates to the OS). The tool instead drives that OS pairing
   through whatever each platform offers and reports the result: on Windows via the
   explicit WinRT API (`bleak.pair()`), and on both platforms by reading an
   encryption-required characteristic, which makes the OS initiate pairing and lets
   us confirm it succeeded. Programmatic unpair is Windows-only (`bleak.unpair()`);
   on macOS unpairing is done in System Settings, which the tool states plainly.
   *Pairing is cross-platform; unpair has one documented platform asymmetry.*

4. **gatt-fuzzer** (`wamble.exploits.gatt_fuzz`) - authorized robustness testing.
   Send boundary and malformed values (empty, maximum length, bit-flipped,
   wrong-width) to a device's writable characteristics and watch for errors,
   disconnects, or hangs. Uses `write_gatt_char`, identical on both platforms.
   Security-sensitive, so it lives in `wamble.exploits`, is gated behind the same
   authorized / own-device confirmation as the other PoCs, and defaults to a dry
   run. *Cross-platform, hardest in this tier, highest risk.*

## Tier 4 - out of scope for now

Not feasible with `bleak` as a central on macOS/Windows without extra hardware or
a different stack. Recorded so the boundary is explicit.

- **peripheral / beacon advertising and spoofing**: `bleak` is central-only on
  the target platforms; it cannot advertise or emulate a peripheral.
- **raw HCI passive sniffing**: needs a sniffer radio (nRF, Ubertooth) or raw HCI
  access, not the OS GATT API `bleak` wraps.
- **OTA / DFU firmware update**: device and vendor specific; out of a generic
  toolkit's scope.
- **active man-in-the-middle**: requires peripheral role plus a second radio.

### Bring-your-own-radio backend (enables the rest of Tier 4)

The reason the items above are blocked is the same: macOS CoreBluetooth and Windows
WinRT expose only GATT to apps, not the raw HCI / L2CAP / SMP sockets that BlueZ and
`gatttool` rely on for explicit pairing, L2CAP CoC, and low-level control. Linux
hands those sockets to user space; macOS and Windows do not.

The way to get that control on all three platforms is a second backend: a user-space
BLE host stack (HCI -> L2CAP -> ATT/SMP) driving an **external USB BLE controller**
over an HCI transport, bypassing the OS stack. Google's **Bumble** (Python,
Apache-2) is such a stack and runs on macOS/Windows/Linux. With a USB dongle it would
unlock explicit **pairing/SMP** parity with `gatttool`, **L2CAP CoC**, and raw
observation.

- *Cost*: requires a USB BLE dongle (the built-in Mac/Windows radio is not available
  as an HCI transport), and it is a whole new backend alongside `bleak`, not a patch.
- *Payoff*: true independence from the OS pairing limitations.
- This is the correct home for a "proper, own pairing API". The Tier 3
  `wamble-pair` deliberately does not attempt it; it drives the OS pairing instead,
  so it needs no extra hardware.

## Workflow

Within a tier, each feature is built on its own branch stacked on the previous
one, and the whole tier is merged to `main` at the end (one release), rather than
merging per feature.
