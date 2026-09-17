from __future__ import annotations

import platform
import hashlib
import re
import subprocess
import threading
import can
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from ford.uds import Ecu, fixedbytes, keygen
from ford.ecu_database import get_ecu_name, get_security_definition, get_security_definition_for_part, find_matching_profile
from ford.vbf import Vbf

LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int, str], None]


@dataclass
class VbfEntry:
    path: Path
    vbf: Vbf

    @property
    def part_number(self) -> str:
        return str(self.vbf.header.get("sw_part_number", self.path.name))

    @property
    def kind(self) -> str:
        return str(self.vbf.header.get("sw_part_type", "UNKNOWN"))

    @property
    def ecu_id(self) -> int:
        return self.vbf.ecuid

    @property
    def is_jade(self) -> bool:
        return any(ds["addr"] in (0x30000000, 0x3FFFFFFC) for ds in self.vbf.data)


class StudioError(RuntimeError):
    pass


class FordBackend:
    def __init__(self, log: LogFn | None = None, progress: ProgressFn | None = None):
        self.log = log or print
        self.progress = progress or (lambda current, total, text: None)
        self.ecu: Ecu | None = None
        self.entries: list[VbfEntry] = []
        self.sbl: VbfEntry | None = None
        self.cancel_event = threading.Event()

    @staticmethod
    def detect_interfaces() -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        system = platform.system()
        if system == "Darwin":
            # FordLink / CH-3.2 uses USB CDC.
            try:
                import glob
                serial_ports = sorted(set(
                    glob.glob("/dev/cu.usbmodem*") +
                    glob.glob("/dev/cu.usbserial*")
                ))
                for port in serial_ports:
                    found.append((f"FordLink CAN1 — {port}", f"fordlink:{port}"))
                    found.append((f"FordLink CAN2 — {port}", f"fordlink1:{port}"))
            except Exception:
                pass

            # GS_USB channels are integer indexed in python-can.
            try:
                import usb.core
                devices = list(usb.core.find(find_all=True) or [])
                gs_candidates = [d for d in devices if getattr(d, "idVendor", None) is not None]
                for idx, _ in enumerate(gs_candidates[:8]):
                    found.append((f"GS_USB channel {idx}", str(idx)))
            except Exception:
                pass
            if not found:
                found.append(("GS_USB channel 0", "0"))
        elif system == "Linux":
            try:
                output = subprocess.check_output(["ip", "-o", "link", "show"], text=True)
                for line in output.splitlines():
                    match = re.search(r"\d+:\s+(can\d+):", line)
                    if match:
                        name = match.group(1)
                        found.append((f"SocketCAN {name}", name))
            except Exception:
                pass
            if not found:
                found.append(("SocketCAN can0", "can0"))
        else:
            found.append(("GS_USB channel 0", "0"))
        return found

    def load_files(self, paths: Iterable[str | Path]) -> list[VbfEntry]:
        entries: list[VbfEntry] = []
        for raw in paths:
            path = Path(raw).expanduser().resolve()
            if not path.is_file():
                raise StudioError(f"Nie znaleziono pliku: {path}")
            vbf = Vbf(str(path))
            entries.append(VbfEntry(path, vbf))
        if not entries:
            raise StudioError("Nie wybrano plików VBF.")
        ecu_ids = {e.ecu_id for e in entries}
        if len(ecu_ids) != 1:
            raise StudioError("Pliki VBF dotyczą różnych adresów ECU.")
        self.entries = entries
        self.sbl = next((e for e in entries if "SBL" in e.kind.upper() or "14C025" in e.part_number), None)
        return entries

    def connect(self, interface: str, ecu_id: int | None = None) -> None:
        if self.ecu is not None:
            self.disconnect()
        target = ecu_id if ecu_id is not None else (self.entries[0].ecu_id if self.entries else None)
        if target is None:
            raise StudioError("Brak adresu ECU. Wczytaj VBF lub wpisz adres ręcznie.")
        self.ecu = Ecu(can_interface=interface, ecuid=target)
        self.log(f"[+] Połączono z interfejsem {interface}, ECU 0x{target:03X} — {get_ecu_name(target)}")

    def disconnect(self) -> None:
        if self.ecu is not None:
            self.ecu.close()
            self.ecu = None
            self.log("[+] Interfejs CAN zamknięty")

    def read_info(self) -> dict[str, str]:
        if self.ecu is None:
            raise StudioError("Brak połączenia z ECU.")
        self.ecu.UDSDiagnosticSessionControl(0x01)
        time.sleep(0.4)
        def text_did(did: list[int]) -> str:
            data = self.ecu.UDSReadDataByIdentifier(did)
            return data.decode("utf-8", errors="replace").strip("\x00") if data else "niedostępne"
        return {
            "Hardware": text_did([0xF1, 0x11]),
            "Part number": text_did([0xF1, 0x13]),
            "Strategy": text_did([0xF1, 0x88]),
            "Calibration": text_did([0xF1, 0x24]),
            "CVN": self.ecu.getCVN() if self.ecu else "niedostępne",
        }

    def uds_request(self, payload: bytes) -> bytes:
        if self.ecu is None:
            raise StudioError("Brak połączenia z ECU.")
        self.ecu.send(bytearray(payload))
        result = self.ecu.recv()
        return bytes(result or b"")

    def _loaded_part_numbers(self) -> list[str]:
        return [entry.part_number for entry in self.entries if entry.part_number]

    def _security_for_loaded_files(self, level: int) -> tuple[dict, str | None]:
        if self.ecu is None:
            raise StudioError("Brak połączenia z ECU.")

        # Najpierw szukamy profilu szczegółowego po numerach wszystkich
        # wczytanych VBF (np. GT4T). Kolejność plików nie ma znaczenia.
        for part_number in self._loaded_part_numbers():
            profile = find_matching_profile(self.ecu.ecuid, part_number)
            if profile:
                security = get_security_definition_for_part(
                    self.ecu.ecuid, level, part_number
                )
                if security:
                    profile_name = str(
                        profile.get("name") or profile.get("id") or part_number
                    )
                    return security, profile_name

        # Brak profilu szczegółowego: używamy domyślnego wpisu ECU.
        # Poprzednio ta linia omyłkowo wywoływała ponownie tę samą metodę,
        # powodując RecursionError po około 1000 wywołaniach.
        security = get_security_definition(self.ecu.ecuid, level)
        if not security:
            raise StudioError(
                f"Brak definicji Security Access dla ECU 0x{self.ecu.ecuid:03X}, "
                f"level 0x{level:02X}."
            )
        return security, None

    def unlock_test(self, level: int = 0x01) -> None:
        if self.ecu is None:
            raise StudioError("Brak połączenia z ECU.")

        self.log("[>] TX: 10 02 — sesja programowania")
        if not self.ecu.UDSDiagnosticSessionControl(0x02):
            raise StudioError("Brak pozytywnej odpowiedzi na 10 02 (timeout lub odrzucenie).")
        self.log("[<] RX: 50 02 — sesja programowania OK")

        # Ford IPC potrzebuje krótkiej przerwy po wejściu w sesję 0x02.
        # Oryginalny, działający vbflasher.py czeka tutaj 1 sekundę.
        self.log("[ ] Oczekiwanie 1,0 s na gotowość ECU...")
        time.sleep(1.0)

        self.log(f"[>] TX: 27 {level:02X} — żądanie seed")
        seed = self.ecu.UDSSecurityAccess(level)
        if not seed:
            # Jedna bezpieczna próba ponowienia — bez wysyłania błędnego klucza.
            self.log("[!] Brak seeda, ponawiam żądanie po 0,5 s...")
            time.sleep(0.5)
            seed = self.ecu.UDSSecurityAccess(level)
        if not seed:
            raise StudioError(f"Brak odpowiedzi seed dla SecurityAccess 0x{level:02X} po 2 próbach.")
        self.log("[<] Seed: " + " ".join(f"{b:02X}" for b in seed))

        security = get_security_definition(self.ecu.ecuid, level)
        if not security:
            raise StudioError(
                f"Brak definicji Security Access dla ECU 0x{self.ecu.ecuid:03X}, level 0x{level:02X}."
            )
        algorithm = security.get("algorithm")
        if algorithm != "ford_3byte":
            raise StudioError(
                f"Algorytm {algorithm!r} dla ECU 0x{self.ecu.ecuid:03X} nie jest jeszcze obsługiwany."
            )
        magic = int(security["magic"])
        key = keygen(seed, magic)
        self.log(f"[+] Magic bytes: 0x{magic:06X}")
        self.log("[>] Key: " + " ".join(f"{b:02X}" for b in key))
        if not self.ecu.UDSSecurityAccess(level + 1, key):
            raise StudioError("ECU odrzuciło klucz SecurityAccess.")
        self.log("[<] RX: 67 02 — Security Access OK")

    def _upload(self, entry: VbfEntry, base_done: int, total_bytes: int) -> int:
        assert self.ecu is not None
        fmt = int(entry.vbf.header.get("data_format_identifier", "0x00"), 16)
        done = base_done
        for ds in entry.vbf.data:
            if self.cancel_event.is_set():
                raise StudioError("Operacja przerwana przez użytkownika.")
            size, addr = ds["size"], ds["addr"]
            self.log(f"[ ] Download 0x{size:08X} -> 0x{addr:08X}")
            chunk_raw = self.ecu.UDSRequestDownload(addr=addr, size=size, fmt=fmt)
            if not chunk_raw:
                raise StudioError("RequestDownload odrzucone.")
            chunk = max(1, int(chunk_raw.hex(), 16) - 2)
            count = (size + chunk - 1) // chunk
            for index in range(count):
                if self.cancel_event.is_set():
                    raise StudioError("Operacja przerwana przez użytkownika.")
                part = ds["data"][index * chunk:(index + 1) * chunk]
                if not self.ecu.UDSTransferData((index + 1) % 256, part):
                    raise StudioError(f"TransferData nie powiódł się, blok {index + 1}/{count}.")
                done += len(part)
                self.progress(done, total_bytes, f"FLASH {entry.part_number}")
            if not self.ecu.UDSRequestTransferExit():
                raise StudioError("RequestTransferExit odrzucone.")
        return done

    def _erase(self, entry: VbfEntry) -> None:
        assert self.ecu is not None
        erase = entry.vbf.header.get("erase")
        if not erase:
            return
        if not isinstance(erase[0], list):
            erase = [erase]
        for start, length in erase:
            addr, size = int(start, 16), int(length, 16)
            self.log(f"[ ] Erase 0x{addr:08X}, 0x{size:X} bytes")
            if not self.ecu.erase(addr, size):
                raise StudioError("Kasowanie pamięci nie powiodło się.")

    def flash_all(self, interface: str) -> None:
        if not self.entries:
            raise StudioError("Najpierw dodaj pliki VBF.")
        self.cancel_event.clear()
        self.connect(interface)
        assert self.ecu is not None
        try:
            self.log("[+] Sesja programowania 0x02")
            if not self.ecu.UDSDiagnosticSessionControl(0x02):
                raise StudioError("Nie udało się rozpocząć sesji programowania.")
            time.sleep(1)
            security, profile_name = self._security_for_loaded_files(0x01)
            magic_override = int(security["magic"]) if security.get("algorithm") == "ford_3byte" else None
            if profile_name:
                self.log(f"[+] Profil Security: {profile_name}")
            ok, message = self.ecu.unlock(0x01, magic_override=magic_override)
            self.log(message)
            if not ok:
                raise StudioError(message)

            total_bytes = sum(ds["size"] for e in self.entries for ds in e.vbf.data)
            done = 0
            ordered = list(self.entries)
            if self.sbl is not None:
                ordered.remove(self.sbl)
                ordered.insert(0, self.sbl)

            for entry in ordered:
                is_sbl = entry is self.sbl
                self.log(f"\n[*] {'SBL' if is_sbl else entry.kind}: {entry.part_number}")
                if not is_sbl:
                    self._erase(entry)
                done = self._upload(entry, done, total_bytes)
                if is_sbl:
                    call = entry.vbf.header.get("call")
                    if not call or not self.ecu.SBLcall(int(call, 16)):
                        raise StudioError("Nie udało się uruchomić SBL.")
                else:
                    if not self.ecu.commit():
                        raise StudioError(f"Commit nie powiódł się dla {entry.part_number}.")
            self.progress(total_bytes, total_bytes, "FLASH zakończony")
            self.log("\n[+] Flashowanie zakończone pomyślnie")
        finally:
            self.disconnect()


    def read_ipc_eeprom(
        self,
        interface: str,
        output_path: str | Path,
        security_profile: str = "gm2t",
        address: int = 0x02000000,
        size: int = 0x1000,
    ) -> dict[str, str | int]:
        """Bezpieczny odczyt EEPROM IPC przez SBL i RequestUpload.

        Ta funkcja nie wysyła RoutineControl FF00, RequestDownload do EEPROM
        ani żadnych danych zapisu.
        """
        if self.sbl is None:
            raise StudioError("Dodaj właściwy SBL VBF dla GM2T (14C025) przed odczytem EEPROM.")
        if size != 0x1000:
            raise StudioError("Tryb GM2T dopuszcza wyłącznie EEPROM o rozmiarze 0x1000.")

        # Potwierdzony z logów GM2T profil loadera EEPROM.
        sbl_total = sum(ds["size"] for ds in self.sbl.vbf.data)
        call = self.sbl.vbf.header.get("call")
        if call is None:
            raise StudioError("SBL nie ma pola call w nagłówku VBF.")
        call_addr = int(call, 0) if isinstance(call, str) else int(call)
        if sbl_total != 0x35C or call_addr != 0x40003600:
            raise StudioError(
                "Nieprawidłowy SBL dla GM2T EEPROM. "
                f"Wczytano payload 0x{sbl_total:X}, call 0x{call_addr:08X}; "
                "wymagany payload 0x35C i call 0x40003600."
            )

        output = Path(output_path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        self.cancel_event.clear()
        self.connect(interface, 0x720)
        assert self.ecu is not None

        try:
            self.log("[*] EEPROM READ-ONLY — brak kasowania i zapisu")
            self.log("[>] TX: 10 01 — sesja domyślna")
            if not self.ecu.UDSDiagnosticSessionControl(0x01):
                raise StudioError("ECU odrzuciło sesję 10 01.")
            time.sleep(0.2)

            try:
                part_number = self.ecu.getPartNo() or "unknown"
            except Exception:
                part_number = "unknown"
            self.log(f"[+] IPC: {part_number}")

            self.log("[>] TX: 10 02 — sesja programowania")
            if not self.ecu.UDSDiagnosticSessionControl(0x02):
                raise StudioError("ECU odrzuciło sesję programowania 10 02.")
            time.sleep(1.0)

            if security_profile != "gm2t":
                raise StudioError("Ta wersja EEPROM obsługuje wyłącznie profil GM2T.")
            magic = 0x4A7722
            profile_name = "IPC GM2T — verified"

            self.log(f"[+] Profil Security: {profile_name}")
            ok, message = self.ecu.unlock(0x01, magic_override=magic)
            self.log(message)
            if not ok:
                raise StudioError(message)

            sbl = self.sbl
            self.log(f"[*] Ładowanie SBL: {sbl.part_number} ({sbl_total} B)")
            self._upload(sbl, 0, sbl_total)
            self.log(f"[>] Uruchamiam SBL pod 0x{call_addr:08X}")
            if not self.ecu.SBLcall(call_addr):
                raise StudioError("Nie udało się uruchomić SBL.")

            self.log(f"[>] RequestUpload: address=0x{address:08X}, size=0x{size:X}")
            upload_response = self.ecu.UDSRequestUpload(address, size, fmt=0x00, aslen=0x44)
            if not upload_response:
                raise StudioError("RequestUpload EEPROM zostało odrzucone.")
            self.log("[<] RequestUpload OK: " + bytes(upload_response).hex(" ").upper())

            data = bytearray()
            counter = 1
            while len(data) < size:
                if self.cancel_event.is_set():
                    raise StudioError("Odczyt EEPROM przerwany przez użytkownika.")
                block = self.ecu.UDSUploadBlock(counter & 0xFF)
                if block is False:
                    raise StudioError(f"Brak poprawnego bloku EEPROM 0x{counter & 0xFF:02X}.")
                block = bytes(block)
                if not block:
                    raise StudioError(f"Pusty blok EEPROM 0x{counter & 0xFF:02X}.")
                remaining = size - len(data)
                if len(block) > remaining:
                    self.log(f"[!] Ostatni blok ma {len(block)} B; używam wymaganych {remaining} B.")
                    block = block[:remaining]
                data.extend(block)
                self.progress(len(data), size, "EEPROM READ")
                self.log(f"[<] Blok 0x{counter & 0xFF:02X}: {len(block)} B ({len(data)}/{size})")
                counter += 1
                if counter > 0x100:
                    raise StudioError("Przekroczono 256 bloków podczas odczytu EEPROM.")

            if not self.ecu.UDSRequestTransferExit():
                raise StudioError("RequestTransferExit po odczycie EEPROM zostało odrzucone.")
            if len(data) != size:
                raise StudioError(f"Nieprawidłowy rozmiar EEPROM: {len(data)} zamiast {size}.")

            temp = output.with_suffix(output.suffix + ".tmp")
            temp.write_bytes(data)
            temp.replace(output)
            digest = hashlib.sha256(data).hexdigest()
            self.progress(size, size, "EEPROM odczytany")
            self.log(f"[+] EEPROM zapisany: {output}")
            self.log(f"[+] Rozmiar: {len(data)} B; SHA-256: {digest}")
            return {
                "part_number": str(part_number),
                "output": str(output),
                "size": len(data),
                "sha256": digest,
                "security_profile": profile_name,
                "sbl": sbl.part_number,
            }
        finally:
            self.disconnect()

    def write_ipc_eeprom(
        self,
        interface: str,
        input_path: str | Path,
        backup_path: str | Path,
        security_profile: str = "gm2t",
        address: int = 0x02000000,
        size: int = 0x1000,
    ) -> dict[str, str | int]:
        """Kasuje i zapisuje 4 KiB EEPROM IPC GM2T bez pośredniego VBF.

        Przed kasowaniem wykonuje automatyczny odczyt bieżącego EEPROM-u do backup_path.
        """
        if self.sbl is None:
            raise StudioError("Dodaj właściwy SBL VBF dla GM2T (14C025) przed zapisem EEPROM.")
        source = Path(input_path).expanduser().resolve()
        if not source.is_file():
            raise StudioError(f"Plik EEPROM nie istnieje: {source}")
        payload = source.read_bytes()
        if len(payload) != size or size != 0x1000:
            raise StudioError(f"EEPROM.bin musi mieć dokładnie 4096 bajtów; ma {len(payload)} B.")

        sbl_total = sum(ds["size"] for ds in self.sbl.vbf.data)
        call = self.sbl.vbf.header.get("call")
        if call is None:
            raise StudioError("SBL nie ma pola call w nagłówku VBF.")
        call_addr = int(call, 0) if isinstance(call, str) else int(call)
        if sbl_total != 0x35C or call_addr != 0x40003600:
            raise StudioError(
                "Nieprawidłowy SBL dla GM2T EEPROM. "
                f"Wczytano payload 0x{sbl_total:X}, call 0x{call_addr:08X}; "
                "wymagany payload 0x35C i call 0x40003600."
            )
        if security_profile != "gm2t":
            raise StudioError("Ta wersja EEPROM obsługuje wyłącznie profil GM2T.")

        backup = Path(backup_path).expanduser().resolve()
        backup.parent.mkdir(parents=True, exist_ok=True)
        self.cancel_event.clear()
        self.connect(interface, 0x720)
        assert self.ecu is not None

        try:
            self.log("[*] GM2T EEPROM WRITE — bez pośredniego VBF")
            if not self.ecu.UDSDiagnosticSessionControl(0x01):
                raise StudioError("ECU odrzuciło sesję 10 01.")
            time.sleep(0.2)
            try:
                part_number = self.ecu.getPartNo() or "unknown"
            except Exception:
                part_number = "unknown"
            self.log(f"[+] IPC: {part_number}")

            if not self.ecu.UDSDiagnosticSessionControl(0x02):
                raise StudioError("ECU odrzuciło sesję programowania 10 02.")
            time.sleep(1.0)
            ok, message = self.ecu.unlock(0x01, magic_override=0x4A7722)
            self.log(message)
            if not ok:
                raise StudioError(message)

            sbl = self.sbl
            self.log(f"[*] Ładowanie SBL: {sbl.part_number} ({sbl_total} B)")
            self._upload(sbl, 0, sbl_total)
            self.log(f"[>] Uruchamiam SBL pod 0x{call_addr:08X}")
            if not self.ecu.SBLcall(call_addr):
                raise StudioError("Nie udało się uruchomić SBL.")

            # Backup przed kasowaniem.
            self.log(f"[>] Backup RequestUpload: 0x{address:08X}, 0x{size:X}")
            if not self.ecu.UDSRequestUpload(address, size, fmt=0x00, aslen=0x44):
                raise StudioError("Nie udało się odczytać backupu przed zapisem.")
            current = bytearray()
            counter = 1
            while len(current) < size:
                block = self.ecu.UDSUploadBlock(counter & 0xFF)
                if block is False:
                    raise StudioError(f"Backup EEPROM: brak bloku 0x{counter & 0xFF:02X}.")
                current.extend(bytes(block)[:size-len(current)])
                counter += 1
                if counter > 0x100:
                    raise StudioError("Backup EEPROM przekroczył 256 bloków.")
            if not self.ecu.UDSRequestTransferExit():
                raise StudioError("Backup EEPROM: RequestTransferExit odrzucone.")
            backup.write_bytes(current)
            self.log(f"[+] Backup zapisany: {backup}")
            self.log(f"[+] Backup SHA-256: {hashlib.sha256(current).hexdigest()}")

            # Kasowanie i bezpośredni zapis BIN.
            self.log(f"[>] Erase EEPROM: 0x{address:08X}, 0x{size:X}")
            if not self.ecu.erase(address, size):
                raise StudioError("Kasowanie EEPROM nie powiodło się.")

            self.log(f"[>] RequestDownload EEPROM: 0x{address:08X}, 0x{size:X}")
            chunk_raw = self.ecu.UDSRequestDownload(address, size, fmt=0x00, aslen=0x44)
            if not chunk_raw:
                raise StudioError("RequestDownload EEPROM zostało odrzucone.")
            max_len = int.from_bytes(bytes(chunk_raw), "big")
            chunk = max(1, min(128, max_len - 2))
            count = (size + chunk - 1) // chunk
            self.log(f"[+] TransferData: {count} bloków, maks. {chunk} B danych")
            done = 0
            for index in range(count):
                if self.cancel_event.is_set():
                    raise StudioError("Zapis EEPROM przerwany przez użytkownika.")
                part = payload[index*chunk:(index+1)*chunk]
                if not self.ecu.UDSTransferData((index + 1) & 0xFF, part):
                    raise StudioError(f"TransferData nie powiódł się, blok {index+1}/{count}.")
                done += len(part)
                self.progress(done, size, "EEPROM WRITE")
                self.log(f"[>] Blok 0x{(index+1)&0xFF:02X}: {len(part)} B ({done}/{size})")
            if not self.ecu.UDSRequestTransferExit():
                raise StudioError("RequestTransferExit po zapisie EEPROM zostało odrzucone.")
            if not self.ecu.commit():
                raise StudioError("Końcowa rutyna 31 01 03 04 została odrzucona.")

            digest = hashlib.sha256(payload).hexdigest()
            self.progress(size, size, "EEPROM zapisany")
            self.log(f"[+] EEPROM zapisany z pliku: {source}")
            self.log(f"[+] Rozmiar: {size} B; SHA-256: {digest}")
            return {
                "part_number": str(part_number),
                "input": str(source),
                "backup": str(backup),
                "size": size,
                "sha256": digest,
                "sbl": sbl.part_number,
            }
        finally:
            self.disconnect()

    def monitor_can(self, interface: str, on_frame, stop_event: threading.Event) -> None:
        """Passive raw CAN monitor. Must be used while the diagnostic connection is closed."""
        if self.ecu is not None:
            raise StudioError("Rozłącz połączenie diagnostyczne przed uruchomieniem monitora CAN.")
        system = platform.system()
        if isinstance(interface, str) and interface.startswith("fordlink"):
            from fordlink import FordLinkBus
            prefix, port = interface.split(":", 1)
            channel = 1 if prefix == "fordlink1" else 0
            bus = FordLinkBus(port=port, serial_baudrate=1_000_000, channel=channel, bitrate=500000)
        elif system == "Darwin":
            bus = can.Bus(interface="gs_usb", channel=int(interface), bitrate=500000)
        elif system == "Linux":
            bus = can.Bus(interface="socketcan", channel=interface, bitrate=500000, receive_own_messages=False)
        else:
            bus = can.Bus(interface="gs_usb", channel=int(interface), bitrate=500000)
        self.log(f"[+] Monitor CAN uruchomiony na {interface}")
        try:
            while not stop_event.is_set():
                msg = bus.recv(timeout=0.25)
                if msg is not None:
                    on_frame(msg)
        finally:
            try:
                bus.shutdown()
            except Exception:
                pass
            self.log("[+] Monitor CAN zatrzymany")

    def cancel(self) -> None:
        self.cancel_event.set()
