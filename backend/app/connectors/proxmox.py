import requests

from .base import BaseConnector, ConnectorError, DiscoveredAsset


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

    def poll(self) -> list[DiscoveredAsset]:
        assets: list[DiscoveredAsset] = []

        nodes = self._get("/nodes")
        for node in nodes:
            node_name = node["node"]
            assets.append(
                DiscoveredAsset(
                    asset_type="proxmox_node",
                    external_id=node_name,
                    name=node_name,
                    status=node.get("status"),
                    raw_data=node,
                )
            )

            for vm in self._get(f"/nodes/{node_name}/qemu"):
                assets.append(
                    DiscoveredAsset(
                        asset_type="vm",
                        external_id=f"{node_name}/qemu/{vm['vmid']}",
                        name=vm.get("name") or f"vm-{vm['vmid']}",
                        status=vm.get("status"),
                        parent_external_id=node_name,
                        raw_data=vm,
                    )
                )

            for ct in self._get(f"/nodes/{node_name}/lxc"):
                assets.append(
                    DiscoveredAsset(
                        asset_type="lxc",
                        external_id=f"{node_name}/lxc/{ct['vmid']}",
                        name=ct.get("name") or f"ct-{ct['vmid']}",
                        status=ct.get("status"),
                        parent_external_id=node_name,
                        raw_data=ct,
                    )
                )

        return assets
