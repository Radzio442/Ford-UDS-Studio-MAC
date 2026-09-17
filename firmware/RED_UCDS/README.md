# RED UCDS / CH-3.2 firmware

This directory contains the combined firmware image for the red UCDS/CH board used by Ford UDS Studio.

## File

- `bl_ch_combined.hex`
- format: Intel HEX
- size: 63,560 bytes
- SHA-256: `56c62c69dcdecffb486e908e68ad46ec01833149de34f504507e19a05cc9d5e5`

### Programmed address ranges

| Region | Address range | Data size |
|---|---:|---:|
| Bootloader | `0x08000000` – `0x08002733` | 10,036 bytes |
| CH application | `0x08004000` – `0x0800813F` | 16,704 bytes |

The gap from `0x08002734` to `0x08003FFF` is intentionally not programmed by this HEX.

## Why this is the CH firmware

The application contains the ASCII identifier:

`CH-3.2`

It also contains the USB CDC descriptors:

- `STMicroelectronics`
- `STM32 Virtual COM Port`

The Ford UDS Studio source matches this device: `fordlink/bus.py` explicitly says the transport was proven on **CH-3.2/F105 firmware**, while `studio/backend.py` detects it as a USB CDC serial device.

## SWD / boot pads

![RED UCDS SWD pinout](../../docs/red_ucds_swd.jpg)

Pads shown in the photo:

- `CLK` = SWCLK
- `DIO` = SWDIO
- `BOOT` = BOOT0
- `GND` = ground
- `5V` = board supply

Use an ST-LINK (or another compatible SWD programmer) with **SWCLK, SWDIO and GND**. Power the board appropriately for your setup. Do not feed conflicting power from two sources at once.

## Flashing with STM32CubeProgrammer

Example:

```bash
STM32_Programmer_CLI -c port=SWD -w firmware/RED_UCDS/bl_ch_combined.hex -v -rst
```

The HEX already carries absolute flash addresses, so no manual start address is required.

## Hardware note

The photographed MCU marking is an STM32F105 in LQFP64. Verify the exact device suffix on your own board before changing option bytes or performing a full-chip erase.

## Recovery

Keep a full readout of the original MCU flash before programming a modified image. This repository image is intended for the CH-3.2/F105 RED UCDS hardware only.
