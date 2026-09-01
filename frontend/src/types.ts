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

export interface Asset {
  id: number;
  connector_id: number | null;
  parent_id: number | null;
  asset_type: string;
  external_id: string | null;
  source: "discovered" | "manual";
  name: string;
  hostname: string | null;
  ip_address: string | null;
  mac_address: string | null;
  status: string | null;
  raw_data: Record<string, unknown> | null;
  notes: string | null;
  tags: string[];
  ports: PortEntry[];
  services: string[];
  first_seen_at: string;
  last_seen_at: string;
  updated_at: string;
  credentials: Credential[];
}

export interface Connector {
  id: number;
  type: string;
  name: string;
  base_url: string;
  verify_ssl: boolean;
  enabled: boolean;
  poll_interval_seconds: number | null;
  last_polled_at: string | null;
  last_error: string | null;
  created_at: string;
}
