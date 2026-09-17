from __future__ import annotations

from dataclasses import dataclass
from .device import FordLinkDevice

@dataclass(frozen=True)
class FordLinkFrame:
    arbitration_id: int
    data: bytes
    is_extended_id: bool = False
    is_remote_frame: bool = False
    timestamp: float = 0.0

class FordLinkBus:
    """CAN bus adapter used by UDS, flash, EEPROM and monitor paths.

    The public API intentionally mirrors the small python-can subset used by
    Ford UDS Studio: send(), recv(), set_filters() and shutdown().
    """
    def __init__(self, port: str, *, serial_baudrate: int = 1_000_000, channel: int = 0, bitrate: int = 500_000):
        if bitrate != 500_000:
            raise ValueError('v0.1 currently validates only 500 kbit/s')
        self.device = FordLinkDevice(port, serial_baudrate)
        self.channel = channel
        self.info = self.device.open()
        # Proven on the CH-3.2/F105 firmware and real IPC at 500 kbit/s.
        # APB1=36 MHz, prescaler=4, 1+15+2 TQ gives 500 kbit/s.
        self.device.configure_channel(channel, prescaler=4, seg1=15, seg2=2, sjw=1)
        self._filters = []

    def set_filters(self, filters):
        self._filters = filters or []

    def send(self, message) -> None:
        self.device.send_can(self.channel, int(message.arbitration_id), bytes(message.data), extended=bool(getattr(message, 'is_extended_id', False)), rtr=bool(getattr(message, 'is_remote_frame', False)))

    def recv(self, timeout: float | None = None):
        import time
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        while True:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            if deadline is not None and remaining <= 0.0:
                return None
            frame = self.device.recv_can(remaining)
            if frame is None:
                return None
            if frame.channel != self.channel: continue
            if self._filters:
                matched = any((frame.arbitration_id & f.get('can_mask', 0x1FFFFFFF)) == (f.get('can_id', 0) & f.get('can_mask', 0x1FFFFFFF)) for f in self._filters)
                if not matched: continue
            try:
                import can
                return can.Message(arbitration_id=frame.arbitration_id, data=frame.data, is_extended_id=frame.extended, is_remote_frame=frame.rtr, timestamp=frame.timestamp_ms/1000.0)
            except ImportError:
                return FordLinkFrame(frame.arbitration_id, frame.data, frame.extended, frame.rtr, frame.timestamp_ms/1000.0)

    def shutdown(self) -> None:
        try: self.device.close_channel(self.channel)
        except Exception: pass
        self.device.close()

    close = shutdown
