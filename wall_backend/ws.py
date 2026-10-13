"""Minimal WebSocket, enough for same-origin text events."""

from __future__ import annotations

import base64
import hashlib
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WebSocketClient:
    def __init__(self, handler):
        self.handler = handler
        self.socket = handler.connection

    def handshake(self):
        key = self.handler.headers["Sec-WebSocket-Key"].strip()
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        )
        self.socket.sendall(response.encode("ascii"))

    def send_text(self, text: str):
        data = text.encode("utf-8")
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", length))
        self.socket.sendall(header + data)

    def serve(self, on_message):
        self.handshake()
        try:
            while True:
                frame = self._read_frame()
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self._pong(payload)
                elif opcode == 0x1:
                    on_message(payload.decode("utf-8"))
        finally:
            try:
                self.socket.shutdown(2)
            except OSError:
                pass

    def _read_exact(self, size: int) -> bytes | None:
        chunks = []
        left = size
        while left:
            part = self.socket.recv(left)
            if not part:
                return None
            chunks.append(part)
            left -= len(part)
        return b"".join(chunks)

    def _read_frame(self):
        head = self._read_exact(2)
        if not head:
            return None
        opcode = head[0] & 0x0F
        length = head[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        mask = self._read_exact(4) if head[1] & 0x80 else None
        payload = self._read_exact(length) or b""
        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def _pong(self, payload: bytes):
        header = bytes([0x8A, len(payload)])
        self.socket.sendall(header + payload)
