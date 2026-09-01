import requests

from .base import BaseConnector, ConnectorError, DiscoveredAsset


class PortainerConnector(BaseConnector):
    """Discovers environments (endpoints) and their Docker containers.

    Expected credentials dict, either:
      {"api_key": "ptr_..."}
    or:
      {"username": "admin", "password": "..."}
    """

    def __init__(self, base_url, verify_ssl, credentials):
        super().__init__(base_url, verify_ssl, credentials)
        self._jwt = None

    def _headers(self) -> dict:
        if self.credentials.get("api_key"):
            return {"X-API-Key": self.credentials["api_key"]}
        if not self._jwt:
            self._login()
        return {"Authorization": f"Bearer {self._jwt}"}

    def _login(self):
        username = self.credentials.get("username")
        password = self.credentials.get("password")
        if not username or not password:
            raise ConnectorError("Portainer connector requires api_key, or username and password")
        resp = requests.post(
            f"{self.base_url}/api/auth",
            json={"username": username, "password": password},
            verify=self.verify_ssl,
            timeout=15,
        )
        if resp.status_code != 200:
            raise ConnectorError(f"Portainer auth failed: {resp.status_code} {resp.text[:200]}")
        self._jwt = resp.json()["jwt"]

    def _get(self, path: str):
        resp = requests.get(
            f"{self.base_url}{path}", headers=self._headers(), verify=self.verify_ssl, timeout=15
        )
        if resp.status_code != 200:
            raise ConnectorError(f"Portainer API {path} returned {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def poll(self) -> list[DiscoveredAsset]:
        assets: list[DiscoveredAsset] = []

        endpoints = self._get("/api/endpoints")
        for ep in endpoints:
            ep_id = ep["Id"]
            ep_name = ep["Name"]
            assets.append(
                DiscoveredAsset(
                    asset_type="docker_host",
                    external_id=f"endpoint/{ep_id}",
                    name=ep_name,
                    status="up" if ep.get("Status") == 1 else "down",
                    raw_data=ep,
                )
            )

            try:
                containers = self._get(f"/api/endpoints/{ep_id}/docker/containers/json?all=true")
            except ConnectorError:
                continue

            for c in containers:
                name = (c.get("Names") or ["/unknown"])[0].lstrip("/")
                ports = c.get("Ports", [])
                assets.append(
                    DiscoveredAsset(
                        asset_type="docker_container",
                        external_id=f"endpoint/{ep_id}/container/{c['Id']}",
                        name=name,
                        status=c.get("State"),
                        parent_external_id=f"endpoint/{ep_id}",
                        raw_data={**c, "_derived_ports": ports},
                    )
                )

        return assets
