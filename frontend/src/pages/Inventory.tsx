import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import type { Asset } from "../types";

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
];

function formatSpecs(a: Asset): string {
  const parts: string[] = [];
  if (a.cpu_cores) parts.push(`${a.cpu_cores} vCPU`);
  if (a.memory_mb) parts.push(`${(a.memory_mb / 1024).toFixed(1)} GB RAM`);
  if (a.disk_gb) parts.push(`${a.disk_gb} GB disk`);
  return parts.join(" · ") || "-";
}

export default function Inventory() {
  const [params, setParams] = useSearchParams();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [q, setQ] = useState(params.get("q") ?? "");
  const [showAdd, setShowAdd] = useState(false);
  const assetType = params.get("asset_type") ?? "";

  function reload() {
    api.listAssets({ asset_type: assetType || undefined, q: q || undefined }).then(setAssets);
  }

  useEffect(reload, [assetType, q]);

  return (
    <div>
      <h1>Inventory</h1>

      <div className="filters">
        <select
          value={assetType}
          onChange={(e) => setParams(e.target.value ? { asset_type: e.target.value } : {})}
        >
          <option value="">All types</option>
          {ASSET_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
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
            <th>Name</th>
            <th>Type</th>
            <th>IP</th>
            <th>Status</th>
            <th>Specs</th>
            <th>Source</th>
            <th>Tags</th>
            <th>Last seen</th>
          </tr>
        </thead>
        <tbody>
          {assets.map((a) => (
            <tr key={a.id}>
              <td>
                <Link className="row-link" to={`/assets/${a.id}`}>
                  {a.name}
                </Link>
                {a.linked_assets.length > 0 && (
                  <span className="muted"> (+{a.linked_assets.length} linked)</span>
                )}
              </td>
              <td>{a.asset_type}</td>
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
