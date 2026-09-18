"""Ford legacy 3-byte SecurityAccess key generation.

The legacy Ford algorithm is one universal 24-bit LFSR keyed by a 5-byte
(40-bit) secret.  ECU families differ primarily by the secret selected for the
live hardware (normally DID F111) and SecurityAccess level.

This module intentionally keeps the algorithm separate from the ECU database:
  seed (3 bytes) + secret (5 bytes) -> key (3 bytes)
"""
from __future__ import annotations


def _secret_bytes(secret: int | bytes | bytearray | str) -> bytes:
    if isinstance(secret, str):
        text = secret.strip().replace(" ", "").replace(":", "")
        if text.lower().startswith("0x"):
            value = int(text, 16)
            return value.to_bytes(5, "big")
        raw = bytes.fromhex(text)
        if len(raw) != 5:
            raise ValueError(f"secret must be 5 bytes, got {len(raw)}")
        return raw
    if isinstance(secret, int):
        if not 0 <= secret <= 0xFFFFFFFFFF:
            raise ValueError("secret must fit in 40 bits")
        return secret.to_bytes(5, "big")
    raw = bytes(secret)
    if len(raw) != 5:
        raise ValueError(f"secret must be 5 bytes, got {len(raw)}")
    return raw


def ford_legacy_key(seed3: bytes | bytearray | list[int], secret: int | bytes | bytearray | str) -> bytes:
    """Return the 3-byte legacy Ford SecurityAccess key.

    ``seed3`` is the 3-byte seed returned by UDS 0x27.
    ``secret`` is the ECU/family-specific 5-byte secret in big-endian order.
    """
    seed = bytes(seed3)
    if len(seed) != 3:
        raise ValueError(f"legacy Ford algorithm requires a 3-byte seed, got {len(seed)}")
    s0, s1, s2, s3, s4 = _secret_bytes(secret)

    seed_int = (seed[0] << 16) | (seed[1] << 8) | seed[2]
    first_word = (
        ((seed_int & 0xFF0000) >> 16)
        | (seed_int & 0xFF00)
        | (s0 << 24)
        | ((seed_int & 0xFF) << 16)
    )
    state = 0xC541A9

    def round_bit(inbit: int, value: int) -> int:
        a = (inbit ^ (value & 1)) << 23
        v = a | (value >> 1)
        t = (v & 0x800000) >> 23
        return (
            (v & 0xEF6FD7)
            | ((((v & 0x100000) >> 20) ^ t) << 20)
            | (((((value >> 1) & 0x8000) >> 15) ^ t) << 15)
            | (((((value >> 1) & 0x1000) >> 12) ^ t) << 12)
            | (32 * ((((value >> 1) & 0x20) >> 5) ^ t))
            | (8 * ((((value >> 1) & 8) >> 3) ^ t))
        )

    for bit in range(32):
        state = round_bit((first_word >> bit) & 1, state)

    second_word = (s4 << 24) | (s3 << 16) | (s2 << 8) | s1
    for bit in range(32):
        state = round_bit((second_word >> bit) & 1, state)

    key = (
        ((state & 0xF0000) >> 16)
        | (16 * (state & 0xF))
        | ((((state & 0xF00000) >> 20) | ((state & 0xF000) >> 8)) << 8)
        | (((state & 0xFF0) >> 4) << 16)
    )
    return bytes([(key >> 16) & 0xFF, (key >> 8) & 0xFF, key & 0xFF])


def selftest() -> bool:
    # Published / commonly used regression vector from the legacy algorithm.
    return ford_legacy_key(bytes.fromhex("1F7C69"), 0x0000FA5FC0).hex() == "9a64ce"
