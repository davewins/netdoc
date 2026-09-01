import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Asset, Connector } from "../types";

export default function Dashboard() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.listAssets(), api.listConnectors()])
      .then(([a, c]) => {
        setAssets(a);
        setConnectors(c);
      })
      .catch((e) => setError(String(e)));
  }, []);

  const counts: Record<string, number> = {};
  for (const a of assets) counts[a.asset_type] = (counts[a.asset_type] ?? 0) + 1;

  const failingConnectors = connectors.filter((c) => c.last_error);

  return (
    <div>
      <h1>Dashboard</h1>
      {error && <div className="card status-error">{error}</div>}

      <h2>Assets by type</h2>
      <div className="grid">
        {Object.entries(counts).map(([type, count]) => (
          <Link key={type} to={`/inventory?asset_type=${type}`} className="row-link">
            <div className="stat">
              <div className="value">{count}</div>
              <div className="label">{type.replace("_", " ")}</div>
            </div>
          </Link>
        ))}
        {assets.length === 0 && <span className="muted">No assets discovered or added yet.</span>}
      </div>

      <h2>Connectors</h2>
      <div className="card">
        {connectors.length === 0 && (
          <span className="muted">
            No connectors configured yet. Add one in <Link to="/connectors">Connectors</Link>.
          </span>
        )}
        {connectors.map((c) => (
          <div key={c.id} style={{ marginBottom: 8 }}>
            <strong>{c.name}</strong> <span className="muted">({c.type})</span> —{" "}
            {c.last_error ? (
              <span className="status-error">error: {c.last_error}</span>
            ) : c.last_polled_at ? (
              <span className="status-ok">last polled {new Date(c.last_polled_at).toLocaleString()}</span>
            ) : (
              <span className="muted">not polled yet</span>
            )}
          </div>
        ))}
        {failingConnectors.length > 0 && (
          <div className="muted">
            {failingConnectors.length} connector(s) currently failing — check <Link to="/connectors">Connectors</Link>.
          </div>
        )}
      </div>
    </div>
  );
}
