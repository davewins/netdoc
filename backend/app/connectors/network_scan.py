import shutil
import subprocess
import xml.etree.ElementTree as ET

from .base import BaseConnector, ConnectorError, DiscoveredAsset

# A short, homelab-relevant port list rather than nmap's default 1000 -
# keeps a full-subnet sweep fast enough to run every poll interval.
COMMON_PORTS = "22,53,80,443,445,631,3000,3306,5000,5432,8000,8006,8080,8081,8443,8843,9000,9090,32400"


class NetworkScanConnector(BaseConnector):
    """Active LAN discovery via nmap. Requires the container to run with
    host networking and NET_ADMIN/NET_RAW capabilities so nmap's ARP scan
    can see real devices on the local subnet (a plain bridge network can
    only see what a bridge network can, i.e. very little).

    `base_url` is repurposed as the CIDR to scan, e.g. "192.168.1.0/24" -
    there's no server to talk to here, so a dedicated field would be
    overkill for what's otherwise a normal connector.
    """

    def __init__(self, base_url, verify_ssl, credentials):
        super().__init__(base_url, verify_ssl, credentials)
        self.cidr = base_url

    def _run_nmap(self, args: list[str]) -> ET.Element:
        if not shutil.which("nmap"):
            raise ConnectorError("nmap is not installed in this container")
        try:
            result = subprocess.run(
                ["nmap", *args, "-oX", "-", self.cidr],
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConnectorError(f"nmap scan of {self.cidr} timed out") from exc

        if result.returncode != 0:
            raise ConnectorError(f"nmap exited {result.returncode}: {result.stderr[:300]}")
        try:
            return ET.fromstring(result.stdout)
        except ET.ParseError as exc:
            raise ConnectorError(f"could not parse nmap output: {exc}") from exc

    def poll(self) -> list[DiscoveredAsset]:
        if not self.cidr:
            raise ConnectorError("Network scan connector requires a CIDR range (set as its base URL)")

        # Pass 1: who's alive + their MAC. On the local subnet this is ARP
        # (needs host networking) and finds everyone reliably. Across a
        # routed link (e.g. a site-to-site WireGuard tunnel to a second
        # site) ARP is impossible - there's no L2 to ARP on - so this falls
        # back to nmap's default handful of discovery probes (ICMP echo,
        # a SYN to 443, an ACK to 80, ...), which plenty of real devices
        # simply don't answer even though they're up. That under-detection
        # is a real limitation of ping-sweep discovery over a tunnel, not
        # fixable here - but pass 2 below (a real port scan of the whole
        # range, not just who pass 1 already found) gives every host a
        # second chance via more ports, and used to be discarded for
        # anyone pass 1 missed. It no longer is.
        discovery_root = self._run_nmap(["-sn"])
        hosts_by_ip: dict[str, dict] = {}
        for host in discovery_root.findall("host"):
            if host.find("status").get("state") != "up":
                continue
            addrs = host.findall("address")
            ip = next((a.get("addr") for a in addrs if a.get("addrtype") == "ipv4"), None)
            if not ip:
                continue
            mac = next((a.get("addr") for a in addrs if a.get("addrtype") == "mac"), None)
            vendor = next((a.get("vendor") for a in addrs if a.get("addrtype") == "mac"), None)
            hostname_el = host.find("hostnames/hostname")
            hostname = hostname_el.get("name") if hostname_el is not None else None
            hosts_by_ip[ip] = {"mac": mac, "vendor": vendor, "hostname": hostname, "ports": []}

        # Pass 2: a light top-ports scan of the *whole* range with -Pn
        # (don't skip anyone just because pass 1 didn't hear back). Besides
        # giving context on what's running (e.g. "this thing has 8006
        # open" hints Proxmox even if no connector has claimed it yet),
        # any response here - open OR closed, i.e. something actually
        # answered rather than the probe vanishing into a firewall - is
        # itself independent evidence of a live host, worth keeping even
        # when pass 1's ping sweep missed it entirely.
        try:
            port_root = self._run_nmap(["-Pn", "-T4", f"-p{COMMON_PORTS}"])
            for host in port_root.findall("host"):
                addrs = host.findall("address")
                ip = next((a.get("addr") for a in addrs if a.get("addrtype") == "ipv4"), None)
                if not ip:
                    continue
                ports = [p for p in host.findall("ports/port") if p.find("state") is not None]
                responded = [p for p in ports if p.find("state").get("state") in ("open", "closed")]
                if ip not in hosts_by_ip:
                    if not responded:
                        continue  # never seen, and nothing here answered either - not a live host
                    hosts_by_ip[ip] = {"mac": None, "vendor": None, "hostname": None, "ports": []}
                for port in responded:
                    if port.find("state").get("state") != "open":
                        continue
                    service = port.find("service")
                    hosts_by_ip[ip]["ports"].append(
                        {
                            "port": int(port.get("portid")),
                            "protocol": port.get("protocol", "tcp"),
                            "description": service.get("name") if service is not None else "",
                        }
                    )
        except ConnectorError:
            pass  # port scan is best-effort; host discovery above still stands

        if not hosts_by_ip:
            return []

        assets = []
        for ip, info in hosts_by_ip.items():
            name = info["hostname"] or info["vendor"] or ip
            external_id = info["mac"] or ip
            assets.append(
                DiscoveredAsset(
                    asset_type="host",
                    external_id=external_id,
                    name=name,
                    hostname=info["hostname"],
                    ip_address=ip,
                    mac_address=info["mac"],
                    status="up",
                    initial_ports=info["ports"],
                    raw_data={"vendor": info["vendor"], "scanned_ports": info["ports"]},
                )
            )
        return assets
