import { useEffect, useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { api } from "../api";
import type { AssetLink } from "../types";

export default function Links() {
  const [links, setLinks] = useState<AssetLink[]>([]);
  const [busyId, setBusyId] = useState<number | "bulk" | null>(null);

  function reload() {
    api.listLinks("pending").then(setLinks);
  }

  useEffect(reload, []);

  const groups = useMemo(() => {
    const byHub = new Map<number, AssetLink[]>();
    for (const l of links) {
      const arr = byHub.get(l.primary_asset.id) ?? [];
      arr.push(l);
      byHub.set(l.primary_asset.id, arr);
    }
    return [...byHub.values()].sort((a, b) => b.length - a.length);
  }, [links]);

  async function confirm(id: number) {
    setBusyId(id);
    try {
      await api.confirmLink(id);
    } finally {
      setBusyId(null);
      reload();
    }
  }

  async function reject(id: number) {
    setBusyId(id);
    try {
      await api.rejectLink(id);
    } finally {
      setBusyId(null);
      reload();
    }
  }

  async function bulkAction(group: AssetLink[], action: "confirm" | "reject") {
    setBusyId("bulk");
    try {
      for (const l of group) {
        await (action === "confirm" ? api.confirmLink(l.id) : api.rejectLink(l.id));
      }
    } finally {
      setBusyId(null);
      reload();
    }
  }

  return (
    <div>
      <h1>Link suggestions</h1>
      <p className="muted">
        These records share an IP address but not a MAC address, so netdoc isn't confident enough to merge
        them automatically (DHCP can reassign an IP to a different device, and several hostnames can
        legitimately point at one reverse proxy). Grouped by the record sharing the IP with the most others.
      </p>

      {groups.length === 0 && <p className="muted">No pending suggestions.</p>}

      {groups.map((group) => {
        const hub = group[0].primary_asset;
        return (
          <div key={hub.id} className="card">
            <div style={{ marginBottom: 10 }}>
              <strong>
                <RouterLink className="row-link" to={`/assets/${hub.id}`}>
                  {hub.name}
                </RouterLink>
              </strong>{" "}
              <span className="muted">
                ({hub.asset_type}, {hub.ip_address}) shares this IP with {group.length} other record
                {group.length > 1 ? "s" : ""}:
              </span>
            </div>

            {group.map((l) => (
              <div key={l.id} className="secret-row" style={{ marginBottom: 6 }}>
                <RouterLink className="row-link" style={{ minWidth: 220 }} to={`/assets/${l.secondary_asset.id}`}>
                  {l.secondary_asset.name}
                </RouterLink>
                <span className="muted">{l.secondary_asset.asset_type}</span>
                <button className="secondary" disabled={busyId !== null} onClick={() => confirm(l.id)}>
                  Confirm
                </button>
                <button className="danger" disabled={busyId !== null} onClick={() => reject(l.id)}>
                  Reject
                </button>
              </div>
            ))}

            {group.length > 1 && (
              <div style={{ marginTop: 8 }}>
                <button disabled={busyId !== null} onClick={() => bulkAction(group, "confirm")}>
                  Confirm all {group.length}
                </button>{" "}
                <button className="secondary" disabled={busyId !== null} onClick={() => bulkAction(group, "reject")}>
                  Reject all {group.length}
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
