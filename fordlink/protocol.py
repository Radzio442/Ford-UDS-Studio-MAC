from __future__ import annotations

import struct
from dataclasses import dataclass

COMMAND_SYNC = 0xA5
COMMAND_DEVICE_INFO = 0x01
COMMAND_DEVICE_FIRMWARE = 0x02
COMMAND_DEVICE_SERIAL = 0x03
COMMAND_DEVICE_MODE = 0x04
COMMAND_DEVICE_HARDWARE = 0x05
COMMAND_DEVICE_OPEN = 0x08
COMMAND_DEVICE_CLOSE = 0x09
COMMAND_CHANNEL_CONFIG = 0x11
COMMAND_CHANNEL_OPEN = 0x18
COMMAND_CHANNEL_CLOSE = 0x19
COMMAND_MESSAGE = 0x40
COMMAND_ACK = 0x80

FLAG_DEVICE_MODE_CAN = 0x01
FLAG_CHANNEL_1 = 0x20
FLAG_CHANNEL_2 = 0x40
FLAG_CONFIG_BUS_SPEED_M = 0x02
FLAG_CONFIG_MODE = 0x09
MODE_NORMAL = 0x00
FLAG_MESSAGE_CHANNEL_1 = 0x2000
FLAG_MESSAGE_CHANNEL_2 = 0x4000
FLAG_MESSAGE_CONFIRM_REQUIRED = 0x0001
FLAG_MESSAGE_EXTID = 0x00000001
FLAG_MESSAGE_RTR = 0x00000002
FLAG_MESSAGE_RX = 0x10000000

COMMAND_HEADER = struct.Struct('<BBBB')
MESSAGE_HEADER = struct.Struct('<BBHH')
CUSTOM_SPEED = struct.Struct('<HHHH')
TO_BUS_MESSAGE = struct.Struct('<IIH8s')
FROM_BUS_MESSAGE = struct.Struct('<IIIIH8s')

@dataclass(frozen=True)
class CommandPacket:
    command: int
    sequence: int
    flags: int
    payload: bytes

@dataclass(frozen=True)
class MessagePacket:
    command: int
    sequence: int
    flags: int
    payload: bytes

def pack_command(command: int, sequence: int, flags: int = 0, payload: bytes = b'') -> bytes:
    if len(payload) > 0xFF:
        raise ValueError('Command payload too large')
    return COMMAND_HEADER.pack(command, sequence, flags, len(payload)) + payload

def pack_message(sequence: int, channel: int, can_id: int, data: bytes, *, extended: bool = False, rtr: bool = False, confirm: bool = False) -> bytes:
    if len(data) > 8:
        raise ValueError('Classic CAN payload cannot exceed 8 bytes')
    header_flags = FLAG_MESSAGE_CHANNEL_1 if channel == 0 else FLAG_MESSAGE_CHANNEL_2
    msg_flags = 0
    if extended: msg_flags |= FLAG_MESSAGE_EXTID
    if rtr: msg_flags |= FLAG_MESSAGE_RTR
    if confirm: msg_flags |= FLAG_MESSAGE_CONFIRM_REQUIRED
    payload = TO_BUS_MESSAGE.pack(msg_flags, can_id, len(data), data.ljust(8, b'\x00'))
    return MESSAGE_HEADER.pack(COMMAND_MESSAGE, sequence, header_flags, len(payload)) + payload

def pack_custom_speed(sequence: int, channel: int, prescaler: int, seg1: int, seg2: int, sjw: int) -> bytes:
    flags = (FLAG_CHANNEL_1 if channel == 0 else FLAG_CHANNEL_2) | FLAG_CONFIG_BUS_SPEED_M
    return pack_command(COMMAND_CHANNEL_CONFIG, sequence, flags, CUSTOM_SPEED.pack(prescaler, seg1, seg2, sjw))

def pack_channel_mode(sequence: int, channel: int, mode: int = MODE_NORMAL) -> bytes:
    flags = (FLAG_CHANNEL_1 if channel == 0 else FLAG_CHANNEL_2) | FLAG_CONFIG_MODE
    return pack_command(COMMAND_CHANNEL_CONFIG, sequence, flags, bytes([mode]))

def packet_size_from_prefix(prefix: bytes) -> int | None:
    if len(prefix) < 4:
        return None
    command = prefix[0] & 0x7F
    if command == COMMAND_MESSAGE:
        if len(prefix) < MESSAGE_HEADER.size:
            return None
        _, _, _, size = MESSAGE_HEADER.unpack(prefix[:MESSAGE_HEADER.size])
        return MESSAGE_HEADER.size + size
    _, _, _, size = COMMAND_HEADER.unpack(prefix[:COMMAND_HEADER.size])
    return COMMAND_HEADER.size + size
