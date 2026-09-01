import type { Asset, AssetLink, Connector, CredentialRevealed, Topology } from "./types";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${body}`);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json();
}

export const api = {
  listAssets: (
    params: { asset_type?: string; connector_id?: number; q?: string; include_merged?: boolean } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.asset_type) qs.set("asset_type", params.asset_type);
    if (params.connector_id !== undefined) qs.set("connector_id", String(params.connector_id));
    if (params.q) qs.set("q", params.q);
    if (params.include_merged) qs.set("include_merged", "true");
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<Asset[]>(`/api/assets${suffix}`);
  },
  getAsset: (id: number) => request<Asset>(`/api/assets/${id}`),
  createAsset: (payload: Partial<Asset> & { asset_type: string; name: string }) =>
    request<Asset>("/api/assets", { method: "POST", body: JSON.stringify(payload) }),
  enrichAsset: (id: number, payload: Partial<Pick<Asset, "notes" | "tags" | "ports" | "services">>) =>
    request<Asset>(`/api/assets/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteAsset: (id: number) => request<void>(`/api/assets/${id}`, { method: "DELETE" }),

  addCredential: (assetId: number, payload: { label: string; username?: string; secret?: string; notes?: string }) =>
    request(`/api/assets/${assetId}/credentials`, { method: "POST", body: JSON.stringify(payload) }),
  revealCredential: (id: number) => request<CredentialRevealed>(`/api/credentials/${id}/reveal`),
  deleteCredential: (id: number) => request<void>(`/api/credentials/${id}`, { method: "DELETE" }),

  listConnectors: () => request<Connector[]>("/api/connectors"),
  createConnector: (payload: {
    type: string;
    name: string;
    base_url: string;
    verify_ssl: boolean;
    enabled: boolean;
    credentials: Record<string, string>;
  }) => request<Connector>("/api/connectors", { method: "POST", body: JSON.stringify(payload) }),
  deleteConnector: (id: number) => request<void>(`/api/connectors/${id}`, { method: "DELETE" }),
  pollConnectorNow: (id: number) => request<Connector>(`/api/connectors/${id}/poll-now`, { method: "POST" }),

  listLinks: (status: string = "pending") => request<AssetLink[]>(`/api/links?status=${status}`),
  confirmLink: (id: number) => request<AssetLink>(`/api/links/${id}/confirm`, { method: "POST" }),
  rejectLink: (id: number) => request<AssetLink>(`/api/links/${id}/reject`, { method: "POST" }),

  getTopology: () => request<Topology>("/api/topology"),
};
