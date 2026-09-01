import { useEffect, useState } from "react";
import { api } from "../api";
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
};

const BASE_URL_LABEL: Record<string, string> = {
  network_scan: "Network range to scan (CIDR, e.g. 192.168.1.0/24)",
};

export default function Connectors() {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [showAdd, setShowAdd] = useState(false);
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
              <td className="muted">{c.base_url}</td>
              <td>
                {c.last_error ? (
                  <span className="status-error" title={c.last_error}>
                    error
                  </span>
                ) : c.last_polled_at ? (
                  <span className="status-ok">ok</span>
                ) : (
                  <span className="muted">pending</span>
                )}
              </td>
              <td>
                <button className="secondary" disabled={busyId === c.id} onClick={() => pollNow(c.id)}>
                  {busyId === c.id ? "Polling..." : "Poll now"}
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

      <button className="secondary" onClick={() => setShowAdd((v) => !v)}>
        {showAdd ? "Cancel" : "+ Add connector"}
      </button>
      {showAdd && (
        <AddConnectorForm
          onCreated={() => {
            setShowAdd(false);
            reload();
          }}
        />
      )}
    </div>
  );
}

function AddConnectorForm({ onCreated }: { onCreated: () => void }) {
  const [type, setType] = useState("proxmox");
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [verifySsl, setVerifySsl] = useState(false);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!name.trim() || !baseUrl.trim()) return;
    try {
      await api.createConnector({
        type,
        name,
        base_url: baseUrl,
        verify_ssl: verifySsl,
        enabled: true,
        credentials: fields,
      });
      onCreated();
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
            onChange={(e) => {
              setType(e.target.value);
              setFields({});
            }}
          >
            <option value="proxmox">Proxmox VE</option>
            <option value="portainer">Portainer</option>
            <option value="pihole">Pi-hole</option>
            <option value="network_scan">Network scan (nmap)</option>
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

      {type === "network_scan" && (
        <p className="muted">
          Requires netdoc to run with host networking (see docker-compose.yml) - otherwise it can only see
          Docker's own bridge network, not your LAN.
        </p>
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
      <button onClick={submit}>Create connector</button>
    </div>
  );
}
