import re
from urllib.parse import urlparse

import requests

from .base import BaseConnector, ConnectorError, DiscoveredAsset

# Substring -> service label, checked against the container's image name.
SERVICE_HINTS = {
    "traefik": "traefik",
    "nginx-proxy-manager": "nginx-proxy-manager",
    "nginxproxymanager": "nginx-proxy-manager",
    "caddy": "caddy",
    "acme.sh": "acme",
    "certbot": "acme",
    "pihole": "pihole",
    "homeassistant": "home-assistant",
    "home-assistant": "home-assistant",
    "portainer": "portainer",
    "watchtower": "watchtower",
    "postgres": "postgres",
    "mysql": "mysql",
    "mariadb": "mariadb",
    "redis": "redis",
    "plex": "plex",
    "jellyfin": "jellyfin",
    "grafana": "grafana",
    "prometheus": "prometheus",
    "vaultwarden": "vaultwarden",
}


def _guess_services(image: str | None) -> list[str]:
    if not image:
        return []
    image_lower = image.lower()
    return sorted({label for needle, label in SERVICE_HINTS.items() if needle in image_lower})


class PortainerConnector(BaseConnector):
    """Discovers environments (endpoints), stacks and Docker containers.

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

    @staticmethod
    def _primary_network(container: dict) -> tuple[str | None, str | None]:
        networks = (container.get("NetworkSettings") or {}).get("Networks") or {}
        for net in networks.values():
            ip = net.get("IPAddress")
            mac = net.get("MacAddress")
            if ip:
                return ip, mac or None
        return None, None

    def _host_address(self, ep: dict) -> str | None:
        """Address other devices on the LAN can reach this endpoint's
        published container ports on, for building clickable service URLs.

        Portainer's own UI uses the same field (PublicURL, an IP/FQDN with
        no scheme or port) for exactly this purpose, but most homelab setups
        never fill it in. A unix://-socket endpoint (the default for a
        single-node install with no agent) means Portainer is talking to the
        Docker engine on its own host, so this connector's own configured
        address is a reliable fallback there. A tcp:// agent/remote endpoint
        parses its host out of URL directly; there's no way to guess one for
        Windows named-pipe (npipe://) agents.
        """
        public_url = (ep.get("PublicURL") or "").strip()
        if public_url:
            return public_url
        url = ep.get("URL") or ""
        match = re.match(r"^tcp://([^:/]+)", url)
        if match:
            return match.group(1)
        if url.startswith("unix://"):
            return urlparse(self.base_url).hostname
        return None

    @staticmethod
    def _ports_from_docker(container: dict, host_address: str | None) -> list[dict]:
        entries = []
        for p in container.get("Ports", []):
            public_port = p.get("PublicPort")
            port = public_port or p.get("PrivatePort")
            if not port:
                continue
            entry = {
                "port": port,
                "protocol": p.get("Type", "tcp"),
                "description": f"container port {p.get('PrivatePort')}",
            }
            # Only a host-published port is actually reachable from the LAN -
            # an unpublished container-internal port stays URL-less.
            if public_port and host_address and entry["protocol"] == "tcp":
                scheme = "https" if public_port in (443, 8443) else "http"
                entry["url"] = f"{scheme}://{host_address}:{public_port}"
            entries.append(entry)
        # de-dupe while preserving order
        seen = set()
        deduped = []
        for e in entries:
            key = (e["port"], e["protocol"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(e)
        return deduped

    def _stack_name_for(self, container: dict) -> str | None:
        labels = container.get("Labels") or {}
        return labels.get("com.docker.compose.project") or labels.get("com.docker.stack.namespace")

    def poll(self) -> list[DiscoveredAsset]:
        assets: list[DiscoveredAsset] = []

        endpoints = self._get("/api/endpoints")
        for ep in endpoints:
            ep_id = ep["Id"]
            ep_name = ep["Name"]
            host_address = self._host_address(ep)
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
                stacks = [s for s in self._get("/api/stacks") if s.get("EndpointId") == ep_id]
            except ConnectorError:
                stacks = []
            stack_name_to_external_id = {}
            for stack in stacks:
                stack_external_id = f"endpoint/{ep_id}/stack/{stack['Id']}"
                stack_name_to_external_id[stack["Name"]] = stack_external_id
                assets.append(
                    DiscoveredAsset(
                        asset_type="docker_stack",
                        external_id=stack_external_id,
                        name=stack["Name"],
                        status=stack.get("Status") and "active" or None,
                        parent_external_id=f"endpoint/{ep_id}",
                        raw_data=stack,
                    )
                )

            try:
                containers = self._get(f"/api/endpoints/{ep_id}/docker/containers/json?all=true")
            except ConnectorError:
                continue

            for c in containers:
                name = (c.get("Names") or ["/unknown"])[0].lstrip("/")
                ip, mac = self._primary_network(c)
                stack_name = self._stack_name_for(c)
                parent_external_id = stack_name_to_external_id.get(stack_name, f"endpoint/{ep_id}")

                cpu_cores = None
                memory_mb = None
                inspect = None
                try:
                    inspect = self._get(f"/api/endpoints/{ep_id}/docker/containers/{c['Id']}/json")
                except ConnectorError:
                    pass
                if inspect:
                    host_config = inspect.get("HostConfig", {})
                    nano_cpus = host_config.get("NanoCpus")
                    cpu_quota = host_config.get("CpuQuota")
                    cpu_period = host_config.get("CpuPeriod") or 100000
                    if nano_cpus:
                        cpu_cores = round(nano_cpus / 1_000_000_000, 2)
                    elif cpu_quota and cpu_quota > 0:
                        cpu_cores = round(cpu_quota / cpu_period, 2)
                    mem_bytes = host_config.get("Memory")
                    if mem_bytes:
                        memory_mb = int(mem_bytes / 1024 / 1024)

                assets.append(
                    DiscoveredAsset(
                        asset_type="docker_container",
                        external_id=f"endpoint/{ep_id}/container/{c['Id']}",
                        name=name,
                        status=c.get("State"),
                        parent_external_id=parent_external_id,
                        ip_address=ip,
                        mac_address=mac,
                        cpu_cores=cpu_cores,
                        memory_mb=memory_mb,
                        initial_ports=self._ports_from_docker(c, host_address),
                        initial_services=_guess_services(c.get("Image")),
                        raw_data={**c, "inspect": inspect},
                    )
                )

        return assets
