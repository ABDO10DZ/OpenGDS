"""Length-prefixed JSON framing shared by LSP and DAP clients."""
from __future__ import annotations
import json
import re

_HEADER_END = b"\r\n\r\n"
_LENGTH_RE = re.compile(rb"(?:^|\r\n)Content-Length\s*:\s*(\d+)", re.IGNORECASE)


def encode_message(payload: dict) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode("ascii") + _HEADER_END + body


class FrameBuffer:
    """Incremental parser for Content-Length framed JSON messages."""
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[dict]:
        self.buffer.extend(data)
        messages: list[dict] = []
        while True:
            split = self.buffer.find(_HEADER_END)
            if split < 0:
                break
            header = bytes(self.buffer[:split])
            match = _LENGTH_RE.search(header)
            if not match:
                # Drop malformed header without discarding any later messages.
                del self.buffer[:split + len(_HEADER_END)]
                continue
            size = int(match.group(1))
            body_start = split + len(_HEADER_END)
            if len(self.buffer) < body_start + size:
                break
            body = bytes(self.buffer[body_start:body_start + size])
            del self.buffer[:body_start + size]
            try:
                value = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                messages.append(value)
        return messages
