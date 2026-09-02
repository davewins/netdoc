import requests

from .base import BaseConnector, ConnectorError, DiscoveredAsset


class PiholeConnector(BaseConnector):
    """Discovers network devices seen by Pi-hole (v6 API) and its local DNS records.

    Expected credentials dict: {"password": "..."} (an application password
    or the web UI password).

    Pi-hole's API surface changed a lot between v5 and v6 - this targets the
    v6 FTL-based API (/api/...). If your Pi-hole is still on v5, this
    connector's endpoints won't match; the older API lived under
    /admin/api.php?...&auth=<token>.
    """

    def __init__(self, base_url, verify_ssl, credentials):
        super().__init__(base_url, verify_ssl, credentials)
        self._sid = None

    def _login(self):
        password = self.credentials.get("password")
        if not password:
            raise ConnectorError("Pi-hole connector requires a password")
        resp = requests.post(
            f"{self.base_url}/api/auth",
            json={"password": password},
            verify=self.verify_ssl,
            timeout=15,
        )
        if resp.status_code != 200:
            raise ConnectorError(f"Pi-hole auth failed: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        self._sid = data.get("session", {}).get("sid")
        if not self._sid:
            raise ConnectorError("Pi-hole auth did not return a session id")

    def _get(self, path: str):
        if not self._sid:
            self._login()
        resp = requests.get(
            f"{self.base_url}{path}",
            headers={"sid": self._sid},
            verify=self.verify_ssl,
            timeout=15,
        )
        if resp.status_code != 200:
            raise ConnectorError(f"Pi-hole API {path} returned {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def poll(self) -> list[DiscoveredAsset]:
        assets: list[DiscoveredAsset] = []

        devices_resp = self._get("/api/network/devices")
        for device in devices_resp.get("devices", []):
            ips = device.get("ips", [])
            primary_ip = ips[0].get("ip") if ips else None
            primary_name = next((ip.get("name") for ip in ips if ip.get("name")), None)
            mac = device.get("hwaddr")
            external_id = mac or primary_ip or str(device.get("id"))
            if not external_id:
                continue

            assets.append(
                DiscoveredAsset(
                    asset_type="device",
                    external_id=external_id,
                    name=primary_name or external_id,
                    hostname=primary_name,
                    ip_address=primary_ip,
                    mac_address=mac,
                    raw_data=device,
                )
            )

        try:
            config = self._get("/api/config").get("config", {})
        except ConnectorError:
            config = {}

        for entry in config.get("dns", {}).get("hosts", []):
            parts = entry.split()
            if len(parts) < 2:
                continue
            ip, hostname = parts[0], parts[1]
            assets.append(
                DiscoveredAsset(
                    asset_type="dns_record",
                    external_id=f"host/{hostname}",
                    name=hostname,
                    hostname=hostname,
                    ip_address=ip,
                    raw_data={"raw_entry": entry},
                )
            )

        # Static DHCP reservations - "MAC,IP,hostname[,lease-time]". These are
        # the strongest link back to Proxmox: a VM's NIC MAC reserved to a
        # fixed IP here will auto-merge with the Proxmox-discovered VM.
        for entry in config.get("dhcp", {}).get("hosts", []):
            parts = entry.split(",")
            if len(parts) < 2:
                continue
            mac, ip = parts[0].strip(), parts[1].strip()
            raw_hostname = parts[2].strip() if len(parts) > 2 else ""
            # Pi-hole writes a literal "*" placeholder when no hostname is set
            # (it still needs the field position for an optional lease-time after it).
            hostname = raw_hostname if raw_hostname and raw_hostname != "*" else ip
            assets.append(
                DiscoveredAsset(
                    asset_type="dhcp_reservation",
                    external_id=f"reservation/{mac}",
                    name=hostname,
                    hostname=hostname if hostname != ip else None,
                    ip_address=ip,
                    mac_address=mac,
                    raw_data={"raw_entry": entry},
                )
            )

        try:
            leases_resp = self._get("/api/dhcp/leases")
            for lease in leases_resp.get("leases", []):
                mac = lease.get("hwaddr")
                ip = lease.get("ip")
                if not mac or not ip:
                    continue
                # dnsmasq's lease file (and Pi-hole's API mirroring it) uses a literal
                # "*" placeholder when the client didn't send a hostname.
                lease_name = lease.get("name")
                if lease_name == "*":
                    lease_name = None
                assets.append(
                    DiscoveredAsset(
                        asset_type="dhcp_reservation",
                        external_id=f"lease/{mac}",
                        name=lease_name or ip,
                        hostname=lease_name,
                        ip_address=ip,
                        mac_address=mac,
                        status="active-lease",
                        raw_data=lease,
                    )
                )
        except ConnectorError:
            pass

        return assets
