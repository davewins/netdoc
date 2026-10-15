import re
from urllib.parse import urlparse

import requests

from .base import BaseConnector, ConnectorError, DiscoveredAsset

_UPTIME_UNITS = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}


def _parse_uptime(value: str | None) -> int | None:
    """RouterOS durations look like "1w2d3h4m5s" (any unit may be absent)."""
    if not value:
        return None
    parts = re.findall(r"(\d+)([wdhms])", value)
    if not parts:
        return None
    return sum(int(n) * _UPTIME_UNITS[u] for n, u in parts)


def _is_randomised_mac(mac: str) -> bool:
    """True for a locally-administered MAC (bit 1 of the first octet set).

    Phones and laptops use these as per-network "private" WiFi addresses, so
    they're not a stable identity for a device.
    """
    return bool(int(mac.split(":")[0], 16) & 0x02)


def _bool(value) -> bool:
    # The REST API returns every boolean as the string "true"/"false".
    return str(value).lower() == "true"


class RouterOSConnector(BaseConnector):
    """Discovers a MikroTik RouterOS switch/router via the v7 REST API.

    Needs RouterOS 7.1+ with the `www` (http) or `www-ssl` (https) service
    enabled under /ip/service; v6 has no REST API. Use a dedicated user in a
    read-only group (policy: read, api, rest-api) and restrict the service's
    `address` to the netdoc host. Plain http sends the Basic-auth password in
    cleartext - fine on a trusted LAN, otherwise use www-ssl (and set
    verify_ssl off for the self-signed cert, or install a real one).

    Endpoints used (all GET, HTTP Basic auth):
    - /rest/system/identity, /rest/system/resource - the switch itself
      (cpu-count, total-memory in bytes, uptime as "1w2d3h4m5s").
    - /rest/interface - supplies the switch's own MAC (the bridge's, falling
      back to the first interface with a MAC) so correlation merges it with
      the same box seen by the LAN scan / Pi-hole.
    - /rest/interface/bridge/host - the bridge FDB: which MAC was learned on
      which port. Entries with local=true are the switch's own MACs, skipped.
    - /rest/ip/arp and /rest/ip/dhcp-server/lease - MAC -> IP / hostname for
      those learned hosts. Both are optional (DHCP may not be served here).

    Learned hosts become "device" assets parented to the switch, with the
    port in raw_data and an initial "port:<name>" tag. A host is only
    reported if the FDB has it, so devices that are merely in ARP but not
    behind this switch are ignored. A host with a locally-administered
    (randomised) MAC is skipped unless ARP or a lease gives it an IP: with
    neither there's nothing to name it by and nothing stable to merge on,
    and the DHCP server's own record of it (e.g. Pi-hole's) is the better one.

    Expected credentials dict: {"username": "...", "password": "..."}.
    """

    def __init__(self, base_url, verify_ssl, credentials):
        super().__init__(base_url, verify_ssl, credentials)
        self._session = requests.Session()

    def _get(self, path: str, optional: bool = False):
        user = self.credentials.get("username")
        password = self.credentials.get("password")
        if not user or not password:
            raise ConnectorError("RouterOS connector requires username and password")
        try:
            resp = self._session.get(
                f"{self.base_url}/rest{path}",
                auth=(user, password),
                verify=self.verify_ssl,
                timeout=15,
            )
        except requests.RequestException as exc:
            if optional:
                return []
            raise ConnectorError(f"RouterOS {path} unreachable: {exc}") from exc
        if resp.status_code != 200:
            if optional:
                return []
            raise ConnectorError(f"RouterOS API {path} returned {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def poll(self) -> list[DiscoveredAsset]:
        identity = self._get("/system/identity")
        resource = self._get("/system/resource")
        interfaces = self._get("/interface")

        switch_name = identity.get("name") or "routeros"
        switch_ip = urlparse(self.base_url).hostname

        # Prefer the bridge's MAC - that's what the switch sources traffic
        # from, so it's what shows up in ARP/scan data for its management IP.
        switch_mac = next(
            (i.get("mac-address") for i in interfaces if i.get("type") == "bridge" and i.get("mac-address")),
            None,
        ) or next((i.get("mac-address") for i in interfaces if i.get("mac-address")), None)
        switch_id = f"switch/{switch_mac or switch_name}"

        total_hdd = resource.get("total-hdd-size")
        assets = [
            DiscoveredAsset(
                asset_type="device",
                external_id=switch_id,
                name=switch_name,
                hostname=switch_name,
                ip_address=switch_ip,
                mac_address=switch_mac,
                status="running",
                cpu_cores=int(resource["cpu-count"]) if resource.get("cpu-count") else None,
                memory_mb=int(resource["total-memory"]) // (1024 * 1024) if resource.get("total-memory") else None,
                disk_gb=round(int(total_hdd) / 1024**3, 2) if total_hdd else None,
                uptime_seconds=_parse_uptime(resource.get("uptime")),
                raw_data={
                    "board_name": resource.get("board-name"),
                    "version": resource.get("version"),
                    "architecture": resource.get("architecture-name"),
                    "interfaces": [
                        {
                            "name": i.get("name"),
                            "type": i.get("type"),
                            "running": _bool(i.get("running")),
                            "disabled": _bool(i.get("disabled")),
                            "mac": i.get("mac-address"),
                        }
                        for i in interfaces
                    ],
                },
                initial_tags=["mikrotik", "switch"],
            )
        ]

        arp_ip = {}
        for e in self._get("/ip/arp", optional=True):
            mac, ip = e.get("mac-address"), e.get("address")
            if mac and ip:
                arp_ip[mac.upper()] = ip
        lease_name = {}
        lease_ip = {}
        for e in self._get("/ip/dhcp-server/lease", optional=True):
            mac = (e.get("mac-address") or "").upper()
            if not mac:
                continue
            if e.get("host-name"):
                lease_name[mac] = e["host-name"]
            if e.get("address"):
                lease_ip[mac] = e["address"]

        seen = set()
        for host in self._get("/interface/bridge/host"):
            mac = (host.get("mac-address") or "").upper()
            if not mac or _bool(host.get("local")) or mac in seen or mac == (switch_mac or "").upper():
                continue
            seen.add(mac)
            ip = arp_ip.get(mac) or lease_ip.get(mac)
            if not ip and _is_randomised_mac(mac):
                continue
            name = lease_name.get(mac) or ip or mac
            port = host.get("on-interface")
            assets.append(
                DiscoveredAsset(
                    asset_type="device",
                    external_id=f"host/{mac}",
                    name=name,
                    hostname=lease_name.get(mac),
                    ip_address=ip,
                    mac_address=mac,
                    parent_external_id=switch_id,
                    raw_data={
                        "switch": switch_name,
                        "port": port,
                        "bridge": host.get("bridge"),
                        "vid": host.get("vid"),
                    },
                    initial_tags=[f"port:{port}"] if port else [],
                )
            )

        return assets
