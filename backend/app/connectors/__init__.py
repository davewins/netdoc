from .base import BaseConnector, ConnectorError, DiscoveredAsset
from .home_assistant import HomeAssistantConnector
from .kubernetes import KubernetesConnector
from .network_scan import NetworkScanConnector
from .pihole import PiholeConnector
from .portainer import PortainerConnector
from .proxmox import ProxmoxConnector
from .uptime_kuma import UptimeKumaConnector
from .wgdashboard import WGDashboardConnector
from .wireguard import WireguardConnector

CONNECTOR_TYPES = {
    "proxmox": ProxmoxConnector,
    "portainer": PortainerConnector,
    "pihole": PiholeConnector,
    "network_scan": NetworkScanConnector,
    "home_assistant": HomeAssistantConnector,
    "kubernetes": KubernetesConnector,
    "uptime_kuma": UptimeKumaConnector,
    "wireguard": WireguardConnector,
    "wgdashboard": WGDashboardConnector,
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
