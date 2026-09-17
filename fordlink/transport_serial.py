from __future__ import annotations

import threading
import time
from typing import Optional

from .errors import FordLinkTimeout
from .protocol import packet_size_from_prefix

try:
    import serial
except ImportError as exc:  # pragma: no cover
    serial = None
    _SERIAL_IMPORT_ERROR = exc
else:
    _SERIAL_IMPORT_ERROR = None

class SerialPacketTransport:
    def __init__(self, port: str, baudrate: int = 1_000_000, timeout: float = 0.05):
        if serial is None:
            raise RuntimeError('pyserial is required: python3 -m pip install pyserial') from _SERIAL_IMPORT_ERROR
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial = None
        self._lock = threading.Lock()
        self._rx = bytearray()

    @property
    def is_open(self) -> bool:
        return bool(self._serial and self._serial.is_open)

    def open(self) -> None:
        if self.is_open:
            return
        self._serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout, write_timeout=1.0)
        self._serial.reset_input_buffer()
        self._serial.reset_output_buffer()

    def close(self) -> None:
        ser, self._serial = self._serial, None
        if ser:
            try: ser.close()
            except Exception: pass

    def write(self, data: bytes) -> None:
        if not self.is_open:
            raise RuntimeError('Serial transport is closed')
        with self._lock:
            written = self._serial.write(data)
            self._serial.flush()
        if written != len(data):
            raise IOError(f'Only {written}/{len(data)} bytes written')

    def read_packet(self, timeout: float = 1.0) -> bytes:
        if not self.is_open:
            raise RuntimeError('Serial transport is closed')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            size = packet_size_from_prefix(self._rx)
            if size is not None and len(self._rx) >= size:
                packet = bytes(self._rx[:size])
                del self._rx[:size]
                return packet
            waiting = self._serial.in_waiting
            chunk = self._serial.read(waiting or 1)
            if chunk:
                self._rx.extend(chunk)
        raise FordLinkTimeout('Timeout waiting for FordLink packet')
