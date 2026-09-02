import re
import socket
from contextlib import contextmanager
from urllib.parse import urlparse

import requests

from .base import BaseConnector, ConnectorError, DiscoveredAsset

# Uptime Kuma's own API is Socket.IO-based (what its web UI uses) - there's
# no plain REST endpoint that lists every monitor. The one stable,
# unauthenticated-friendly REST surface it does offer is the Prometheus
# metrics endpoint, if enabled (Settings > Monitor History > Prometheus, or
# just "Expose Prometheus Metrics" depending on version). It's a plaintext
# exposition-format dump, not JSON, hence the small regex parser below
# rather than pulling in a prometheus client library for one gauge.
METRIC_LINE_RE = re.compile(r'^monitor_status\{(?P<labels>.*)\}\s+(?P<value>[\d.]+)\s*$')
LABEL_RE = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')

STATUS_MAP = {"0": "down", "1": "up", "2": "pending", "3": "maintenance"}


@contextmanager
def _dns_timeout(seconds: float):
    """Scope a short timeout around a blocking DNS lookup so one unreachable
    hostname can't stall the whole poll. Connectors run one at a time from
    a single background scheduler job, so mutating the process-wide default
    is safe here - just careful to always put it back."""
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(seconds)
    try:
        yield
    finally:
        socket.setdefaulttimeout(previous)


def _is_ip(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 4 and all(p.isdigit() for p in parts)


def _resolve(hostname: str) -> str | None:
    if _is_ip(hostname):
        return hostname
    try:
        with _dns_timeout(3):
            return socket.gethostbyname(hostname)
    except OSError:
        return None


def _parse_labels(raw: str) -> dict:
    return {key: value for key, value in LABEL_RE.findall(raw)}


class UptimeKumaConnector(BaseConnector):
    """Backfills asset status from Uptime Kuma's Prometheus metrics endpoint.

    Requires "Expose Prometheus Metrics" enabled in Uptime Kuma's settings.
    Expected credentials dict, either:
      {"api_key": "uk1_..."} (sent as the basic-auth *password* with the
      username left blank - `curl -u":<key>"` per Kuma's docs; note that
      adding any API key in Kuma permanently disables basic-auth login on
      this endpoint, so an api_key here is mandatory once one exists)
    or:
      {"username": "...", "password": "..."} (your Kuma login - only works
      until the first API key is created in Kuma)

    Each monitor becomes its own DiscoveredAsset (asset_type "uptime_monitor")
    rather than trying to match an existing asset itself - that's left to
    the normal correlation pipeline. Monitors rarely carry a MAC, so in
    practice they'll only line up via a shared IP, which correlation.py
    turns into a pending link rather than an automatic merge; confirming
    that link is what actually backfills the target asset's `status` field
    (see the backfill-on-confirm logic in routers/links.py and
    correlation.py's MAC-merge path - both now carry status the same way
    they've always carried ip/hostname).

    A monitor's target is usually a hostname/URL, not a bare IP, so this
    does a best-effort DNS lookup to turn that into something correlation
    can actually match on. If that fails (or is skipped, if it's a plain
    HTTP check with no discrete host) the monitor still becomes a
    standalone asset - it just won't link up with anything until an IP
    happens to be known some other way.
    """

    def _auth(self):
        if self.credentials.get("api_key"):
            return ("", self.credentials["api_key"])
        username = self.credentials.get("username")
        password = self.credentials.get("password")
        if not username or not password:
            raise ConnectorError("Uptime Kuma connector requires api_key, or username and password")
        return (username, password)

    @staticmethod
    def _monitor_host(labels: dict) -> str | None:
        hostname = labels.get("monitor_hostname")
        if hostname:
            return hostname
        url = labels.get("monitor_url")
        if url:
            parsed = urlparse(url)
            if parsed.hostname:
                return parsed.hostname
        return None

    def poll(self) -> list[DiscoveredAsset]:
        resp = requests.get(
            f"{self.base_url}/metrics", auth=self._auth(), verify=self.verify_ssl, timeout=15
        )
        if resp.status_code != 200:
            raise ConnectorError(f"Uptime Kuma /metrics returned {resp.status_code}: {resp.text[:200]}")

        assets: list[DiscoveredAsset] = []
        for line in resp.text.splitlines():
            match = METRIC_LINE_RE.match(line)
            if not match:
                continue
            labels = _parse_labels(match.group("labels"))
            name = labels.get("monitor_name")
            if not name:
                continue

            host = self._monitor_host(labels)
            ip = _resolve(host) if host else None

            assets.append(
                DiscoveredAsset(
                    asset_type="uptime_monitor",
                    external_id=name,
                    name=name,
                    ip_address=ip,
                    status=STATUS_MAP.get(match.group("value").split(".")[0], "unknown"),
                    raw_data={"labels": labels, "resolved_ip": ip},
                )
            )

        return assets
