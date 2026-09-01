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


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    connector_id: Optional[int]
    parent_id: Optional[int]
    asset_type: str
    external_id: Optional[str]
    source: str
    name: str
    hostname: Optional[str]
    ip_address: Optional[str]
    mac_address: Optional[str]
    status: Optional[str]
    raw_data: Optional[dict] = None
    notes: Optional[str]
    tags: list[str] = []
    ports: list[dict] = []
    services: list[str] = []
    first_seen_at: datetime.datetime
    last_seen_at: datetime.datetime
    updated_at: datetime.datetime
    credentials: list[CredentialOut] = []


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
    last_polled_at: Optional[datetime.datetime]
    last_error: Optional[str]
    created_at: datetime.datetime
