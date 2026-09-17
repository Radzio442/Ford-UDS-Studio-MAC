# Ford UDS Studio

Ford diagnostic / UDS utility with support for VBF files, flashing, CAN monitoring and the **FordLink / RED UCDS CH-3.2** serial transport.

## RED UCDS / CH-3.2 firmware

A ready-to-flash combined Intel HEX image is included here:

`firmware/RED_UCDS/bl_ch_combined.hex`

The image contains both the bootloader and the CH application:

- bootloader: `0x08000000` – `0x08002733`
- application: `0x08004000` – `0x0800813F`
- embedded USB strings: `STMicroelectronics`, `STM32 Virtual COM Port`
- embedded device identifier: `CH-3.2`
- SHA-256: `56c62c69dcdecffb486e908e68ad46ec01833149de34f504507e19a05cc9d5e5`

The FordLink backend in this repository is written for the same protocol. The source explicitly describes the adapter as **CH-3.2/F105**, uses USB CDC serial at **1,000,000 baud**, and supports CAN1/CAN2.

See [`firmware/RED_UCDS/README.md`](firmware/RED_UCDS/README.md) for flashing notes and the SWD pinout photo.

## Build

For macOS, see [`BUILD_MACOS.md`](BUILD_MACOS.md).

## Repository notes

Generated `dist/` and `build/` trees are intentionally excluded from this GitHub-ready package. Build them locally when required.

## License

See [`LICENSE`](LICENSE).
