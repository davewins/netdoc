import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { DataSet, Network } from "vis-network/standalone/esm/vis-network";
import { api } from "../api";
import { useTheme } from "../theme";

const GRAPH_COLORS = {
  dark: { font: "#e6e8eb", edge: "#2a2e37" },
  light: { font: "#1a1d23", edge: "#c3c8d1" },
};

const TYPE_STYLE: Record<string, { color: string; shape: string; label: string }> = {
  proxmox_node: { color: "#4f8cff", shape: "box", label: "Proxmox node" },
  vm: { color: "#3fb950", shape: "ellipse", label: "VM" },
  lxc: { color: "#3fb950", shape: "diamond", label: "LXC container" },
  docker_host: { color: "#e5a53b", shape: "box", label: "Docker host" },
  docker_stack: { color: "#e5a53b", shape: "database", label: "Docker stack" },
  docker_container: { color: "#e5a53b", shape: "ellipse", label: "Docker container" },
  dns_record: { color: "#8b909c", shape: "dot", label: "DNS record" },
  dhcp_reservation: { color: "#8b909c", shape: "dot", label: "DHCP reservation" },
  device: { color: "#c97ce5", shape: "dot", label: "Device" },
  host: { color: "#c97ce5", shape: "dot", label: "Host (scanned)" },
  k8s_node: { color: "#4f8cff", shape: "box", label: "Kubernetes node" },
  k8s_pod: { color: "#e5a53b", shape: "ellipse", label: "Kubernetes pod" },
  ha_device: { color: "#c97ce5", shape: "box", label: "Home Assistant device" },
  ha_entity: { color: "#c97ce5", shape: "triangle", label: "Home Assistant entity" },
  uptime_monitor: { color: "#8b909c", shape: "star", label: "Uptime Kuma monitor" },
  wireguard_peer: { color: "#3fb950", shape: "hexagon", label: "WireGuard peer" },
};
const DEFAULT_STYLE = { color: "#8b909c", shape: "dot", label: "Other" };

// A node whose connector is tagged with a site gets a colored ring around
// it (in addition to the type fill above) so a remote location's assets
// stand out in the graph. Palette is deliberately distinct from the
// TYPE_STYLE hues above so the two encodings don't get confused for one
// another; picked per site name via a stable hash so it stays the same
// across refreshes without needing to persist an assignment anywhere.
const SITE_RING_COLORS = ["#f0b429", "#2dd4bf", "#f472b6", "#a3e635", "#fb923c", "#38bdf8"];

function siteRingColor(site: string): string {
  let hash = 0;
  for (let i = 0; i < site.length; i++) hash = (hash * 31 + site.charCodeAt(i)) | 0;
  return SITE_RING_COLORS[Math.abs(hash) % SITE_RING_COLORS.length];
}

const REFRESH_MS = 15000;

function ShapeSwatch({ shape, color }: { shape: string; color: string }) {
  const common = { fill: color, stroke: "none" };
  return (
    <svg width={18} height={18} viewBox="0 0 20 20" style={{ flexShrink: 0 }}>
      {shape === "box" && <rect x="2" y="4" width="16" height="12" rx="2" {...common} />}
      {shape === "ellipse" && <ellipse cx="10" cy="10" rx="9" ry="6" {...common} />}
      {shape === "dot" && <circle cx="10" cy="10" r="6" {...common} />}
      {shape === "diamond" && <polygon points="10,1 19,10 10,19 1,10" {...common} />}
      {shape === "triangle" && <polygon points="10,2 19,17 1,17" {...common} />}
      {shape === "hexagon" && <polygon points="15,2 19,10 15,18 5,18 1,10 5,2" {...common} />}
      {shape === "star" && (
        <polygon
          points="10,1 12.4,7.1 19,7.6 13.9,11.8 15.6,18.2 10,14.6 4.4,18.2 6.1,11.8 1,7.6 7.6,7.1"
          {...common}
        />
      )}
      {shape === "database" && (
        <g fill={color}>
          <ellipse cx="10" cy="5" rx="8" ry="3" />
          <path d="M2 5v10a8 3 0 0 0 16 0V5" />
          <ellipse cx="10" cy="15" rx="8" ry="3" fill={color} opacity="0.6" />
        </g>
      )}
    </svg>
  );
}

export default function NetworkMap() {
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  const nodesRef = useRef(new DataSet<any>());
  const edgesRef = useRef(new DataSet<any>());
  const navigate = useNavigate();
  const { theme } = useTheme();
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sites, setSites] = useState<string[]>([]);

  useEffect(() => {
    if (!containerRef.current) return;

    // Captures whatever theme is current at mount time - later toggles are
    // handled by the separate effect below via setOptions() rather than by
    // rerunning this one, so switching theme doesn't blow away node
    // positions and restart the physics simulation.
    const initialColors = GRAPH_COLORS[theme];
    const network = new Network(
      containerRef.current,
      { nodes: nodesRef.current, edges: edgesRef.current },
      {
        physics: { stabilization: true, barnesHut: { springLength: 120 } },
        interaction: { hover: true },
        nodes: { font: { color: initialColors.font }, borderWidth: 1 },
        edges: { color: initialColors.edge, smooth: { type: "dynamic", enabled: true, roundness: 0.5 } },
      },
    );
    networkRef.current = network;
    network.on("doubleClick", (params) => {
      if (params.nodes.length > 0) navigate(`/assets/${params.nodes[0]}`);
    });
    // Fires whenever physics settles - on first load, and again after any
    // refresh adds/moves nodes. Fitting here (rather than on a guessed
    // delay) means the bounding box always reflects final positions, not
    // a mid-simulation snapshot.
    network.on("stabilizationIterationsDone", () => network.fit({ animation: true }));

    // vis-network can size its canvas from the container's layout-in-
    // progress dimensions if it initializes before the flex layout
    // settles, which then centers content relative to the wrong width.
    // A ResizeObserver keeps the canvas (and the fit) matched to the
    // container's real, final size.
    const resizeObserver = new ResizeObserver(() => {
      network.redraw();
      network.fit({ animation: false });
    });
    resizeObserver.observe(containerRef.current);

    async function refresh() {
      try {
        const topo = await api.getTopology();
        const nodeData = topo.nodes.map((n) => {
          const style = TYPE_STYLE[n.asset_type] ?? DEFAULT_STYLE;
          const label = n.ip_address ? `${n.name}\n${n.ip_address}` : n.name;
          const border = n.site ? siteRingColor(n.site) : style.color;
          return {
            id: n.id,
            label,
            shape: style.shape,
            color: { background: style.color, border },
            borderWidth: n.site ? 3 : 1,
            title: n.site ? `${style.label} · ${n.site}` : style.label,
          };
        });
        setSites([...new Set(topo.nodes.map((n) => n.site).filter((s): s is string => !!s))].sort());
        const edgeData = topo.edges.map((e) => ({ id: `${e.source}-${e.target}`, from: e.source, to: e.target }));

        // Upsert rather than clear+add, so nodes that already exist keep the
        // position physics settled them into instead of re-simulating the
        // whole graph (and visibly jiggling) on every refresh.
        const keepNodeIds = new Set<unknown>(nodeData.map((n) => n.id));
        for (const id of nodesRef.current.getIds()) {
          if (!keepNodeIds.has(id)) nodesRef.current.remove(id as never);
        }
        nodesRef.current.update(nodeData);

        const keepEdgeIds = new Set<unknown>(edgeData.map((e) => e.id));
        for (const id of edgesRef.current.getIds()) {
          if (!keepEdgeIds.has(id)) edgesRef.current.remove(id as never);
        }
        edgesRef.current.update(edgeData);

        setLastUpdated(new Date());
        setError(null);
      } catch (e) {
        setError(String(e));
      }
    }

    refresh();
    const interval = setInterval(refresh, REFRESH_MS);
    return () => {
      clearInterval(interval);
      resizeObserver.disconnect();
      network.destroy();
    };
  }, [navigate]);

  useEffect(() => {
    const colors = GRAPH_COLORS[theme];
    networkRef.current?.setOptions({
      nodes: { font: { color: colors.font } },
      edges: { color: colors.edge },
    });
  }, [theme]);

  return (
    <div>
      <h1>Network map</h1>
      <p className="muted">
        Double-click a node to open it. Refreshes every {REFRESH_MS / 1000}s
        {lastUpdated ? ` · last updated ${lastUpdated.toLocaleTimeString()}` : ""}.
      </p>
      {error && <div className="card status-error">{error}</div>}
      <div
        ref={containerRef}
        style={{ height: "70vh", border: "1px solid var(--border)", borderRadius: 8, background: "var(--input-bg)" }}
      />

      <div className="card" style={{ display: "flex", flexWrap: "wrap", gap: "20px 28px", marginTop: 16 }}>
        {Object.entries(TYPE_STYLE).map(([type, style]) => (
          <div key={type} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
            <ShapeSwatch shape={style.shape} color={style.color} />
            <span className="muted">{style.label}</span>
          </div>
        ))}
      </div>

      {sites.length > 0 && (
        <div className="card" style={{ display: "flex", flexWrap: "wrap", gap: "20px 28px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
            <span className="muted">Colored ring = remote site:</span>
          </div>
          {sites.map((s) => (
            <div key={s} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
              <svg width={18} height={18} viewBox="0 0 20 20" style={{ flexShrink: 0 }}>
                <circle cx="10" cy="10" r="7" fill="none" stroke={siteRingColor(s)} strokeWidth="3" />
              </svg>
              <span className="muted">{s}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
