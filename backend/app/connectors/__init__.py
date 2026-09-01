from .base import BaseConnector, ConnectorError, DiscoveredAsset
from .network_scan import NetworkScanConnector
from .pihole import PiholeConnector
from .portainer import PortainerConnector
from .proxmox import ProxmoxConnector

CONNECTOR_TYPES = {
    "proxmox": ProxmoxConnector,
    "portainer": PortainerConnector,
    "pihole": PiholeConnector,
    "network_scan": NetworkScanConnector,
}


def build_connector(connector_type: str, base_url: str, verify_ssl: bool, credentials: dict) -> BaseConnector:
    cls = CONNECTOR_TYPES.get(connector_type)
    if not cls:
        raise ConnectorError(f"Unknown connector type: {connector_type}")
    return cls(base_url, verify_ssl, credentials)


__all__ = [
    "BaseConnector",
    "ConnectorError",
    "DiscoveredAsset",
    "CONNECTOR_TYPES",
    "build_connector",
]
