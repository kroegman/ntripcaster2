import base64
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class NtripRequest:
    method: str
    path: str
    headers: dict
    body: bytes

    @property
    def mountpoint(self) -> str:
        if self.path.startswith('/'):
            return self.path[1:]
        return self.path

    def auth_basic(self) -> Optional[Tuple[str, str]]:
        auth = self.headers.get('authorization')
        if not auth:
            return None
        parts = auth.split(' ', 1)
        if len(parts) != 2:
            return None
        scheme, b64 = parts
        if scheme.lower() != 'basic':
            return None
        try:
            decoded = base64.b64decode(b64).decode('utf-8')
            if ':' in decoded:
                user, pw = decoded.split(':', 1)
                return user, pw
        except Exception:
            return None
        return None


class NtripParser:
    @staticmethod
    def parse(raw: bytes) -> NtripRequest:
        # Split headers and body
        if b"\r\n\r\n" in raw:
            head, body = raw.split(b"\r\n\r\n", 1)
        else:
            head, body = raw, b""
        lines = head.split(b"\r\n")
        request_line = lines[0].decode('utf-8', errors='ignore')
        method, path, _ = request_line.split(' ', 2)
        headers = {}
        for line in lines[1:]:
            if not line:
                continue
            try:
                k, v = line.decode('utf-8', errors='ignore').split(':', 1)
                headers[k.strip().lower()] = v.strip()
            except ValueError:
                pass
        return NtripRequest(method=method, path=path, headers=headers, body=body)

    @staticmethod
    def detect_version(req: NtripRequest) -> str:
        # v2 has Ntrip-Version: Ntrip/2.0
        v = req.headers.get('ntrip-version')
        if v and v.lower().startswith('ntrip/2'):
            return 'ntrip_v2'
        # v1 uses ICY responses and various agents; absence of v2 header implies v1
        return 'ntrip_v1'


def build_response_ok(version: str, is_source: bool) -> bytes:
    if version == 'ntrip_v2':
        status = b"HTTP/1.1 200 OK\r\n"
        headers = [
            b"Connection: close",
            b"Ntrip-Version: Ntrip/2.0",
            b"Content-Type: gnss/data",
            b"Transfer-Encoding: chunked" if not is_source else b"",  # clients may send GGA
        ]
        out = status + b"\r\n".join([h for h in headers if h]) + b"\r\n\r\n"
        return out
    else:
        # v1 style ICY OK
        return b"ICY 200 OK\r\n\r\n"


def build_response_unauthorized(version: str) -> bytes:
    if version == 'ntrip_v2':
        return (
            b"HTTP/1.1 401 Unauthorized\r\n"
            b"Connection: close\r\n\r\n"
        )
    else:
        return b"ICY 401 Unauthorized\r\n\r\n"


def build_response_not_found(version: str) -> bytes:
    if version == 'ntrip_v2':
        return b"HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n"
    else:
        return b"SOURCETABLE 0\r\n\r\n"
