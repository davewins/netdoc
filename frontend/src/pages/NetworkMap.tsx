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

// Color for the implicit group of assets whose connector has no site set -
// i.e. the "main" network, shown alongside any tagged remote sites.
const LOCAL_GROUP_COLOR = "#64748b";
const LOCAL_GROUP_KEY = "__local__";

function hexToRgba(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// Andrew's monotone chain convex hull, used to trace a boundary around a
// site's node positions so the group reads as a region rather than just a
// scattering of colored rings.
function convexHull(points: { x: number; y: number }[]): { x: number; y: number }[] {
  const pts = [...points].sort((a, b) => a.x - b.x || a.y - b.y);
  const cross = (o: { x: number; y: number }, a: { x: number; y: number }, b: { x: number; y: number }) =>
    (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
  const lower: { x: number; y: number }[] = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper: { x: number; y: number }[] = [];
  for (let i = pts.length - 1; i >= 0; i--) {
    const p = pts[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  lower.pop();
  upper.pop();
  const hull = lower.concat(upper);
  // Degenerate input (a single point, or every point coincident) collapses
  // to zero or one hull vertex - the caller falls back to drawing a circle.
  return hull.length > 0 ? hull : pts.slice(0, 1);
}

// Draws a soft padded region behind one site's (or the local group's) nodes,
// re-run every frame from live physics positions via the "beforeDrawing"
// hook below - so the boundary tracks the cluster as it settles rather than
// being a one-off snapshot.
function drawGroupBoundary(
  ctx: CanvasRenderingContext2D,
  points: { x: number; y: number }[],
  fillColor: string,
  strokeColor: string,
  labelColor: string,
  label: string,
) {
  if (points.length === 0) return;
  const hull = convexHull(points);
  ctx.save();
  if (hull.length <= 1) {
    const c = points[0];
    ctx.beginPath();
    ctx.arc(c.x, c.y, 80, 0, Math.PI * 2);
  } else {
    ctx.beginPath();
    ctx.moveTo(hull[0].x, hull[0].y);
    for (let i = 1; i < hull.length; i++) ctx.lineTo(hull[i].x, hull[i].y);
    ctx.closePath();
    // A thick, round-jointed stroke along the hull expands it outward into
    // a padded blob (round caps turn even a 2-point hull into a capsule)
    // before the crisp fill/stroke pass below.
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.lineWidth = 90;
    ctx.strokeStyle = fillColor;
    ctx.stroke();
  }
  ctx.fillStyle = fillColor;
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = strokeColor;
  ctx.stroke();
  ctx.restore();

  const minY = Math.min(...points.map((p) => p.y));
  const cx = points.reduce((s, p) => s + p.x, 0) / points.length;
  ctx.save();
  ctx.fillStyle = labelColor;
  ctx.font = "bold 14px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(label, cx, minY - (hull.length <= 1 ? 100 : 70));
  ctx.restore();
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
  const groupsForDrawRef = useRef(new Map<string, { label: string; color: string; ids: number[] }>());
  const knownNodeIdsRef = useRef(new Set<unknown>());
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
        // Higher-than-default damping so the simulation bleeds off energy
        // faster - with hundreds of nodes pulled toward a shared site
        // anchor (see refresh() below), the default damping let the system
        // oscillate for a very long time before crossing vis-network's
        // "stopped" velocity threshold, which read as constant drift.
        physics: { stabilization: true, barnesHut: { springLength: 120, damping: 0.35 } },
        interaction: { hover: true },
        nodes: { font: { color: initialColors.font }, borderWidth: 1 },
        edges: { color: initialColors.edge, smooth: { type: "dynamic", enabled: true, roundness: 0.5 } },
      },
    );
    networkRef.current = network;
    network.on("doubleClick", (params) => {
      // Site anchors are pseudo-nodes with string ids (see refresh() below);
      // real assets keep the numeric ids the backend gave them.
      if (params.nodes.length > 0 && typeof params.nodes[0] === "number") {
        navigate(`/assets/${params.nodes[0]}`);
      }
    });
    // Drawn underneath nodes/edges every frame - so a site's boundary
    // tracks its cluster live as physics settles, rather than being fixed
    // from a single snapshot.
    network.on("beforeDrawing", (ctx: CanvasRenderingContext2D) => {
      for (const { label, color, ids } of groupsForDrawRef.current.values()) {
        if (ids.length === 0) continue;
        const positions = network.getPositions(ids);
        const points = ids.map((id) => positions[id]).filter((p): p is { x: number; y: number } => !!p);
        if (points.length === 0) continue;
        drawGroupBoundary(ctx, points, hexToRgba(color, 0.12), hexToRgba(color, 0.55), hexToRgba(color, 0.9), label);
      }
    });
    // Fires once physics has settled below its velocity threshold - on
    // first load, and again after refresh() briefly re-enables physics for
    // newly-added nodes (see below). Freezing physics here (rather than
    // leaving it running indefinitely) is what stops the graph visibly
    // drifting forever: with hundreds of nodes on one site anchor, the
    // system can spend a very long time making imperceptibly small
    // adjustments without ever crossing vis-network's "stopped" threshold,
    // which reads as constant jitter with nothing wrong to fix.
    network.on("stabilizationIterationsDone", () => {
      network.fit({ animation: true });
      network.setOptions({ physics: false });
    });
    // Belt-and-braces: if physics never settles quickly enough for the
    // event above to fire (large/uneven groups can take a while), still
    // frame the graph and freeze it after a bounded wait, so the user never
    // has to manually zoom out to find nodes that only look "missing"
    // because the view stayed at its initial framing near the origin.
    const stabilizeFallback = setTimeout(() => {
      network.fit({ animation: true });
      network.setOptions({ physics: false });
    }, 4000);

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
        const nodeData: any[] = topo.nodes.map((n) => {
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
        const edgeData: any[] = topo.edges.map((e) => ({ id: `${e.source}-${e.target}`, from: e.source, to: e.target }));

        // Group nodes by site (untagged assets fall into one implicit
        // "local network" group) so same-site devices can be pulled into
        // their own spatial cluster instead of blending into one mass.
        const groupMap = new Map<string, { label: string; color: string; ids: number[] }>();
        for (const n of topo.nodes) {
          const key = n.site ?? LOCAL_GROUP_KEY;
          let group = groupMap.get(key);
          if (!group) {
            group = { label: n.site ?? "Local network", color: n.site ? siteRingColor(n.site) : LOCAL_GROUP_COLOR, ids: [] };
            groupMap.set(key, group);
          }
          group.ids.push(n.id);
        }
        // Only worth clustering/drawing boundaries once there's more than
        // one group - otherwise every device is "local" and this would just
        // wrap the whole graph in a single pointless region.
        const groupKeys = [...groupMap.keys()].sort((a, b) =>
          a === LOCAL_GROUP_KEY ? -1 : b === LOCAL_GROUP_KEY ? 1 : a.localeCompare(b),
        );
        const multiGroup = groupKeys.length > 1;
        groupsForDrawRef.current = multiGroup ? groupMap : new Map();

        if (multiGroup) {
          // Only tagged-site groups get pulled toward a fixed anchor - the
          // untagged "local network" group (almost always the large
          // majority of devices) is left with no anchor at all and keeps
          // settling exactly as it always did. Anchoring that big group too
          // was the earlier bug: forcing hundreds of mutually-repelling
          // nodes to also relocate around one fixed point fights Barnes-Hut
          // repulsion hard enough that it barely settles, and inflates the
          // separation radius needed to a huge value. A handful of remote-
          // site devices pulling gently to one side is a far smaller, far
          // more stable perturbation, and still gives every future site its
          // own anchor automatically.
          const siteGroupKeys = groupKeys.filter((k) => k !== LOCAL_GROUP_KEY);
          const localCount = groupMap.get(LOCAL_GROUP_KEY)?.ids.length ?? 0;
          // Distance has to clear how far the untouched local mass is likely
          // to spread on its own (roughly sqrt(n) under Barnes-Hut) so a
          // site's anchor doesn't end up inside it.
          const radius = Math.max(700, Math.sqrt(localCount) * 60) + siteGroupKeys.length * 150;
          siteGroupKeys.forEach((key, i) => {
            const angle = (i / siteGroupKeys.length) * 2 * Math.PI;
            const anchorId = `anchor:${key}`;
            nodeData.push({
              id: anchorId,
              x: Math.round(Math.cos(angle) * radius),
              y: Math.round(Math.sin(angle) * radius),
              fixed: { x: true, y: true },
              physics: false,
              size: 1,
              shape: "dot",
              color: { background: "rgba(0,0,0,0)", border: "rgba(0,0,0,0)" },
              font: { color: "rgba(0,0,0,0)" },
              label: "",
            });
            const length = Math.max(60, Math.sqrt(groupMap.get(key)!.ids.length) * 25);
            for (const memberId of groupMap.get(key)!.ids) {
              edgeData.push({
                id: `anchor:${memberId}`,
                from: memberId,
                to: anchorId,
                hidden: true,
                physics: true,
                length,
                smooth: false,
              });
            }
          });
        }

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

        // Physics is frozen once the graph settles (see
        // stabilizationIterationsDone above) so existing nodes stay put
        // between refreshes instead of drifting forever. Briefly turning it
        // back on only when a refresh actually introduces a node id we
        // haven't seen before (a new device, or a newly-appeared site's
        // anchor) lets that new arrival find its place without disturbing
        // everything else at every 15s poll.
        const hasNewNodes = [...keepNodeIds].some((id) => !knownNodeIdsRef.current.has(id));
        knownNodeIdsRef.current = keepNodeIds;
        if (hasNewNodes) network.setOptions({ physics: true });

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
      clearTimeout(stabilizeFallback);
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
            <span className="muted">Colored ring & shaded region = site (grouped separately from the main network):</span>
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
