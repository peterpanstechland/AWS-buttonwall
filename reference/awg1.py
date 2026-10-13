"""AWG1 frames. CRC is IEEE CRC-32, the same value as zlib.crc32."""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass

MAGIC = b"\xA5\x5A"
MAJOR = 1
MAX_PAYLOAD = 2048

HELLO = 0x01
HELLO_ACK = 0x02
HEARTBEAT = 0x03
STATE_SNAPSHOT = 0x04
CONFIG_SET = 0x05
SNAPSHOT_REQUEST = 0x06
BUTTON_HIT = 0x10
BUTTON_RELEASE = 0x11
START_GESTURE = 0x12
SCENE_SET = 0x20
CUE_PLAY = 0x21
SCENE_CLEAR = 0x22
LAMP_SET = 0x23
COUNTDOWN_START = 0x30
COUNTDOWN_EVENT = 0x31
TIMER_EVENT = 0x32
TIMER_CONTROL = 0x33
ROUND_ARM = 0x34
ROUND_ARMED = 0x35
STEP_ARM = 0x36
STEP_ARMED = 0x37
INPUT_DRAINED = 0x38
RESULT_ACK = 0x39
SELF_TEST = 0x40
DIAG_RESULT = 0x41
ERROR = 0x7E
ACK = 0x7F

RELIABLE = {
    HELLO,
    HELLO_ACK,
    STATE_SNAPSHOT,
    CONFIG_SET,
    SNAPSHOT_REQUEST,
    BUTTON_HIT,
    START_GESTURE,
    SCENE_SET,
    CUE_PLAY,
    SCENE_CLEAR,
    LAMP_SET,
    COUNTDOWN_START,
    COUNTDOWN_EVENT,
    TIMER_EVENT,
    TIMER_CONTROL,
    ROUND_ARM,
    ROUND_ARMED,
    STEP_ARM,
    STEP_ARMED,
    INPUT_DRAINED,
    RESULT_ACK,
    SELF_TEST,
    DIAG_RESULT,
}


def crc32_ieee(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


@dataclass(frozen=True)
class Frame:
    msg_type: int
    payload: dict
    seq: int
    ack_required: bool
    is_response: bool

    @property
    def reliable(self) -> bool:
        return self.msg_type in RELIABLE and self.ack_required


def encode_frame(msg_type: int, payload: dict, seq: int, ack_required: bool = False, is_response: bool = False) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_PAYLOAD:
        raise ValueError("payload too large")
    flags = (1 if ack_required else 0) | (2 if is_response else 0)
    head = struct.pack("<BBBBIH", MAJOR, msg_type, flags, 0, seq, len(body))
    digest = crc32_ieee(head + body)
    return MAGIC + head + body + struct.pack("<I", digest)


class Parser:
    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[Frame | None, str | None]]:
        """Return parsed frames. A tuple (None, reason) is a dropped bad frame."""
        self._buf.extend(data)
        out = []
        while True:
            start = self._buf.find(MAGIC)
            if start < 0:
                if len(self._buf) > 1:
                    del self._buf[:-1]
                break
            if start:
                del self._buf[:start]
            if len(self._buf) < 12:
                break
            payload_len = struct.unpack_from("<H", self._buf, 10)[0]
            if payload_len > MAX_PAYLOAD:
                out.append((None, "BAD_FRAME"))
                del self._buf[:2]
                continue
            total = 16 + payload_len
            if len(self._buf) < total:
                break
            packet = bytes(self._buf[:total])
            del self._buf[:total]
            frame, reason = _decode_packet(packet)
            out.append((frame, reason))
        return out


def _decode_packet(packet: bytes) -> tuple[Frame | None, str | None]:
    if packet[:2] != MAGIC:
        return None, "BAD_FRAME"
    region = packet[2:-4]
    expect = struct.unpack_from("<I", packet, len(packet) - 4)[0]
    if crc32_ieee(region) != expect:
        return None, "BAD_CRC"
    major, msg_type, flags, _reserved, seq, payload_len = struct.unpack_from("<BBBBIH", packet, 2)
    if major != MAJOR:
        return None, "VERSION_MISMATCH"
    raw = packet[12:12 + payload_len]
    try:
        text = raw.decode("utf-8")
        payload = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "BAD_JSON"
    if not isinstance(payload, dict):
        return None, "BAD_JSON"
    return Frame(msg_type, payload, seq, bool(flags & 1), bool(flags & 2)), None
