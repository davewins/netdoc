import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class PortEntry(BaseModel):
    port: int
    protocol: str = "tcp"
    description: str = ""


class CredentialIn(BaseModel):
    label: str
    username: Optional[str] = None
    secret: Optional[str] = None
    notes: Optional[str] = None


class CredentialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_id: int
    label: str
    username: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class CredentialRevealed(CredentialOut):
    secret: Optional[str] = None


class LinkedAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_type: str
    name: str
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    connector_id: Optional[int] = None
    link_reason: Optional[str] = None
    link_status: Optional[str] = None


class ChildAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_type: str
    name: str
    status: Optional[str] = None


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    connector_id: Optional[int]
    parent_id: Optional[int]
    canonical_asset_id: Optional[int] = None
    asset_type: str
    external_id: Optional[str]
    source: str
    name: str
    hostname: Optional[str]
    ip_address: Optional[str]
    mac_address: Optional[str]
    status: Optional[str]
    site: Optional[str] = None
    cpu_cores: Optional[int] = None
    memory_mb: Optional[int] = None
    disk_gb: Optional[float] = None
    uptime_seconds: Optional[int] = None
    raw_data: Optional[dict] = None
    notes: Optional[str]
    tags: list[str] = []
    ports: list[dict] = []
    services: list[str] = []
    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime
    updated_at: datetime.datetime
    credentials: list[CredentialOut] = []
    linked_assets: list[LinkedAssetOut] = []
    children: list[ChildAssetOut] = []


class AssetEnrichmentIn(BaseModel):
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    ports: Optional[list[PortEntry]] = None
    services: Optional[list[str]] = None


class AssetCreateManual(BaseModel):
    asset_type: str
    name: str
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    notes: Optional[str] = None
    tags: list[str] = []
    services: list[str] = []


class ConnectorIn(BaseModel):
    type: str
    name: str
    base_url: str
    verify_ssl: bool = False
    enabled: bool = True
    poll_interval_seconds: Optional[int] = None
    site: Optional[str] = None
    credentials: dict[str, Any] = {}


class ConnectorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    name: str
    base_url: str
    verify_ssl: bool
    enabled: bool
    poll_interval_seconds: Optional[int]
    site: Optional[str] = None
    last_polled_at: Optional[datetime.datetime]
    last_error: Optional[str]
    created_at: datetime.datetime


class LinkAssetSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    asset_type: str
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None


class LinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reason: str
    status: str
    created_at: datetime.datetime
    primary_asset: LinkAssetSummary
    secondary_asset: LinkAssetSummary


class TopologyNode(BaseModel):
    id: int
    name: str
    asset_type: str
    status: Optional[str] = None
    ip_address: Optional[str] = None
    site: Optional[str] = None
    parent_id: Optional[int] = None


class TopologyEdge(BaseModel):
    source: int
    target: int
    kind: str  # "parent" | "subnet"


class TopologyOut(BaseModel):
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]


class ReportConnectorSummary(BaseModel):
    id: int
    name: str
    type: str
    site: Optional[str] = None
    enabled: bool
    last_polled_at: Optional[datetime.datetime] = None
    last_error: Optional[str] = None


class ReportAssetSummary(BaseModel):
    id: int
    name: str
    asset_type: str
    status: Optional[str] = None
    site: Optional[str] = None


class ReportOut(BaseModel):
    generated_at: datetime.datetime
    total_assets: int
    by_type: dict[str, int]
    by_site: dict[str, int]
    connectors: list[ReportConnectorSummary]
    down_assets: list[ReportAssetSummary]
    pending_link_count: int
    narrative: list[str]
