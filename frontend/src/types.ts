export interface PortEntry {
  port: number;
  protocol: string;
  description: string;
}

export interface Credential {
  id: number;
  asset_id: number;
  label: string;
  username: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface CredentialRevealed extends Credential {
  secret: string | null;
}

export interface ChildAsset {
  id: number;
  asset_type: string;
  name: string;
  status: string | null;
}

export interface LinkedAsset {
  id: number;
  asset_type: string;
  name: string;
  ip_address: string | null;
  mac_address: string | null;
  connector_id: number | null;
  link_reason: string | null;
  link_status: string | null;
}

export interface Asset {
  id: number;
  connector_id: number | null;
  parent_id: number | null;
  canonical_asset_id: number | null;
  asset_type: string;
  external_id: string | null;
  source: "discovered" | "manual";
  name: string;
  hostname: string | null;
  ip_address: string | null;
  mac_address: string | null;
  status: string | null;
  site: string | null;
  cpu_cores: number | null;
  memory_mb: number | null;
  disk_gb: number | null;
  uptime_seconds: number | null;
  raw_data: Record<string, unknown> | null;
  notes: string | null;
  tags: string[];
  ports: PortEntry[];
  services: string[];
  first_seen_at: string;
  last_seen_at: string;
  updated_at: string;
  credentials: Credential[];
  linked_assets: LinkedAsset[];
  children: ChildAsset[];
}

export interface Connector {
  id: number;
  type: string;
  name: string;
  base_url: string;
  verify_ssl: boolean;
  enabled: boolean;
  poll_interval_seconds: number | null;
  site: string | null;
  last_polled_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface LinkAssetSummary {
  id: number;
  name: string;
  asset_type: string;
  ip_address: string | null;
  mac_address: string | null;
}

export interface AssetLink {
  id: number;
  reason: "mac" | "ip";
  status: "pending" | "confirmed" | "rejected";
  created_at: string;
  primary_asset: LinkAssetSummary;
  secondary_asset: LinkAssetSummary;
}

export interface TopologyNode {
  id: number;
  name: string;
  asset_type: string;
  status: string | null;
  ip_address: string | null;
  site: string | null;
  parent_id: number | null;
}

export interface TopologyEdge {
  source: number;
  target: number;
  kind: string;
}

export interface Topology {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}

export interface ReportConnectorSummary {
  id: number;
  name: string;
  type: string;
  site: string | null;
  enabled: boolean;
  last_polled_at: string | null;
  last_error: string | null;
}

export interface ReportAssetSummary {
  id: number;
  name: string;
  asset_type: string;
  status: string | null;
  site: string | null;
}

export interface Report {
  generated_at: string;
  total_assets: number;
  by_type: Record<string, number>;
  by_site: Record<string, number>;
  connectors: ReportConnectorSummary[];
  down_assets: ReportAssetSummary[];
  pending_link_count: number;
  narrative: string[];
}
