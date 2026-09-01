from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DiscoveredAsset:
    asset_type: str
    external_id: str
    name: str
    hostname: Optional[str] = None
    ip_address: Optional[str] = None
    mac_address: Optional[str] = None
    status: Optional[str] = None
    parent_external_id: Optional[str] = None
    raw_data: dict = field(default_factory=dict)


class ConnectorError(Exception):
    pass


class BaseConnector:
    """Implementations return a flat list of DiscoveredAsset.

    Parent/child relationships are expressed via parent_external_id, which
    must match another asset's external_id discovered in the same poll
    (or an existing one already stored for this connector).
    """

    def __init__(self, base_url: str, verify_ssl: bool, credentials: dict):
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.credentials = credentials

    def poll(self) -> list[DiscoveredAsset]:
        raise NotImplementedError
