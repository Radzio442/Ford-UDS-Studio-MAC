# Ford UDS Studio 2.11.1 — macOS Release

## Najprościej

Kliknij dwukrotnie:

```text
build_and_open.command
```

Jeśli macOS zablokuje uruchomienie, w Terminalu wykonaj:

```bash
cd ~/Desktop/Ford_UDS_Studio_2_11_1_macOS_Release_Builder
chmod +x build_macos_release.sh build_and_open.command
./build_macos_release.sh
```

Po zakończeniu powstaną:

```text
dist/Ford UDS Studio.app
Ford_UDS_Studio_2.11.1_macOS.dmg
```

Builder dołącza:

- GS_USB / python-can,
- libusb / PyUSB,
- FordLink CAN1 i CAN2,
- pyserial,
- katalog `config`,
- pakiety `ford`, `studio`, `fordlink`,
- ikonę `MyIcon.icns`.

Aplikacja otrzymuje podpis ad-hoc. Do publicznej dystrybucji można później użyć certyfikatu Developer ID i notaryzacji.
