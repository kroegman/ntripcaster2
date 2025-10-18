from __future__ import annotations

import asyncio
import math
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional, Set, Tuple

from sqlalchemy.orm import Session

from ..models import Mountpoint


@dataclass
class StreamHub:
    subscribers: Set[asyncio.Queue] = field(default_factory=set)
    last_data_at: Optional[datetime] = None

    def publish(self, data: bytes):
        self.last_data_at = datetime.utcnow()
        for q in list(self.subscribers):
            if not q.full():
                q.put_nowait(data)

    @asynccontextmanager
    async def subscribe(self, max_queue=100) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=max_queue)
        self.subscribers.add(q)
        try:
            yield q
        finally:
            self.subscribers.discard(q)


class MountpointManager:
    def __init__(self):
        # in-memory hubs keyed by mountpoint name
        self._hubs: Dict[str, StreamHub] = {}
        # sources online set
        self._sources_online: Set[str] = set()
        # lock for creation
        self._lock = asyncio.Lock()

    async def get_hub(self, name: str) -> StreamHub:
        async with self._lock:
            hub = self._hubs.get(name)
            if not hub:
                hub = StreamHub()
                self._hubs[name] = hub
            return hub

    def mark_source_online(self, db: Session, mp: Mountpoint, online: bool):
        mp.online = online
        mp.last_data_at = datetime.utcnow() if online else mp.last_data_at
        db.add(mp)
        db.commit()
        if online:
            self._sources_online.add(mp.name)
        else:
            self._sources_online.discard(mp.name)

    def touch_data(self, db: Session, mp: Mountpoint):
        mp.last_data_at = datetime.utcnow()
        if not mp.online:
            mp.online = True
        db.add(mp)
        db.commit()

    def nearest_online(self, db: Session, lat: float, lon: float) -> Optional[Mountpoint]:
        # Haversine distance
        def distance_km(lat1, lon1, lat2, lon2):
            R = 6371.0
            phi1 = math.radians(lat1)
            phi2 = math.radians(lat2)
            dphi = math.radians(lat2 - lat1)
            dlambda = math.radians(lon2 - lon1)
            a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
            c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
            return R*c

        candidates = db.query(Mountpoint).filter(Mountpoint.online == True).all()  # noqa: E712
        best: Tuple[Optional[Mountpoint], float] = (None, float('inf'))
        for mp in candidates:
            if mp.latitude is None or mp.longitude is None:
                continue
            d = distance_km(lat, lon, mp.latitude, mp.longitude)
            if d < best[1]:
                best = (mp, d)
        return best[0]

    def offline_if_stale(self, db: Session, stale_after_seconds: int = 15):
        # Call periodically to mark sources offline if no data
        now = datetime.utcnow()
        for name, hub in list(self._hubs.items()):
            if hub.last_data_at and (now - hub.last_data_at) > timedelta(seconds=stale_after_seconds):
                mp = db.query(Mountpoint).filter_by(name=name).first()
                if mp and mp.online:
                    mp.online = False
                    db.add(mp)
                    db.commit()
                    self._sources_online.discard(name)
