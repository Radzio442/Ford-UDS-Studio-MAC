# Ford UDS Studio for macOS

[![Latest Release](https://img.shields.io/github/v/release/Radzio442/Ford-UDS-Studio-MAC?display_name=tag&sort=semver)](https://github.com/Radzio442/Ford-UDS-Studio-MAC/releases/latest)
[![macOS](https://img.shields.io/badge/macOS-13%2B-black?logo=apple)](https://github.com/Radzio442/Ford-UDS-Studio-MAC)
[![Python](https://img.shields.io/badge/Python-3.13-blue?logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Ford diagnostic and UDS utility for macOS with VBF support, flashing tools, CAN monitoring, FordLink transport, and RED UCDS / CH-3.2 support.

## Download

### Latest stable release — v2.11.3

**[Download Ford_UDS_Studio_2.11.3_macOS.dmg](https://github.com/Radzio442/Ford-UDS-Studio-MAC/releases/download/v2.11.3/Ford_UDS_Studio_2.11.3_macOS.dmg)**

[View all releases](https://github.com/Radzio442/Ford-UDS-Studio-MAC/releases)

```text
File:    Ford_UDS_Studio_2.11.3_macOS.dmg
Size:    55.61 MiB
SHA-256: 52e172f83bd419134293ed6bcdd6adf75526332eec8f24ab37865c09b7ca7988
```

## What's new in v2.11.3

- restored verified legacy SecurityAccess magic values
- IPC `0x720`, level `0x01` uses `0x4A7722`
- ACM `0x727`, level `0x01` uses `0x123BF9`
- APIM `0x7D0`, level `0x01` uses `0x123BF9`
- specific F111 rules no longer get overridden by generic wildcard rules
- added `ford/security.py`
- added `docs/SECURITY_ACCESS.md`
- fixed executable permissions for macOS build scripts

## Features

- Ford UDS diagnostic communication
- VBF parsing and utility tools
- ECU flashing support
- CAN communication and monitoring
- FordLink transport
- RED UCDS / CH-3.2 support
- CAN1 / CAN2 support
- USB CDC serial communication
- SecurityAccess seed-key support
- F111 hardware-aware SecurityAccess profiles
- macOS application build and DMG release workflow

## SecurityAccess

Ford UDS Studio supports the legacy Ford 3-byte SecurityAccess seed/key mechanism.

For known ECUs, the application uses verified ECU/level-specific magic values. More specific F111 hardware rules can be used where available, while generic wildcard rules are treated only as a fallback.

Current verified examples:

| ECU | Module | Level | Magic |
|---|---|---:|---:|
| `0x720` | IPC | `0x01` | `0x4A7722` |
| `0x727` | ACM | `0x01` | `0x123BF9` |
| `0x7D0` | APIM / SYNC | `0x01` | `0x123BF9` |

More details:

[`docs/SECURITY_ACCESS.md`](docs/SECURITY_ACCESS.md)

## RED UCDS / CH-3.2

The repository includes a ready-to-flash combined Intel HEX image for the RED UCDS / CH board:

```text
firmware/RED_UCDS/bl_ch_combined.hex
```

Firmware SHA-256:

```text
56c62c69dcdecffb486e908e68ad46ec01833149de34f504507e19a05cc9d5e5
```

### Flash layout

| Region | Address range | Data size |
|---|---:|---:|
| Bootloader | `0x08000000` – `0x08002733` | 10,036 bytes |
| CH application | `0x08004000` – `0x0800813F` | 16,704 bytes |

The gap between `0x08002734` and `0x08003FFF` is not programmed by the combined HEX.

The CH application contains:

```text
CH-3.2
STMicroelectronics
STM32 Virtual COM Port
```

The FordLink backend is intended for the same **CH-3.2 / STM32F105** protocol and uses USB CDC serial communication at **1,000,000 baud**.

Full firmware notes:

[`firmware/RED_UCDS/README.md`](firmware/RED_UCDS/README.md)

## RED UCDS SWD pinout

![RED UCDS SWD pinout](docs/red_ucds_swd.jpg)

| Board marking | Function |
|---|---|
| `CLK` | SWCLK |
| `DIO` | SWDIO |
| `BOOT` | BOOT0 |
| `GND` | Ground |
| `5V` | Board supply |

For normal SWD programming use **SWCLK, SWDIO and GND**, plus suitable board power for your setup.

## Flashing RED UCDS firmware

Example with STM32CubeProgrammer:

```bash
STM32_Programmer_CLI \
  -c port=SWD \
  -w firmware/RED_UCDS/bl_ch_combined.hex \
  -v \
  -rst
```

The Intel HEX contains absolute flash addresses, so a separate start address is not required.

> Before flashing, keep a backup of the original MCU flash. Verify the exact STM32F105 device fitted to your board before changing option bytes or performing a full-chip erase.

## Repository structure

```text
Ford-UDS-Studio-MAC/
├── README.md
├── BUILD_MACOS.md
├── VERSION
├── requirements.txt
├── ford_uds_studio.py
├── config/
├── ford/
│   ├── ecu_database.py
│   ├── security.py
│   ├── uds.py
│   └── ...
├── fordlink/
├── studio/
├── tools/
├── docs/
│   ├── SECURITY_ACCESS.md
│   └── red_ucds_swd.jpg
├── firmware/
│   └── RED_UCDS/
│       ├── README.md
│       └── bl_ch_combined.hex
└── OBD_CH_GS/
    ├── bl.bin
    ├── ch.bin
    └── gs.bin
```

Generated `build/`, `dist/`, and `.dmg` files are intentionally excluded from the Git repository. Release binaries are published under **GitHub Releases**.

## Build on macOS

See:

[`BUILD_MACOS.md`](BUILD_MACOS.md)

Typical setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Build and open:

```bash
chmod +x build_and_open.command build_macos_release.sh
./build_and_open.command
```

Build release only:

```bash
./build_macos_release.sh
```

## Useful tools

The repository also contains standalone utilities including:

```text
vbfextract.py
vbfmake.py
vbflasher.py
vbflasher2.py
tools/fordlink_probe.py
tools/fordlink_uds_probe.py
```

## Updating the repository

```bash
git add .
git commit -m "Update Ford UDS Studio"
git push
```

Large application binaries such as `.dmg` files should be uploaded to **GitHub Releases**, not committed directly to the repository.

## License

MIT
