import requests

from .base import BaseConnector, ConnectorError, DiscoveredAsset


class KubernetesConnector(BaseConnector):
    """Discovers nodes and pods from a Kubernetes cluster via the raw API server.

    Expected credentials dict: {"token": "<service account bearer token>"}
    Create a read-only service account and grab its token, e.g.:

        kubectl create serviceaccount netdoc -n default
        kubectl create clusterrolebinding netdoc-view \\
          --clusterrole=view --serviceaccount=default:netdoc
        kubectl create token netdoc -n default

    `base_url` is the cluster's API server, e.g. "https://192.168.1.50:6443".
    Clusters typically use a self-signed CA, so leave "Verify TLS
    certificate" off unless you've supplied that CA to the container.

    Only nodes and pods are modeled (no Deployment/ReplicaSet grouping) -
    working out "which Deployment owns this pod" needs walking
    ownerReferences through ReplicaSets, which adds a lot of complexity for
    a detail the pod's own name (usually "<deployment>-<hash>-<hash>")
    already hints at.
    """

    def _headers(self) -> dict:
        token = self.credentials.get("token")
        if not token:
            raise ConnectorError("Kubernetes connector requires a service account token")
        return {"Authorization": f"Bearer {token}"}

    def _get(self, path: str) -> dict:
        resp = requests.get(
            f"{self.base_url}{path}", headers=self._headers(), verify=self.verify_ssl, timeout=15
        )
        if resp.status_code != 200:
            raise ConnectorError(f"Kubernetes API {path} returned {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    @staticmethod
    def _node_status(node: dict) -> str | None:
        for cond in (node.get("status", {}).get("conditions") or []):
            if cond.get("type") == "Ready":
                return "ready" if cond.get("status") == "True" else "not-ready"
        return None

    @staticmethod
    def _node_internal_ip(node: dict) -> str | None:
        for addr in (node.get("status", {}).get("addresses") or []):
            if addr.get("type") == "InternalIP":
                return addr.get("address")
        return None

    @staticmethod
    def _cpu_cores(quantity: str | None) -> float | None:
        if not quantity:
            return None
        if quantity.endswith("m"):
            return round(int(quantity[:-1]) / 1000, 2)
        try:
            return float(quantity)
        except ValueError:
            return None

    @staticmethod
    def _memory_mb(quantity: str | None) -> int | None:
        if not quantity:
            return None
        units = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "Ti": 1024 * 1024}
        for suffix, mb_per_unit in units.items():
            if quantity.endswith(suffix):
                try:
                    return int(float(quantity[: -len(suffix)]) * mb_per_unit)
                except ValueError:
                    return None
        return None

    def poll(self) -> list[DiscoveredAsset]:
        assets: list[DiscoveredAsset] = []

        nodes = self._get("/api/v1/nodes").get("items", [])
        for node in nodes:
            node_name = node["metadata"]["name"]
            capacity = node.get("status", {}).get("capacity", {})
            assets.append(
                DiscoveredAsset(
                    asset_type="k8s_node",
                    external_id=f"node/{node_name}",
                    name=node_name,
                    status=self._node_status(node),
                    ip_address=self._node_internal_ip(node),
                    cpu_cores=self._cpu_cores(capacity.get("cpu")),
                    memory_mb=self._memory_mb(capacity.get("memory")),
                    initial_tags=sorted(
                        label.split("/")[-1]
                        for label in (node.get("metadata", {}).get("labels") or {})
                        if label.startswith("node-role.kubernetes.io/")
                    ),
                    raw_data=node,
                )
            )

        pods = self._get("/api/v1/pods").get("items", [])
        for pod in pods:
            meta = pod.get("metadata", {})
            namespace = meta.get("namespace", "default")
            pod_name = meta.get("name")
            node_name = pod.get("spec", {}).get("nodeName")
            images = sorted({c.get("image") for c in pod.get("spec", {}).get("containers", []) if c.get("image")})

            assets.append(
                DiscoveredAsset(
                    asset_type="k8s_pod",
                    external_id=f"pod/{namespace}/{pod_name}",
                    name=f"{namespace}/{pod_name}",
                    status=pod.get("status", {}).get("phase"),
                    parent_external_id=f"node/{node_name}" if node_name else None,
                    # Deliberately not populated: pod IPs come from the
                    # cluster's internal overlay network (e.g. Flannel's
                    # 10.244.0.0/16 default), reused independently by every
                    # cluster - treating it as a correlatable LAN address
                    # would reproduce the exact false-merge bug the Docker
                    # bridge-IP exclusion in correlation.py exists to avoid,
                    # except across this setup's several k8s clusters
                    # instead of Docker stacks. The real IP is on raw_data.
                    ip_address=None,
                    initial_tags=[namespace],
                    initial_services=images,
                    raw_data=pod,
                )
            )

        return assets
