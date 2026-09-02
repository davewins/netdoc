import datetime

import requests

from .base import BaseConnector, ConnectorError, DiscoveredAsset

# A peer with no handshake this recently is considered disconnected rather
# than "maybe still up" - WireGuard clients re-handshake at least this often
# whenever the tunnel is actually in use (persistent keepalive is commonly
# set well under this).
STALE_HANDSHAKE_SECONDS = 180


def _strip_cidr(address: str | None) -> str | None:
    if not address:
        return None
    return address.split("/")[0]


def _peer_status(client: dict) -> str:
    if not client.get("enabled", True):
        return "disabled"
    handshake = client.get("latestHandshakeAt")
    if not handshake:
        return "never-connected"
    try:
        ts = datetime.datetime.fromisoformat(handshake.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    age = (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds()
    return "connected" if age <= STALE_HANDSHAKE_SECONDS else "disconnected"


class WireguardConnector(BaseConnector):
    """Discovers VPN peers ("clients") from a wg-easy instance.

    WireGuard itself has no API - this talks to wg-easy's web UI backend
    instead, since that's what's actually running here. Targets wg-easy
    v14+ (the Nuxt-based rewrite, `ghcr.io/wg-easy/wg-easy`): login is
    POST /api/session with {username, password, remember}, peers are
    GET /api/client. The older pre-v14 Express build used a single global
    password and a different path (/api/wireguard/client) - if your
    instance 404s on /api/client, you're on that older version and this
    connector won't work against it as-is.

    Expected credentials dict: {"username": "...", "password": "..."} -
    whatever you log into the wg-easy web UI with.

    A peer's tunnel address (e.g. 10.8.0.2) is populated as ip_address.
    It won't correlate with that same device's real LAN presence (its
    Wi-Fi/Ethernet IP from Pi-hole or a scan) since those are two different
    addresses for one device and correlation only matches on an address
    both records agree on - a WireGuard peer will generally show up as its
    own standalone asset rather than merging into anything. That's fine;
    it's still useful as "is this peer currently connected" (see
    STALE_HANDSHAKE_SECONDS above), not as a cross-reference key.
    """

    def __init__(self, base_url, verify_ssl, credentials):
        super().__init__(base_url, verify_ssl, credentials)
        self._session = requests.Session()
        self._authenticated = False

    def _login(self):
        username = self.credentials.get("username")
        password = self.credentials.get("password")
        if not username or not password:
            raise ConnectorError("Wireguard (wg-easy) connector requires username and password")
        resp = self._session.post(
            f"{self.base_url}/api/session",
            json={"username": username, "password": password, "remember": False},
            verify=self.verify_ssl,
            timeout=15,
        )
        if resp.status_code != 200:
            raise ConnectorError(f"wg-easy login failed: {resp.status_code} {resp.text[:200]}")
        self._authenticated = True

    def _get(self, path: str):
        if not self._authenticated:
            self._login()
        resp = self._session.get(f"{self.base_url}{path}", verify=self.verify_ssl, timeout=15)
        if resp.status_code == 401:
            # Session cookie may have expired mid-poll - retry once.
            self._authenticated = False
            self._login()
            resp = self._session.get(f"{self.base_url}{path}", verify=self.verify_ssl, timeout=15)
        if resp.status_code != 200:
            raise ConnectorError(f"wg-easy API {path} returned {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def poll(self) -> list[DiscoveredAsset]:
        clients = self._get("/api/client")
        if isinstance(clients, dict):
            clients = clients.get("clients") or clients.get("data") or []

        assets: list[DiscoveredAsset] = []
        for client in clients:
            client_id = client.get("id")
            if not client_id:
                continue
            assets.append(
                DiscoveredAsset(
                    asset_type="wireguard_peer",
                    external_id=str(client_id),
                    name=client.get("name") or str(client_id),
                    ip_address=_strip_cidr(client.get("address")),
                    status=_peer_status(client),
                    raw_data=client,
                )
            )
        return assets
