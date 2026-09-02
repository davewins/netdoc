import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
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
    # Free-text label for which physical location this connector talks to
    # (e.g. "Teignmouth") - unset for your main/local network. Purely
    # organizational: every asset discovered through this connector
    # inherits it (see Asset.site below), nothing else treats it specially.
    site = Column(String, nullable=True)
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
    canonical_asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True)

    # proxmox_node, vm, lxc, docker_host, docker_stack, docker_container,
    # dns_record, dhcp_reservation, device, host
    asset_type = Column(String, nullable=False)
    external_id = Column(String, nullable=True)  # id on the source system; null for manual assets
    source = Column(String, default="manual")  # discovered | manual

    name = Column(String, nullable=False)
    hostname = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    mac_address = Column(String, nullable=True)
    status = Column(String, nullable=True)

    cpu_cores = Column(Integer, nullable=True)
    memory_mb = Column(Integer, nullable=True)
    disk_gb = Column(Float, nullable=True)
    uptime_seconds = Column(Integer, nullable=True)

    raw_data = Column(JSON, nullable=True)

    notes = Column(Text, nullable=True)
    tags = Column(JSON, default=list)
    ports = Column(JSON, default=list)  # [{"port": 443, "protocol": "tcp", "description": "https"}]
    services = Column(JSON, default=list)  # ["acme", "nginx-proxy-manager"]

    first_seen_at = Column(DateTime, default=utcnow)
    last_seen_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    connector = relationship("Connector", back_populates="assets")

    @property
    def site(self) -> str | None:
        return self.connector.site if self.connector else None

    parent = relationship("Asset", remote_side=[id], foreign_keys=[parent_id], backref="children")
    canonical_asset = relationship(
        "Asset", remote_side=[id], foreign_keys=[canonical_asset_id], backref="merged_assets"
    )
    credentials = relationship("Credential", back_populates="asset", cascade="all, delete-orphan")


class AssetLink(Base):
    """Records a same-host relationship between two assets discovered from
    different sources (e.g. a Pi-hole DHCP reservation and a Proxmox VM).

    reason: "mac" (auto-confirmed) or "ip" (needs confirmation, since IPs
    get reassigned by DHCP but MACs don't).
    status: "confirmed" | "pending" | "rejected".
    """

    __tablename__ = "asset_links"
    __table_args__ = (UniqueConstraint("primary_asset_id", "secondary_asset_id", name="uq_asset_link_pair"),)

    id = Column(Integer, primary_key=True)
    primary_asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    secondary_asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)
    reason = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    primary_asset = relationship("Asset", foreign_keys=[primary_asset_id])
    secondary_asset = relationship("Asset", foreign_keys=[secondary_asset_id])


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
