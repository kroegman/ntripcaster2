from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, DateTime, ForeignKey, Boolean, Float, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_limit: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    mountpoints: Mapped[list["Mountpoint"]] = relationship(back_populates="owner")


class Mountpoint(Base):
    __tablename__ = "mountpoints"
    __table_args__ = (
        UniqueConstraint("name", name="uq_mountpoint_name"),
        UniqueConstraint("source_username", name="uq_mountpoint_src_username"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), default=None)

    # Credentials for base/source sending data into the caster (same for NTRIP v1/v2)
    source_username: Mapped[str] = mapped_column(String(64), nullable=False)
    source_password: Mapped[str] = mapped_column(String(128), nullable=False)

    # Protocol for source connection: 'ntrip' | 'tcp_raw'
    source_protocol: Mapped[str] = mapped_column(String(16), nullable=False, default="ntrip")

    # Optional dedicated TCP port for raw TCP/IP sources (only used when source_protocol == 'tcp_raw')
    tcp_port: Mapped[Optional[int]] = mapped_column(Integer, default=None)

    # GNSS base approximate location for NEAREST routing (lat/lon in degrees)
    latitude: Mapped[Optional[float]] = mapped_column(Float, default=None)
    longitude: Mapped[Optional[float]] = mapped_column(Float, default=None)

    # Status
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_data_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=None)

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    owner: Mapped[User] = relationship(back_populates="mountpoints")


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    mountpoint_id: Mapped[Optional[int]] = mapped_column(ForeignKey("mountpoints.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(16))  # 'source' or 'client'
    remote_addr: Mapped[Optional[str]] = mapped_column(String(64))
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    disconnected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
