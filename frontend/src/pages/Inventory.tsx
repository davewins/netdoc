import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import type { Asset, Connector } from "../types";

const ASSET_TYPES = [
  "proxmox_node",
  "vm",
  "lxc",
  "docker_host",
  "docker_stack",
  "docker_container",
  "dns_record",
  "dhcp_reservation",
  "device",
  "host",
  "k8s_node",
  "k8s_pod",
  "ha_device",
  "ha_entity",
  "uptime_monitor",
  "wireguard_peer",
];

function formatSpecs(a: Asset): string {
  const parts: string[] = [];
  if (a.cpu_cores) parts.push(`${a.cpu_cores} vCPU`);
  if (a.memory_mb) parts.push(`${(a.memory_mb / 1024).toFixed(1)} GB RAM`);
  if (a.disk_gb) parts.push(`${a.disk_gb} GB disk`);
  return parts.join(" · ") || "-";
}

// IPv4 dotted string -> a single comparable number, so sorting is numeric
// per-octet (192.168.1.9 before 192.168.1.10) rather than lexical string
// order. Anything not a plain dotted-quad (IPv6, empty) sorts to the
// bottom regardless of direction.
function ipSortValue(ip: string | null): number {
  if (!ip) return -1;
  const parts = ip.split(".").map(Number);
  if (parts.length !== 4 || parts.some((p) => Number.isNaN(p))) return -1;
  return parts.reduce((acc, p) => acc * 256 + p, 0);
}

type SortKey =
  | "name"
  | "asset_type"
  | "site"
  | "ip_address"
  | "status"
  | "specs"
  | "source"
  | "tags"
  | "last_seen_at";

const SORTERS: Record<SortKey, (a: Asset) => string | number> = {
  name: (a) => a.name.toLowerCase(),
  asset_type: (a) => a.asset_type,
  site: (a) => a.site ?? "",
  ip_address: (a) => ipSortValue(a.ip_address),
  status: (a) => a.status ?? "",
  specs: (a) => a.memory_mb ?? 0,
  source: (a) => a.source,
  tags: (a) => a.tags.join(","),
  last_seen_at: (a) => new Date(a.last_seen_at).getTime(),
};

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "asset_type", label: "Type" },
  { key: "site", label: "Site" },
  { key: "ip_address", label: "IP" },
  { key: "status", label: "Status" },
  { key: "specs", label: "Specs" },
  { key: "source", label: "Source" },
  { key: "tags", label: "Tags" },
  { key: "last_seen_at", label: "Last seen" },
];

export default function Inventory() {
  const [params, setParams] = useSearchParams();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [q, setQ] = useState(params.get("q") ?? "");
  const [showAdd, setShowAdd] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const assetType = params.get("asset_type") ?? "";
  const site = params.get("site") ?? "";

  function reload() {
    api.listAssets({ asset_type: assetType || undefined, site: site || undefined, q: q || undefined }).then(setAssets);
  }

  useEffect(reload, [assetType, site, q]);
  useEffect(() => {
    api.listConnectors().then(setConnectors);
  }, []);

  const knownSites = [...new Set(connectors.map((c) => c.site).filter((s): s is string => !!s))].sort();

  function setFilter(key: "asset_type" | "site", value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  }

  function sortBy(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  const sortedAssets = [...assets].sort((a, b) => {
    const va = SORTERS[sortKey](a);
    const vb = SORTERS[sortKey](b);
    const cmp = va < vb ? -1 : va > vb ? 1 : 0;
    return sortDir === "asc" ? cmp : -cmp;
  });

  return (
    <div>
      <h1>Inventory</h1>

      <div className="filters">
        <select value={assetType} onChange={(e) => setFilter("asset_type", e.target.value)}>
          <option value="">All types</option>
          {ASSET_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        {knownSites.length > 0 && (
          <select value={site} onChange={(e) => setFilter("site", e.target.value)}>
            <option value="">All sites</option>
            {knownSites.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        )}
        <input placeholder="Search name / hostname / IP" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="secondary" onClick={() => setShowAdd((v) => !v)}>
          {showAdd ? "Cancel" : "+ Add manual asset"}
        </button>
      </div>

      {showAdd && (
        <AddAssetForm
          onCreated={() => {
            setShowAdd(false);
            reload();
          }}
        />
      )}

      <table>
        <thead>
          <tr>
            {COLUMNS.map((c) => (
              <th key={c.key} className="sortable" onClick={() => sortBy(c.key)}>
                {c.label}
                <span className="sort-arrow">{sortKey === c.key ? (sortDir === "asc" ? "▲" : "▼") : ""}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedAssets.map((a) => (
            <tr key={a.id}>
              <td>
                <Link className="row-link" to={`/assets/${a.id}`}>
                  {a.name}
                </Link>
                {a.linked_assets.length > 0 && (
                  <span className="muted"> (+{a.linked_assets.length} linked)</span>
                )}
                {a.children.length > 0 && (
                  <span className="muted">
                    {" "}
                    (+{a.children.length} {a.asset_type === "ha_device" ? "entities" : "children"})
                  </span>
                )}
              </td>
              <td>{a.asset_type}</td>
              <td>{a.site ? <span className="tag">{a.site}</span> : <span className="muted">-</span>}</td>
              <td>{a.ip_address ?? "-"}</td>
              <td>{a.status ?? "-"}</td>
              <td className="muted">{formatSpecs(a)}</td>
              <td className="muted">{a.source}</td>
              <td>
                {a.tags.map((t) => (
                  <span key={t} className="tag">
                    {t}
                  </span>
                ))}
              </td>
              <td className="muted">{new Date(a.last_seen_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {assets.length === 0 && <p className="muted">No assets match.</p>}
    </div>
  );
}

function AddAssetForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [assetType, setAssetType] = useState("host");
  const [ip, setIp] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!name.trim()) return;
    try {
      await api.createAsset({ name, asset_type: assetType, ip_address: ip || undefined });
      onCreated();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="card">
      <div className="form-row">
        <div>
          <label>Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. living-room-tv" />
        </div>
        <div>
          <label>Type</label>
          <select value={assetType} onChange={(e) => setAssetType(e.target.value)}>
            {ASSET_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label>IP address</label>
          <input value={ip} onChange={(e) => setIp(e.target.value)} placeholder="192.168.1.x" />
        </div>
      </div>
      {error && <div className="status-error">{error}</div>}
      <button onClick={submit}>Create</button>
    </div>
  );
}
