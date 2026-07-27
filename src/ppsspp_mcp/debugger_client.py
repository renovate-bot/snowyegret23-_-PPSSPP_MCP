from __future__ import annotations

import base64
import json
import os
import socket
import struct
import time
from dataclasses import dataclass
from typing import Any


class PPSSPPDebuggerError(RuntimeError):
    pass


@dataclass
class PPSSPPDebuggerClient:
    host: str = "127.0.0.1"
    port: int = 7378
    path: str = "/debugger"
    timeout: float = 5.0

    def __post_init__(self) -> None:
        self._sock: socket.socket | None = None

    def __enter__(self) -> "PPSSPPDebuggerClient":
        self.connect()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.close()

    def connect(self) -> None:
        if self._sock is not None:
            return
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Sec-WebSocket-Protocol: debugger.ppsspp.org\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = self._recv_http_response(sock)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            sock.close()
            raise PPSSPPDebuggerError(response.decode("latin1", errors="replace"))
        self._sock = sock

    def close(self) -> None:
        sock = self._sock
        if sock is None:
            return
        try:
            self._send_frame(b"", opcode=0x8)
        except (OSError, PPSSPPDebuggerError):
            pass
        self._sock = None
        sock.close()

    def request(self, event: str, **params: Any) -> dict[str, Any]:
        ticket = params.pop("ticket", None) or f"mcp-{time.time_ns():x}"
        payload = {"event": event, **params, "ticket": ticket}
        self.send(payload)
        return self.wait_for_ticket(ticket)

    def notify(self, event: str, **params: Any) -> None:
        self.send({"event": event, **params})

    def request_event(self, event: str, **params: Any) -> dict[str, Any]:
        """Send a request whose asynchronous response does not echo tickets."""
        self.notify(event, **params)
        deadline = time.monotonic() + self.timeout
        last_event: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            message = self.recv_json()
            last_event = message
            if message.get("event") == "error":
                raise PPSSPPDebuggerError(str(message.get("message", f"{event} failed")))
            if message.get("event") == event:
                return message
        raise PPSSPPDebuggerError(f"timed out waiting for event {event}; last_event={last_event!r}")

    def send(self, payload: dict[str, Any]) -> None:
        self.connect()
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._send_frame(raw, opcode=0x1)

    def wait_for_ticket(self, ticket: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        last_event: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            message = self.recv_json()
            last_event = message
            if message.get("ticket") == ticket:
                return message
        raise PPSSPPDebuggerError(f"timed out waiting for ticket {ticket}; last_event={last_event!r}")

    def recv_json(self) -> dict[str, Any]:
        raw = self._recv_message()
        try:
            value = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise PPSSPPDebuggerError(f"invalid JSON from PPSSPP: {raw!r}") from e
        if not isinstance(value, dict):
            raise PPSSPPDebuggerError(f"unexpected JSON from PPSSPP: {value!r}")
        return value

    @staticmethod
    def _recv_http_response(sock: socket.socket) -> bytes:
        chunks: list[bytes] = []
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            data = b"".join(chunks)
            if len(data) > 65536:
                raise PPSSPPDebuggerError("oversized HTTP response")
        return data

    def _send_frame(self, payload: bytes, opcode: int) -> None:
        sock = self._sock
        if sock is None:
            raise PPSSPPDebuggerError("not connected")
        first = 0x80 | (opcode & 0x0F)
        length = len(payload)
        mask_bit = 0x80
        if length < 126:
            header = struct.pack("!BB", first, mask_bit | length)
        elif length <= 0xFFFF:
            header = struct.pack("!BBH", first, mask_bit | 126, length)
        else:
            header = struct.pack("!BBQ", first, mask_bit | 127, length)
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        sock.sendall(header + mask + masked)

    def _recv_exact(self, length: int) -> bytes:
        sock = self._sock
        if sock is None:
            raise PPSSPPDebuggerError("not connected")
        chunks: list[bytes] = []
        remaining = length
        while remaining:
            chunk = sock.recv(remaining)
            if not chunk:
                raise PPSSPPDebuggerError("websocket closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _recv_message(self) -> bytes:
        chunks: list[bytes] = []
        while True:
            header = self._recv_exact(2)
            first, second = header
            opcode = first & 0x0F
            fin = bool(first & 0x80)
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length) if length else b""
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 0x8:
                raise PPSSPPDebuggerError("websocket closed by PPSSPP")
            if opcode == 0x9:
                self._send_frame(payload, opcode=0xA)
                continue
            if opcode in (0x1, 0x2, 0x0):
                chunks.append(payload)
                if fin:
                    return b"".join(chunks)
