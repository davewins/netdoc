import re

import requests

from .base import BaseConnector, ConnectorError, DiscoveredAsset

MAC_RE = re.compile(r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})")


class ProxmoxConnector(BaseConnector):
    """Discovers nodes, QEMU VMs and LXC containers from a Proxmox VE cluster.

    Expected credentials dict:
      {"token_name": "root@pam!netdoc", "token_value": "<uuid>"}
    Create the token in Proxmox under Datacenter > Permissions > API Tokens
    (a read-only "PVEAuditor" role is enough for discovery).
    """

    def _headers(self) -> dict:
        token_name = self.credentials.get("token_name")
        token_value = self.credentials.get("token_value")
        if not token_name or not token_value:
            raise ConnectorError("Proxmox connector requires token_name and token_value")
        return {"Authorization": f"PVEAPIToken={token_name}={token_value}"}

    def _get(self, path: str):
        url = f"{self.base_url}/api2/json{path}"
        resp = requests.get(url, headers=self._headers(), verify=self.verify_ssl, timeout=15)
        if resp.status_code != 200:
            raise ConnectorError(f"Proxmox API {path} returned {resp.status_code}: {resp.text[:200]}")
        return resp.json().get("data", [])

    def _try_get(self, path: str):
        """Like _get, but swallows failures - used for best-effort detail
        calls (guest agent, interfaces) that routinely fail on stopped or
        agent-less guests and shouldn't abort the whole poll."""
        try:
            return self._get(path)
        except ConnectorError:
            return None

    @staticmethod
    def _parse_tags(raw_tags: str | None) -> list[str]:
        if not raw_tags:
            return []
        return [t.strip() for t in re.split(r"[;,]", raw_tags) if t.strip()]

    @staticmethod
    def _mac_from_config(config: dict) -> str | None:
        for key, value in config.items():
            if not key.startswith("net") or not isinstance(value, str):
                continue
            match = MAC_RE.search(value)
            if match:
                return match.group(1)
        return None

    def _guest_agent_ip(self, node: str, vmid: int) -> str | None:
        data = self._try_get(f"/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces")
        if not data:
            return None
        for iface in data.get("result", []):
            if iface.get("name") in ("lo", "loopback"):
                continue
            for addr in iface.get("ip-addresses", []):
                if addr.get("ip-address-type") == "ipv4":
                    return addr["ip-address"]
        return None

    def _lxc_interface_ip(self, node: str, vmid: int) -> str | None:
        data = self._try_get(f"/nodes/{node}/lxc/{vmid}/interfaces")
        if not data:
            return None
        for iface in data:
            if iface.get("name") == "lo":
                continue
            inet = iface.get("inet")
            if inet:
                return inet.split("/")[0]
        return None

    def poll(self) -> list[DiscoveredAsset]:
        assets: list[DiscoveredAsset] = []

        nodes = self._get("/nodes")
        for node in nodes:
            node_name = node["node"]
            maxmem = node.get("maxmem")
            assets.append(
                DiscoveredAsset(
                    asset_type="proxmox_node",
                    external_id=node_name,
                    name=node_name,
                    status=node.get("status"),
                    cpu_cores=node.get("maxcpu"),
                    memory_mb=int(maxmem / 1024 / 1024) if maxmem else None,
                    disk_gb=round(node["maxdisk"] / 1024**3, 1) if node.get("maxdisk") else None,
                    uptime_seconds=node.get("uptime"),
                    raw_data=node,
                )
            )

            for vm in self._get(f"/nodes/{node_name}/qemu"):
                vmid = vm["vmid"]
                config = self._try_get(f"/nodes/{node_name}/qemu/{vmid}/config") or {}
                mac = self._mac_from_config(config)
                ip = self._guest_agent_ip(node_name, vmid) if vm.get("status") == "running" else None
                maxmem = vm.get("maxmem")

                assets.append(
                    DiscoveredAsset(
                        asset_type="vm",
                        external_id=f"{node_name}/qemu/{vmid}",
                        name=vm.get("name") or f"vm-{vmid}",
                        status=vm.get("status"),
                        parent_external_id=node_name,
                        ip_address=ip,
                        mac_address=mac,
                        cpu_cores=vm.get("cpus") or config.get("cores"),
                        memory_mb=int(maxmem / 1024 / 1024) if maxmem else None,
                        disk_gb=round(vm["maxdisk"] / 1024**3, 1) if vm.get("maxdisk") else None,
                        uptime_seconds=vm.get("uptime"),
                        initial_tags=self._parse_tags(vm.get("tags") or config.get("tags")),
                        raw_data={**vm, "config": config},
                    )
                )

            for ct in self._get(f"/nodes/{node_name}/lxc"):
                vmid = ct["vmid"]
                config = self._try_get(f"/nodes/{node_name}/lxc/{vmid}/config") or {}
                mac = self._mac_from_config(config)
                ip = self._lxc_interface_ip(node_name, vmid) if ct.get("status") == "running" else None
                maxmem = ct.get("maxmem")

                assets.append(
                    DiscoveredAsset(
                        asset_type="lxc",
                        external_id=f"{node_name}/lxc/{vmid}",
                        name=ct.get("name") or f"ct-{vmid}",
                        status=ct.get("status"),
                        parent_external_id=node_name,
                        ip_address=ip,
                        mac_address=mac,
                        cpu_cores=ct.get("cpus") or config.get("cores"),
                        memory_mb=int(maxmem / 1024 / 1024) if maxmem else None,
                        disk_gb=round(ct["maxdisk"] / 1024**3, 1) if ct.get("maxdisk") else None,
                        uptime_seconds=ct.get("uptime"),
                        initial_tags=self._parse_tags(ct.get("tags") or config.get("tags")),
                        raw_data={**ct, "config": config},
                    )
                )

        return assets
