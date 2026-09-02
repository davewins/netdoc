import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Report } from "../types";

export default function ReportPage() {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function load() {
    setLoading(true);
    api
      .getReport()
      .then((r) => {
        setReport(r);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  const failingConnectors = report?.connectors.filter((c) => c.last_error) ?? [];
  const needsAttention = report && (report.down_assets.length > 0 || failingConnectors.length > 0 || report.pending_link_count > 0);

  return (
    <div>
      <h1>Network report</h1>
      <p className="muted">
        A generated-on-demand summary of the current network state - counts and status are read fresh
        from the database every time you open this page or hit regenerate; nothing here is stored.
        {report && ` Last generated ${new Date(report.generated_at).toLocaleString()}.`}{" "}
        <button className="secondary" onClick={load} disabled={loading}>
          {loading ? "Regenerating…" : "Regenerate"}
        </button>
      </p>

      {error && <div className="card status-error">{error}</div>}

      {report && (
        <>
          <div className="card" style={{ lineHeight: 1.6 }}>
            {report.narrative.map((paragraph, i) => (
              <p key={i} style={{ margin: i === report.narrative.length - 1 ? 0 : "0 0 10px" }}>
                {paragraph}
              </p>
            ))}
          </div>

          {needsAttention && (
            <>
              <h2>Needs attention</h2>
              <div className="card">
                {failingConnectors.map((c) => (
                  <div key={`c${c.id}`} style={{ marginBottom: 8 }}>
                    <span className="status-error">{c.name}</span>{" "}
                    <span className="muted">
                      ({c.type}
                      {c.site ? `, ${c.site}` : ""}) —{" "}
                    </span>
                    {c.last_error}
                  </div>
                ))}
                {report.down_assets.map((a) => (
                  <div key={`a${a.id}`} style={{ marginBottom: 8 }}>
                    <Link to={`/assets/${a.id}`}>{a.name}</Link>{" "}
                    <span className="muted">
                      ({a.asset_type.replace("_", " ")}
                      {a.site ? `, ${a.site}` : ""}) — {a.status}
                    </span>
                  </div>
                ))}
                {report.pending_link_count > 0 && (
                  <div>
                    {report.pending_link_count} pending link suggestion{report.pending_link_count !== 1 ? "s" : ""} —
                    see <Link to="/links">Link suggestions</Link>.
                  </div>
                )}
              </div>
            </>
          )}

          <h2>Assets by type</h2>
          <div className="grid">
            {Object.entries(report.by_type)
              .sort((a, b) => b[1] - a[1])
              .map(([type, count]) => (
                <Link key={type} to={`/inventory?asset_type=${type}`} className="row-link">
                  <div className="stat">
                    <div className="value">{count}</div>
                    <div className="label">{type.replace("_", " ")}</div>
                  </div>
                </Link>
              ))}
          </div>

          {Object.keys(report.by_site).length > 1 && (
            <>
              <h2>Assets by site</h2>
              <div className="grid">
                {Object.entries(report.by_site)
                  .sort((a, b) => b[1] - a[1])
                  .map(([site, count]) => (
                    <Link
                      key={site}
                      to={site === "Local network" ? "/inventory" : `/inventory?site=${encodeURIComponent(site)}`}
                      className="row-link"
                    >
                      <div className="stat">
                        <div className="value">{count}</div>
                        <div className="label">{site}</div>
                      </div>
                    </Link>
                  ))}
              </div>
            </>
          )}

          <h2>Connectors</h2>
          <div className="card">
            {report.connectors.length === 0 && (
              <span className="muted">
                No connectors configured yet. Add one in <Link to="/connectors">Connectors</Link>.
              </span>
            )}
            {report.connectors.map((c) => (
              <div key={c.id} style={{ marginBottom: 8 }}>
                <strong>{c.name}</strong>{" "}
                <span className="muted">
                  ({c.type}
                  {c.site ? `, ${c.site}` : ""})
                </span>{" "}
                —{" "}
                {c.last_error ? (
                  <span className="status-error">error: {c.last_error}</span>
                ) : c.last_polled_at ? (
                  <span className="status-ok">last polled {new Date(c.last_polled_at).toLocaleString()}</span>
                ) : (
                  <span className="muted">not polled yet</span>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
