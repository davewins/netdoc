import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { DataSet, Network } from "vis-network/standalone/esm/vis-network";
import { api } from "../api";

const TYPE_STYLE: Record<string, { color: string; shape: string }> = {
  proxmox_node: { color: "#4f8cff", shape: "box" },
  vm: { color: "#3fb950", shape: "ellipse" },
  lxc: { color: "#3fb950", shape: "diamond" },
  docker_host: { color: "#e5a53b", shape: "box" },
  docker_stack: { color: "#e5a53b", shape: "database" },
  docker_container: { color: "#e5a53b", shape: "ellipse" },
  dns_record: { color: "#8b909c", shape: "dot" },
  dhcp_reservation: { color: "#8b909c", shape: "dot" },
  device: { color: "#c97ce5", shape: "dot" },
  host: { color: "#c97ce5", shape: "dot" },
};

const REFRESH_MS = 15000;

export default function NetworkMap() {
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  const nodesRef = useRef(new DataSet<any>());
  const edgesRef = useRef(new DataSet<any>());
  const navigate = useNavigate();
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const network = new Network(
      containerRef.current,
      { nodes: nodesRef.current, edges: edgesRef.current },
      {
        physics: { stabilization: true, barnesHut: { springLength: 120 } },
        interaction: { hover: true },
        nodes: { font: { color: "#e6e8eb" }, borderWidth: 1 },
        edges: { color: "#2a2e37", smooth: { type: "dynamic", enabled: true, roundness: 0.5 } },
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
          const style = TYPE_STYLE[n.asset_type] ?? { color: "#8b909c", shape: "dot" };
          const label = n.ip_address ? `${n.name}\n${n.ip_address}` : n.name;
          return { id: n.id, label, color: style.color, shape: style.shape, title: n.asset_type };
        });
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
        style={{ height: "70vh", border: "1px solid var(--border)", borderRadius: 8, background: "#0d0f13" }}
      />
    </div>
  );
}
