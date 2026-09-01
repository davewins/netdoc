import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


def utcnow():
    return datetime.datetime.utcnow()


class Connector(Base):
    __tablename__ = "connectors"

    id = Column(Integer, primary_key=True)
    type = Column(String, nullable=False)  # proxmox | portainer | pihole
    name = Column(String, nullable=False)
    base_url = Column(String, nullable=False)
    verify_ssl = Column(Boolean, default=False)
    encrypted_credentials = Column(Text)  # JSON blob, encrypted as a whole
    enabled = Column(Boolean, default=True)
    poll_interval_seconds = Column(Integer, nullable=True)
    last_polled_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    assets = relationship("Asset", back_populates="connector", cascade="all, delete-orphan")


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("connector_id", "asset_type", "external_id", name="uq_asset_source"),
    )

    id = Column(Integer, primary_key=True)
    connector_id = Column(Integer, ForeignKey("connectors.id"), nullable=True)
    parent_id = Column(Integer, ForeignKey("assets.id"), nullable=True)

    asset_type = Column(String, nullable=False)  # proxmox_node, vm, lxc, docker_host, docker_container, dns_record, host, device
    external_id = Column(String, nullable=True)  # id on the source system; null for manual assets
    source = Column(String, default="manual")  # discovered | manual

    name = Column(String, nullable=False)
    hostname = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    mac_address = Column(String, nullable=True)
    status = Column(String, nullable=True)

    raw_data = Column(JSON, nullable=True)

    notes = Column(Text, nullable=True)
    tags = Column(JSON, default=list)
    ports = Column(JSON, default=list)  # [{"port": 443, "protocol": "tcp", "description": "https"}]
    services = Column(JSON, default=list)  # ["acme", "nginx-proxy-manager"]

    first_seen_at = Column(DateTime, default=utcnow)
    last_seen_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    connector = relationship("Connector", back_populates="assets")
    parent = relationship("Asset", remote_side=[id], backref="children")
    credentials = relationship("Credential", back_populates="asset", cascade="all, delete-orphan")


class Credential(Base):
    __tablename__ = "credentials"

    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    label = Column(String, nullable=False)
    username = Column(String, nullable=True)
    encrypted_secret = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    asset = relationship("Asset", back_populates="credentials")
