import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Mountpoint
from ..services.mountpoint_manager import MountpointManager
from .protocol import NtripParser, build_response_ok, build_response_unauthorized, build_response_not_found


class NtripCaster:
    def __init__(self, host: str = '0.0.0.0', port: int = 2101, manager: Optional[MountpointManager] = None):
        self.host = host
        self.port = port
        self.manager = manager or MountpointManager()
        self._server: Optional[asyncio.base_events.Server] = None
        self._active_clients_per_owner: dict[int, int] = {}
        self._lock = asyncio.Lock()
        # Dedicated TCP raw listeners per mountpoint id
        self._raw_servers: dict[int, asyncio.base_events.Server] = {}
        self._raw_lock = asyncio.Lock()

    async def start(self):
        self._server = await asyncio.start_server(self.handle_conn, self.host, self.port)
        print(f"NTRIP caster listening on {self.host}:{self.port}")
        # Start dedicated TCP raw listeners for existing mountpoints
        async with self.db_session() as db:
            from ..models import Mountpoint
            mps = db.query(Mountpoint).filter(Mountpoint.source_protocol == 'tcp_raw', Mountpoint.tcp_port.isnot(None)).all()
            for mp in mps:
                try:
                    await self.start_tcp_raw_listener(mp.id, mp.name, mp.tcp_port)  # type: ignore[arg-type]
                except Exception as e:
                    print(f"Failed to start raw listener for {mp.name} on {mp.tcp_port}: {e}")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        # Stop all dedicated raw servers
        async with self._raw_lock:
            for mp_id, srv in list(self._raw_servers.items()):
                try:
                    srv.close()
                    await srv.wait_closed()
                except Exception:
                    pass
            self._raw_servers.clear()

    async def start_tcp_raw_listener(self, mount_id: int, mount_name: str, port: int):
        async with self._raw_lock:
            if mount_id in self._raw_servers:
                return
            server = await asyncio.start_server(
                lambda r, w: self._handle_tcp_raw_conn(mount_id, r, w), self.host, port
            )
            self._raw_servers[mount_id] = server
            print(f"TCP raw listener for {mount_name} on {self.host}:{port}")

    async def stop_tcp_raw_listener(self, mount_id: int):
        async with self._raw_lock:
            srv = self._raw_servers.pop(mount_id, None)
            if srv:
                srv.close()
                await srv.wait_closed()

    async def _handle_tcp_raw_conn(self, mount_id: int, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info('peername')
        # Expect AUTH line first
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        except Exception:
            writer.close()
            await writer.wait_closed()
            return
        if not line.startswith(b"AUTH "):
            writer.close()
            await writer.wait_closed()
            return
        try:
            parts = line.strip().split()
            _, up, mountname = parts[:3]
            userpass = up.decode(errors='ignore')
            if ':' not in userpass:
                raise ValueError('bad auth')
            u, p = userpass.split(':', 1)
            mountname = mountname.decode(errors='ignore')
        except Exception:
            writer.close()
            await writer.wait_closed()
            return

        async with self.db_session() as db:
            mp = db.query(Mountpoint).get(mount_id)
            if not mp or mp.name != mountname:
                writer.close()
                await writer.wait_closed()
                return
            if u != mp.source_username or p != mp.source_password:
                writer.close()
                await writer.wait_closed()
                return
            # OK, accept and stream
            writer.write(b"ICY 200 OK\r\n\r\n")
            await writer.drain()
            hub = await self.manager.get_hub(mp.name)
            self.manager.mark_source_online(db, mp, True)
            try:
                while not reader.at_eof():
                    data = await reader.read(8192)
                    if not data:
                        break
                    hub.publish(data)
                    self.manager.touch_data(db, mp)
            except Exception:
                pass
            finally:
                self.manager.mark_source_online(db, mp, False)
                writer.close()
                await writer.wait_closed()

    @asynccontextmanager
    async def db_session(self) -> Session:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    async def handle_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info('peername')
        # Read initial request (headers). Also support TCP raw AUTH preface.
        try:
            raw = await reader.readuntil(separator=b"\r\n\r\n")
            is_tcp_raw = False
        except Exception:
            # Try to read a single line as TCP raw AUTH
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=2.0)
            except Exception:
                line = b""
            if line.startswith(b"AUTH "):
                # Format: AUTH username:password mountpoint\r\n
                parts = line.strip().split()
                if len(parts) >= 3:
                    _, up, mountname = parts[:3]
                    # synthesize a fake HTTP-like request for unified handling
                    raw = b"SOURCE " + up + b" " + b"/" + mountname + b"\r\n\r\n"
                    is_tcp_raw = True
                else:
                    writer.close()
                    await writer.wait_closed()
                    return
            else:
                writer.close()
                await writer.wait_closed()
                return

        req = NtripParser.parse(raw)
        version = NtripParser.detect_version(req)

        # Identify if this is a client GET or source POST/SOURCE
        method = req.method.upper()
        mount = req.mountpoint

        if mount.upper() == "NEAREST":
            # special virtual mountpoint; we'll later reroute based on GGA
            pass

        async with self.db_session() as db:
            mp = db.query(Mountpoint).filter_by(name=mount).first()
            if not mp and mount.upper() != 'NEAREST':
                writer.write(build_response_not_found(version))
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return

            if method in ("GET",):
                # Client requesting data
                if mount.upper() == 'NEAREST':
                    # Send 200 OK and wait for NMEA GGA from client to determine position, then forward
                    writer.write(build_response_ok(version, is_source=False))
                    await writer.drain()
                    await self._serve_nearest(db, reader, writer, version)
                    return
                else:
                    # Authenticate via Basic
                    creds = req.auth_basic()
                    if not creds:
                        writer.write(build_response_unauthorized(version))
                        await writer.drain()
                        writer.close()
                        await writer.wait_closed()
                        return
                    u, p = creds
                    if u != mp.source_username or p != mp.source_password:
                        writer.write(build_response_unauthorized(version))
                        await writer.drain()
                        writer.close()
                        await writer.wait_closed()
                        return

                    # Enforce per-owner connection limit
                    owner = mp.owner
                    async with self._lock:
                        current = self._active_clients_per_owner.get(owner.id, 0)
                        if current >= (owner.connection_limit or 0):
                            writer.write(build_response_unauthorized(version))
                            await writer.drain()
                            writer.close()
                            await writer.wait_closed()
                            return
                        self._active_clients_per_owner[owner.id] = current + 1

                    writer.write(build_response_ok(version, is_source=False))
                    await writer.drain()

                    hub = await self.manager.get_hub(mp.name)
                    try:
                        async with hub.subscribe() as q:
                            while not reader.at_eof():
                                try:
                                    data = await q.get()
                                except asyncio.CancelledError:
                                    break
                                writer.write(data)
                                try:
                                    await writer.drain()
                                except Exception:
                                    break
                    finally:
                        async with self._lock:
                            self._active_clients_per_owner[owner.id] = max(0, self._active_clients_per_owner.get(owner.id, 1) - 1)
                    writer.close()
                    await writer.wait_closed()
                    return

            elif method in ("POST", "SOURCE"):
                # Source sending data into mountpoint
                # Auth: v1 uses 'SOURCE password mountpoint' in request line; but we simplify: accept Basic too
                authed = False
                if method == 'SOURCE':
                    # v1: req line is like: 'SOURCE password mountpoint' but our parser treats method=SOURCE, path as mountpoint
                    pw = req.path
                    # Unfortunately we don't have username in v1 SOURCE line; many encoders use 'SOURCE <pwd> /mount'
                    # We'll authenticate by password only for v1 when username is unique per mountpoint
                    if mp and pw == mp.source_password:
                        authed = True
                else:
                    creds = req.auth_basic()
                    if creds and mp:
                        u, p = creds
                        authed = (u == mp.source_username and p == mp.source_password)

                if not authed and mount.upper() != 'NEAREST':
                    writer.write(build_response_unauthorized(version))
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                    return

                writer.write(build_response_ok(version, is_source=True))
                await writer.drain()

                # Stream data from source to hub and mark online
                if mount.upper() == 'NEAREST':
                    # NEAREST cannot be a source
                    writer.close()
                    await writer.wait_closed()
                    return

                hub = await self.manager.get_hub(mp.name)
                self.manager.mark_source_online(db, mp, True)
                try:
                    while not reader.at_eof():
                        data = await reader.read(8192)
                        if not data:
                            break
                        hub.publish(data)
                        self.manager.touch_data(db, mp)
                except Exception:
                    pass
                finally:
                    self.manager.mark_source_online(db, mp, False)
                    writer.close()
                    await writer.wait_closed()
                    return
            else:
                writer.write(build_response_not_found(version))
                await writer.drain()
                writer.close()
                await writer.wait_closed()

    async def _serve_nearest(self, db: Session, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, version: str):
        # Wait for a GGA sentence from client to determine position
        lat, lon = None, None
        try:
            while not reader.at_eof():
                line = await reader.readline()
                if not line:
                    break
                if b"$GPGGA" in line or b"$GNGGA" in line:
                    try:
                        lat, lon = parse_gga(line.decode('ascii', errors='ignore'))
                    except Exception:
                        pass
                    break
        except Exception:
            pass
        # Choose nearest online mountpoint
        if lat is None or lon is None:
            # no position; cannot route
            writer.close()
            await writer.wait_closed()
            return
        mp = self.manager.nearest_online(db, lat, lon)
        if not mp:
            writer.close()
            await writer.wait_closed()
            return
        # Subscribe to hub and forward
        hub = await self.manager.get_hub(mp.name)
        async with hub.subscribe() as q:
            while not reader.at_eof():
                try:
                    data = await q.get()
                except asyncio.CancelledError:
                    break
                writer.write(data)
                try:
                    await writer.drain()
                except Exception:
                    break
        writer.close()
        await writer.wait_closed()


def parse_gga(sentence: str):
    # Very minimal NMEA GGA parser: $GxGGA,hhmmss,ddmm.mmmm,N,dddmm.mmmm,E,...
    parts = sentence.strip().split(',')
    if len(parts) < 6:
        raise ValueError('invalid GGA')
    lat_raw = parts[2]
    lat_hemi = parts[3]
    lon_raw = parts[4]
    lon_hemi = parts[5]
    def dm_to_deg(dm: str):
        if not dm or '.' not in dm:
            return None
        if len(dm) < 4:
            return None
        # lat: 2 deg digits; lon: 3
        # We'll infer by length
        dot = dm.find('.')
        deg_len = dot - 2
        deg = float(dm[:deg_len])
        minutes = float(dm[deg_len:])
        return deg + minutes/60.0
    lat = dm_to_deg(lat_raw) or 0.0
    lon = dm_to_deg(lon_raw) or 0.0
    if lat_hemi == 'S':
        lat = -lat
    if lon_hemi == 'W':
        lon = -lon
    return lat, lon
