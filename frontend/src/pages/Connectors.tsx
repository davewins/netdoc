import { useEffect, useState } from "react";
import { api } from "../api";
import { CheckCircleIcon, EditIcon, ErrorCircleIcon } from "../icons";
import type { Connector } from "../types";

const CONNECTOR_FIELDS: Record<string, { key: string; label: string; type?: string }[]> = {
  proxmox: [
    { key: "token_name", label: "API token name (user@realm!tokenid)" },
    { key: "token_value", label: "API token value", type: "password" },
  ],
  portainer: [
    { key: "api_key", label: "API key (leave blank to use username/password)" },
    { key: "username", label: "Username (if no API key)" },
    { key: "password", label: "Password (if no API key)", type: "password" },
  ],
  pihole: [{ key: "password", label: "Web UI / app password", type: "password" }],
  network_scan: [],
  home_assistant: [{ key: "token", label: "Long-lived access token", type: "password" }],
  kubernetes: [{ key: "token", label: "Service account bearer token", type: "password" }],
  uptime_kuma: [
    { key: "api_key", label: "API key (leave blank to use username/password)" },
    { key: "username", label: "Username (if no API key)" },
    { key: "password", label: "Password (if no API key)", type: "password" },
  ],
  wireguard: [
    { key: "username", label: "wg-easy username" },
    { key: "password", label: "wg-easy password", type: "password" },
  ],
  wgdashboard: [
    { key: "username", label: "WGDashboard username" },
    { key: "password", label: "WGDashboard password", type: "password" },
  ],
};

const BASE_URL_LABEL: Record<string, string> = {
  network_scan: "Network range to scan (CIDR, e.g. 192.168.1.0/24)",
  kubernetes: "API server URL (e.g. https://192.168.1.50:6443)",
  home_assistant: "Home Assistant URL (e.g. http://homeassistant.local:8123)",
  uptime_kuma: "Uptime Kuma URL",
  wireguard: "wg-easy URL (e.g. http://192.168.1.5:51821)",
  wgdashboard: "WGDashboard URL (e.g. http://192.168.1.5:10086)",
};

export default function Connectors() {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<Connector | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  function reload() {
    api.listConnectors().then(setConnectors);
  }

  useEffect(reload, []);

  async function pollNow(id: number) {
    setBusyId(id);
    try {
      await api.pollConnectorNow(id);
    } finally {
      setBusyId(null);
      reload();
    }
  }

  async function remove(id: number) {
    if (!confirm("Delete this connector and its discovered assets?")) return;
    await api.deleteConnector(id);
    reload();
  }

  const knownSites = [...new Set(connectors.map((c) => c.site).filter((s): s is string => !!s))].sort();

  return (
    <div>
      <h1>Connectors</h1>
      <p className="muted">
        Each connector polls a source every few minutes to keep the inventory up to date. Credentials are
        encrypted at rest.
      </p>

      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Site</th>
            <th>URL</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {connectors.map((c) => (
            <tr key={c.id}>
              <td>{c.name}</td>
              <td>{c.type}</td>
              <td>{c.site ? <span className="tag">{c.site}</span> : <span className="muted">-</span>}</td>
              <td className="muted">{c.base_url}</td>
              <td>
                {c.last_error ? (
                  <span className="status-error" title={c.last_error}>
                    <ErrorCircleIcon /> error
                  </span>
                ) : c.last_polled_at ? (
                  <span className="status-ok">
                    <CheckCircleIcon /> ok
                  </span>
                ) : (
                  <span className="muted">pending</span>
                )}
              </td>
              <td>
                <button className="secondary" disabled={busyId === c.id} onClick={() => pollNow(c.id)}>
                  {busyId === c.id ? "Polling..." : "Poll now"}
                </button>{" "}
                <button
                  className="secondary"
                  onClick={() => {
                    setEditing(c);
                    setShowAdd(false);
                  }}
                >
                  <EditIcon /> Edit
                </button>{" "}
                <button className="danger" onClick={() => remove(c.id)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {connectors.some((c) => c.last_error) && (
        <div className="card status-error">
          {connectors
            .filter((c) => c.last_error)
            .map((c) => (
              <div key={c.id}>
                <strong>{c.name}:</strong> {c.last_error}
              </div>
            ))}
        </div>
      )}

      {editing && (
        <ConnectorForm
          connector={editing}
          knownSites={knownSites}
          onDone={() => {
            setEditing(null);
            reload();
          }}
          onCancel={() => setEditing(null)}
        />
      )}

      {!editing && (
        <>
          <button className="secondary" onClick={() => setShowAdd((v) => !v)}>
            {showAdd ? "Cancel" : "+ Add connector"}
          </button>
          {showAdd && (
            <ConnectorForm
              knownSites={knownSites}
              onDone={() => {
                setShowAdd(false);
                reload();
              }}
            />
          )}
        </>
      )}
    </div>
  );
}

function ConnectorForm({
  connector,
  knownSites,
  onDone,
  onCancel,
}: {
  connector?: Connector;
  knownSites: string[];
  onDone: () => void;
  onCancel?: () => void;
}) {
  const isEdit = !!connector;
  const [type, setType] = useState(connector?.type ?? "proxmox");
  const [name, setName] = useState(connector?.name ?? "");
  const [baseUrl, setBaseUrl] = useState(connector?.base_url ?? "");
  const [verifySsl, setVerifySsl] = useState(connector?.verify_ssl ?? false);
  const [enabled, setEnabled] = useState(connector?.enabled ?? true);
  const [site, setSite] = useState(connector?.site ?? "");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!name.trim() || !baseUrl.trim()) return;
    try {
      const payload = {
        type,
        name,
        base_url: baseUrl,
        verify_ssl: verifySsl,
        enabled,
        site: site.trim() || undefined,
        credentials: fields,
      };
      if (isEdit) {
        await api.updateConnector(connector.id, payload);
      } else {
        await api.createConnector(payload);
      }
      onDone();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="card">
      <div className="form-row">
        <div>
          <label>Type</label>
          <select
            value={type}
            disabled={isEdit}
            onChange={(e) => {
              setType(e.target.value);
              setFields({});
            }}
          >
            <option value="proxmox">Proxmox VE</option>
            <option value="portainer">Portainer</option>
            <option value="pihole">Pi-hole</option>
            <option value="network_scan">Network scan (nmap)</option>
            <option value="home_assistant">Home Assistant</option>
            <option value="kubernetes">Kubernetes</option>
            <option value="uptime_kuma">Uptime Kuma</option>
            <option value="wireguard">WireGuard (wg-easy)</option>
            <option value="wgdashboard">WireGuard (WGDashboard)</option>
          </select>
        </div>
        <div>
          <label>Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="pve-1" />
        </div>
        <div>
          <label>{BASE_URL_LABEL[type] ?? "Base URL"}</label>
          <input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={type === "network_scan" ? "192.168.1.0/24" : "https://192.168.1.5:8006"}
          />
        </div>
        <div>
          <label>Site (optional)</label>
          <input
            value={site}
            onChange={(e) => setSite(e.target.value)}
            placeholder="e.g. Teignmouth - blank for your main network"
            list="connector-sites"
          />
          <datalist id="connector-sites">
            {knownSites.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
        </div>
      </div>

      {type !== "network_scan" && (
        <label>
          <input
            type="checkbox"
            style={{ width: "auto", marginRight: 6 }}
            checked={verifySsl}
            onChange={(e) => setVerifySsl(e.target.checked)}
          />
          Verify TLS certificate
        </label>
      )}

      {isEdit && (
        <label>
          <input
            type="checkbox"
            style={{ width: "auto", marginRight: 6 }}
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          Enabled
        </label>
      )}

      {type === "network_scan" && (
        <p className="muted">
          Requires netdoc to run with host networking (see docker-compose.yml) - otherwise it can only see
          Docker's own bridge network, not your LAN.
        </p>
      )}

      {isEdit && (CONNECTOR_FIELDS[type] ?? []).length > 0 && (
        <p className="muted">Leave credential fields blank to keep what's already stored.</p>
      )}

      {(CONNECTOR_FIELDS[type] ?? []).map((f) => (
        <div key={f.key}>
          <label>{f.label}</label>
          <input
            type={f.type ?? "text"}
            value={fields[f.key] ?? ""}
            onChange={(e) => setFields((prev) => ({ ...prev, [f.key]: e.target.value }))}
          />
        </div>
      ))}

      {error && <div className="status-error">{error}</div>}
      <button onClick={submit}>{isEdit ? "Save changes" : "Create connector"}</button>{" "}
      {isEdit && (
        <button className="secondary" onClick={onCancel}>
          Cancel
        </button>
      )}
    </div>
  );
}
