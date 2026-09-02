import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type { Asset, PortEntry } from "../types";

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  if (days > 0) return `${days}d ${hours}h`;
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

export default function AssetDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [asset, setAsset] = useState<Asset | null>(null);
  const [notes, setNotes] = useState("");
  const [tagsText, setTagsText] = useState("");
  const [servicesText, setServicesText] = useState("");
  const [ports, setPorts] = useState<PortEntry[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load() {
    api.getAsset(Number(id)).then((a) => {
      setAsset(a);
      setNotes(a.notes ?? "");
      setTagsText(a.tags.join(", "));
      setServicesText(a.services.join(", "));
      setPorts(a.ports);
    });
  }

  useEffect(load, [id]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.enrichAsset(Number(id), {
        notes,
        tags: tagsText.split(",").map((t) => t.trim()).filter(Boolean),
        services: servicesText.split(",").map((t) => t.trim()).filter(Boolean),
        ports,
      });
      setAsset(updated);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!confirm(`Delete asset "${asset?.name}"? This cannot be undone.`)) return;
    await api.deleteAsset(Number(id));
    navigate("/inventory");
  }

  function updatePort(idx: number, patch: Partial<PortEntry>) {
    setPorts((prev) => prev.map((p, i) => (i === idx ? { ...p, ...patch } : p)));
  }

  function addPort() {
    setPorts((prev) => [...prev, { port: 0, protocol: "tcp", description: "" }]);
  }

  function removePort(idx: number) {
    setPorts((prev) => prev.filter((_, i) => i !== idx));
  }

  if (!asset) return <p className="muted">Loading...</p>;

  return (
    <div>
      <p>
        <Link className="row-link muted" to="/inventory">
          &larr; Inventory
        </Link>
      </p>
      <h1>{asset.name}</h1>
      <p className="muted">
        {asset.asset_type} · {asset.source}
        {asset.ip_address ? ` · ${asset.ip_address}` : ""}
        {asset.mac_address ? ` · ${asset.mac_address}` : ""}
        {asset.status ? ` · ${asset.status}` : ""}
      </p>
      {(asset.cpu_cores || asset.memory_mb || asset.disk_gb || asset.uptime_seconds) && (
        <p className="muted">
          {asset.cpu_cores ? `${asset.cpu_cores} vCPU` : null}
          {asset.memory_mb ? ` · ${(asset.memory_mb / 1024).toFixed(1)} GB RAM` : null}
          {asset.disk_gb ? ` · ${asset.disk_gb} GB disk` : null}
          {asset.uptime_seconds ? ` · up ${formatUptime(asset.uptime_seconds)}` : null}
        </p>
      )}

      {asset.canonical_asset_id && (
        <div className="card status-error">
          This record has been merged into{" "}
          <Link className="row-link" to={`/assets/${asset.canonical_asset_id}`}>
            asset #{asset.canonical_asset_id}
          </Link>
          . View it there for the combined enrichment.
        </div>
      )}

      {asset.linked_assets.length > 0 && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Also known as</h2>
          <p className="muted">Same physical/virtual host, identified via other sources:</p>
          {asset.linked_assets.map((l) => (
            <div key={l.id} style={{ marginBottom: 6 }}>
              <Link className="row-link" to={`/assets/${l.id}`}>
                {l.name}
              </Link>{" "}
              <span className="muted">
                ({l.asset_type}
                {l.ip_address ? `, ${l.ip_address}` : ""}
                {l.mac_address ? `, ${l.mac_address}` : ""}) - linked via {l.link_reason}
              </span>
            </div>
          ))}
        </div>
      )}

      {asset.children.length > 0 && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>
            {asset.asset_type === "ha_device" ? "Entities" : "Children"} ({asset.children.length})
          </h2>
          {asset.children.map((c) => (
            <div key={c.id} style={{ marginBottom: 6 }}>
              <Link className="row-link" to={`/assets/${c.id}`}>
                {c.name}
              </Link>{" "}
              <span className="muted">
                ({c.asset_type}
                {c.status ? `, ${c.status}` : ""})
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Enrichment</h2>
        <label>Notes</label>
        <textarea rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} />

        <label>Tags (comma separated)</label>
        <input value={tagsText} onChange={(e) => setTagsText(e.target.value)} />

        <label>Services (comma separated, e.g. acme, nginx-proxy-manager)</label>
        <input value={servicesText} onChange={(e) => setServicesText(e.target.value)} />

        <label>Ports</label>
        {ports.map((p, i) => (
          <div className="form-row" key={i} style={{ marginBottom: 6 }}>
            <input
              type="number"
              value={p.port}
              onChange={(e) => updatePort(i, { port: Number(e.target.value) })}
              placeholder="443"
            />
            <select value={p.protocol} onChange={(e) => updatePort(i, { protocol: e.target.value })}>
              <option value="tcp">tcp</option>
              <option value="udp">udp</option>
            </select>
            <input
              value={p.description}
              onChange={(e) => updatePort(i, { description: e.target.value })}
              placeholder="description"
            />
            <button className="danger" onClick={() => removePort(i)}>
              Remove
            </button>
          </div>
        ))}
        <button className="secondary" onClick={addPort}>
          + Add port
        </button>

        {error && <div className="status-error">{error}</div>}
        <div>
          <button onClick={save} disabled={saving}>
            {saving ? "Saving..." : "Save"}
          </button>{" "}
          <button className="danger" onClick={remove}>
            Delete asset
          </button>
        </div>
      </div>

      <CredentialsPanel assetId={asset.id} credentials={asset.credentials} onChange={load} />

      {asset.raw_data && (
        <details className="card">
          <summary style={{ cursor: "pointer" }}>Raw discovered data</summary>
          <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{JSON.stringify(asset.raw_data, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}

function CredentialsPanel({
  assetId,
  credentials,
  onChange,
}: {
  assetId: number;
  credentials: Asset["credentials"];
  onChange: () => void;
}) {
  const [label, setLabel] = useState("");
  const [username, setUsername] = useState("");
  const [secret, setSecret] = useState("");
  const [revealed, setRevealed] = useState<Record<number, string>>({});

  async function add() {
    if (!label.trim()) return;
    await api.addCredential(assetId, { label, username: username || undefined, secret: secret || undefined });
    setLabel("");
    setUsername("");
    setSecret("");
    onChange();
  }

  async function reveal(id: number) {
    const cred = await api.revealCredential(id);
    setRevealed((prev) => ({ ...prev, [id]: cred.secret ?? "(empty)" }));
  }

  async function remove(id: number) {
    if (!confirm("Delete this credential?")) return;
    await api.deleteCredential(id);
    onChange();
  }

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>Credentials</h2>
      {credentials.length === 0 && <p className="muted">None stored yet.</p>}
      {credentials.map((c) => (
        <div key={c.id} className="secret-row" style={{ marginBottom: 8 }}>
          <strong style={{ minWidth: 100 }}>{c.label}</strong>
          <span className="muted">{c.username ?? "-"}</span>
          <span>{revealed[c.id] ?? "••••••••"}</span>
          {!revealed[c.id] && (
            <button className="secondary" onClick={() => reveal(c.id)}>
              Reveal
            </button>
          )}
          <button className="danger" onClick={() => remove(c.id)}>
            Delete
          </button>
        </div>
      ))}

      <h2>Add credential</h2>
      <div className="form-row">
        <div>
          <label>Label</label>
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="admin console" />
        </div>
        <div>
          <label>Username</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div>
          <label>Password / secret</label>
          <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} />
        </div>
      </div>
      <button onClick={add}>Add credential</button>
    </div>
  );
}
