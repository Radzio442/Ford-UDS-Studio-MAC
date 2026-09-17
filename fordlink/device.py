from __future__ import annotations

import queue
import struct
import threading
import time
from dataclasses import dataclass

from .errors import FordLinkProtocolError, FordLinkTimeout
from .protocol import *
from .transport_serial import SerialPacketTransport

@dataclass(frozen=True)
class FordLinkDeviceInfo:
    hardware_id: int
    name: str
    firmware: str
    serial_hex: str

@dataclass(frozen=True)
class RawCanFrame:
    channel: int
    arbitration_id: int
    data: bytes
    extended: bool
    rtr: bool
    timestamp_ms: int

class FordLinkDevice:
    def __init__(self, port: str, baudrate: int = 1_000_000):
        self.transport = SerialPacketTransport(port, baudrate)
        self._sequence = 0
        self._responses: queue.Queue[bytes] = queue.Queue()
        self._frames: queue.Queue[RawCanFrame] = queue.Queue()
        self._stop = threading.Event()
        self._reader = None
        self._command_lock = threading.Lock()

    def _next_sequence(self) -> int:
        value = self._sequence
        self._sequence = (self._sequence + 1) & 0xFF
        return value

    def open(self) -> FordLinkDeviceInfo:
        self.transport.open()
        # Raw sync has a fixed response 5A 00 5A 00.
        self.transport.write(bytes([0xA5, 0x00, 0xA5, 0x00]))
        sync = self.transport.read_packet(timeout=1.0)
        if sync != bytes([0x5A, 0x00, 0x5A, 0x00]):
            raise FordLinkProtocolError(f'Bad sync response: {sync.hex(" ")}')
        self._stop.clear()
        self._reader = threading.Thread(target=self._reader_loop, name='FordLinkReader', daemon=True)
        self._reader.start()

        hardware = self.command(COMMAND_DEVICE_HARDWARE)
        name = self.command(COMMAND_DEVICE_INFO).decode('ascii', errors='replace').rstrip('\x00')
        firmware = self.command(COMMAND_DEVICE_FIRMWARE).decode('ascii', errors='replace').rstrip('\x00')
        serial_bytes = self.command(COMMAND_DEVICE_SERIAL)
        self._expect_ack(self.command_packet(COMMAND_DEVICE_MODE, FLAG_DEVICE_MODE_CAN))
        self._expect_ack(self.command_packet(COMMAND_DEVICE_OPEN))
        return FordLinkDeviceInfo(hardware[0] if hardware else -1, name, firmware, serial_bytes.hex().upper())

    def close(self) -> None:
        try:
            if self.transport.is_open:
                try: self.command_packet(COMMAND_DEVICE_CLOSE, timeout=0.3)
                except Exception: pass
        finally:
            self._stop.set()
            self.transport.close()
            if self._reader and self._reader.is_alive():
                self._reader.join(timeout=0.3)
            self._reader = None

    def _reader_loop(self) -> None:
        while not self._stop.is_set() and self.transport.is_open:
            try:
                packet = self.transport.read_packet(timeout=0.1)
            except FordLinkTimeout:
                continue
            except Exception:
                break
            if (packet[0] & 0x7F) == COMMAND_MESSAGE and len(packet) >= MESSAGE_HEADER.size:
                self._decode_message(packet)
            else:
                self._responses.put(packet)

    def _decode_message(self, packet: bytes) -> None:
        command, sequence, channel_flags, size = MESSAGE_HEADER.unpack(packet[:MESSAGE_HEADER.size])
        payload = packet[MESSAGE_HEADER.size:MESSAGE_HEADER.size+size]
        if len(payload) != FROM_BUS_MESSAGE.size:
            return
        flags, timestamp, crc, can_id, dlc, data = FROM_BUS_MESSAGE.unpack(payload)
        channel = 0 if channel_flags == FLAG_MESSAGE_CHANNEL_1 else 1
        self._frames.put(RawCanFrame(channel, can_id, data[:dlc], bool(flags & FLAG_MESSAGE_EXTID), bool(flags & FLAG_MESSAGE_RTR), timestamp))

    def command_packet(self, command: int, flags: int = 0, payload: bytes = b'', timeout: float = 1.0) -> bytes:
        sequence = self._next_sequence()
        request = pack_command(command, sequence, flags, payload)
        with self._command_lock:
            self.transport.write(request)
            deadline = time.monotonic() + timeout
            deferred = []
            try:
                while time.monotonic() < deadline:
                    try: packet = self._responses.get(timeout=max(0.01, deadline-time.monotonic()))
                    except queue.Empty: break
                    if len(packet) >= 2 and packet[1] == sequence:
                        return packet
                    deferred.append(packet)
            finally:
                for packet in deferred: self._responses.put(packet)
        raise FordLinkTimeout(f'Timeout waiting for command 0x{command:02X}')

    def command(self, command: int, flags: int = 0, payload: bytes = b'', timeout: float = 1.0) -> bytes:
        packet = self.command_packet(command, flags, payload, timeout)
        if packet[0] == 0xFF:
            raise FordLinkProtocolError(f'Command 0x{command:02X} rejected')
        if (packet[0] & 0x7F) != command:
            raise FordLinkProtocolError(f'Unexpected command response: {packet.hex(" ")}')
        return packet[4:4+packet[3]]

    @staticmethod
    def _expect_ack(packet: bytes) -> None:
        if not packet or packet[0] == 0xFF or not (packet[0] & COMMAND_ACK):
            raise FordLinkProtocolError(f'Expected ACK, got: {packet.hex(" ")}')

    def configure_channel(self, channel: int, *, prescaler: int = 4, seg1: int = 15, seg2: int = 2, sjw: int = 1) -> None:
        # Values are passed directly to firmware's can_set_bittiming().
        seq = self._next_sequence()
        request = pack_channel_mode(seq, channel, MODE_NORMAL)
        with self._command_lock:
            self.transport.write(request)
            self._expect_ack(self._wait_sequence(seq))
        seq = self._next_sequence()
        request = pack_custom_speed(seq, channel, prescaler, seg1, seg2, sjw)
        with self._command_lock:
            self.transport.write(request)
            self._expect_ack(self._wait_sequence(seq))
        flags = FLAG_CHANNEL_1 if channel == 0 else FLAG_CHANNEL_2
        self._expect_ack(self.command_packet(COMMAND_CHANNEL_OPEN, flags))

    def _wait_sequence(self, sequence: int, timeout: float = 1.0) -> bytes:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try: packet = self._responses.get(timeout=max(0.01, deadline-time.monotonic()))
            except queue.Empty: break
            if len(packet) >= 2 and packet[1] == sequence: return packet
        raise FordLinkTimeout(f'Timeout waiting for sequence {sequence}')

    def close_channel(self, channel: int) -> None:
        flags = FLAG_CHANNEL_1 if channel == 0 else FLAG_CHANNEL_2
        self._expect_ack(self.command_packet(COMMAND_CHANNEL_CLOSE, flags))

    def send_can(self, channel: int, arbitration_id: int, data: bytes, *, extended: bool = False, rtr: bool = False) -> None:
        sequence = self._next_sequence()
        self.transport.write(pack_message(sequence, channel, arbitration_id, data, extended=extended, rtr=rtr, confirm=False))

    def recv_can(self, timeout: float | None = None) -> RawCanFrame | None:
        try: return self._frames.get(timeout=timeout)
        except queue.Empty: return None
