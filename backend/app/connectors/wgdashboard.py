import requests

from .base import BaseConnector, ConnectorError, DiscoveredAsset


def _strip_cidr(address: str | None) -> str | None:
    if not address:
        return None
    return address.split("/")[0]


def _peer_status(peer: dict, restricted: bool) -> str:
    if restricted:
        return "disabled"
    if not peer.get("latest_handshake") or peer.get("latest_handshake") == "No Handshake":
        return "never-connected"
    # WGDashboard itself already computes running/stopped server-side (a
    # peer counts as "running" if its handshake is under 3 minutes old) -
    # no need to parse latest_handshake's "H:MM:SS" duration string
    # ourselves, unlike wg-easy's ISO timestamp in the sibling connector.
    return "connected" if peer.get("status") == "running" else "disconnected"


class WGDashboardConnector(BaseConnector):
    """Discovers VPN peers from a WGDashboard instance (donaldzou/WGDashboard,
    now WGDashboard/WGDashboard) - a different self-hosted WireGuard UI from
    wg-easy (see the sibling `wireguard.py`), with its own unrelated API.
    Both connector types produce the same `wireguard_peer` asset_type and
    status vocabulary so they're interchangeable from netdoc's point of
    view; which one to use depends purely on which UI a given WireGuard
    instance actually runs.

    Endpoints (from WGDashboard's Flask backend, src/dashboard.py):
    - POST /api/authenticate with {"username", "password"} - sets a session
      cookie on success. Always returns HTTP 200; success/failure is in the
      JSON body's "status" boolean, not the status code, and login always
      reports success if the instance has "Require Authentication" turned
      off in its own settings, so this works either way. TOTP-protected
      accounts aren't supported (no way to supply a live code from a poll
      loop) - use an account with TOTP disabled.
    - GET /api/getWireguardConfigurations - lists WireGuard interfaces
      (their "Name" field, e.g. "wg0").
    - GET /api/getWireguardConfigurationInfo?configurationName=<Name> -
      returns {"configurationPeers": [...], "configurationRestrictedPeers":
      [...]} for that interface. A *restricted* (blocked) peer is removed
      from configurationPeers entirely and only appears in the restricted
      list - so both lists have to be walked to see every peer, and
      membership in the restricted list is itself the "disabled" signal
      (there's no per-peer enabled/disabled flag to read otherwise).

    Peer JSON fields used here (Peer.toJson() in WGDashboard's source is a
    plain `self.__dict__`, so there's no schema doc beyond the source
    itself): "id" (the peer's WireGuard public key - used as external_id),
    "name", "allowed_ip" (its tunnel address/CIDR), "status" ("running" or
    "stopped", computed server-side from a 3-minute handshake staleness
    window - same threshold as wg-easy's STALE_HANDSHAKE_SECONDS, just
    computed on the other end), and "latest_handshake" (a "H:MM:SS"-style
    duration string, or the literal "No Handshake" - notably NOT an ISO
    timestamp like wg-easy's latestHandshakeAt, so there's nothing to parse
    here, just a string comparison).

    Expected credentials dict: {"username": "...", "password": "..."} -
    whatever you log into the WGDashboard web UI with.
    """

    def __init__(self, base_url, verify_ssl, credentials):
        super().__init__(base_url, verify_ssl, credentials)
        self._session = requests.Session()
        self._authenticated = False

    def _login(self):
        username = self.credentials.get("username")
        password = self.credentials.get("password")
        if not username or not password:
            raise ConnectorError("WGDashboard connector requires username and password")
        resp = self._session.post(
            f"{self.base_url}/api/authenticate",
            json={"username": username, "password": password},
            verify=self.verify_ssl,
            timeout=15,
        )
        if resp.status_code != 200:
            raise ConnectorError(f"WGDashboard login failed: {resp.status_code} {resp.text[:200]}")
        body = resp.json()
        if not body.get("status"):
            raise ConnectorError(f"WGDashboard login failed: {body.get('message')}")
        self._authenticated = True

    def _get(self, path: str, params: dict | None = None):
        if not self._authenticated:
            self._login()
        resp = self._session.get(f"{self.base_url}{path}", params=params, verify=self.verify_ssl, timeout=15)
        if resp.status_code == 401:
            # Session cookie may have expired mid-poll - retry once.
            self._authenticated = False
            self._login()
            resp = self._session.get(f"{self.base_url}{path}", params=params, verify=self.verify_ssl, timeout=15)
        if resp.status_code != 200:
            raise ConnectorError(f"WGDashboard API {path} returned {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        # Unlike the HTTP-status-code failures above, a logical error (bad
        # configurationName, etc.) still comes back as HTTP 200 with
        # {"status": false, "message": "..."} - WGDashboard's ResponseObject
        # always uses 200 except for the auth middleware's own 401s.
        if not body.get("status", True):
            raise ConnectorError(f"WGDashboard API {path} error: {body.get('message')}")
        return body.get("data")

    def poll(self) -> list[DiscoveredAsset]:
        configs = self._get("/api/getWireguardConfigurations") or []

        assets: list[DiscoveredAsset] = []
        for config in configs:
            name = config.get("Name")
            if not name:
                continue
            info = self._get("/api/getWireguardConfigurationInfo", params={"configurationName": name}) or {}
            peers = info.get("configurationPeers") or []
            restricted = info.get("configurationRestrictedPeers") or []
            restricted_ids = {p.get("id") for p in restricted if p.get("id")}

            for peer in list(peers) + list(restricted):
                peer_id = peer.get("id")
                if not peer_id:
                    continue
                assets.append(
                    DiscoveredAsset(
                        asset_type="wireguard_peer",
                        external_id=peer_id,
                        name=peer.get("name") or peer_id,
                        ip_address=_strip_cidr(peer.get("allowed_ip")),
                        status=_peer_status(peer, restricted=peer_id in restricted_ids),
                        raw_data=peer,
                    )
                )
        return assets
