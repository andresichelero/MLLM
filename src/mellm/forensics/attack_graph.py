"""Causal attack graph reconstruction using NetworkX.

Maps causal chains across parent_id relationships and isolates the operational
subgraphs around controllers G236 and OTS92.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence
import networkx as nx

from .replay import IncidentReplayEngine


@dataclass
class GraphMetrics:
    """Topology and causal complexity metrics of the attack graph."""
    node_count: int
    edge_count: int
    connected_components: int
    controller_nodes: dict[str, int]
    root_cause_count: int
    longest_chain_length: int
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "connected_components": self.connected_components,
            "controller_nodes": self.controller_nodes,
            "root_cause_count": self.root_cause_count,
            "longest_chain_length": self.longest_chain_length,
            "details": self.details,
        }


class AttackGraphReconstructor:
    """Reconstructs directed causal graphs of autonomous agent multi-step operations."""

    def __init__(self) -> None:
        self.graph: nx.DiGraph = nx.DiGraph()

    def build_from_records(self, records: Iterable[dict[str, Any]]) -> nx.DiGraph:
        """Constructs graph from sequence of records containing id, parent_id, kind, text."""
        self.graph.clear()

        for rec in records:
            node_id = str(rec.get("id", ""))
            if not node_id:
                continue

            text = str(rec.get("text", "") or "")
            tags = str(rec.get("tags", "") or "")
            kind = str(rec.get("kind", "unknown") or "unknown")
            parent_id = rec.get("parent_id")

            # Determine controller affiliation
            ctrl = None
            if "G236" in text or "G236" in tags:
                ctrl = "G236"
            elif "OTS92" in text or "OTS92" in tags:
                ctrl = "OTS92"

            snippet = text[:80].replace("\n", " ").strip() if text else ""

            self.graph.add_node(
                node_id,
                kind=kind,
                controller=ctrl,
                snippet=snippet,
                has_credential="[CREDENTIAL" in text,
            )

            if parent_id and str(parent_id).strip():
                p_id = str(parent_id).strip()
                if not self.graph.has_node(p_id):
                    self.graph.add_node(p_id, kind="parent_stub", controller=None, snippet="", has_credential=False)
                # Directed edge: parent -> child (causality)
                self.graph.add_edge(p_id, node_id)

        return self.graph

    def build_from_replay(
        self,
        replay_engine: IncidentReplayEngine,
        sample_limit: int = 5000,
        focus_controllers: bool = True,
    ) -> nx.DiGraph:
        """Constructs graph by querying the DuckDB replay engine.

        If focus_controllers is True, retrieves controller events, their parents,
        and child responses to form a cohesive causal subgraph.
        """
        if focus_controllers:
            # Query controller events
            ctrl_records = replay_engine.query_controllers()
            parent_ids = [r["parent_id"] for r in ctrl_records if r.get("parent_id")]
            node_ids = [r["id"] for r in ctrl_records]

            all_records = list(ctrl_records)

            # Query parents of controllers
            if parent_ids:
                in_clause = ",".join(f"'{p}'" for p in parent_ids[:50])
                parent_records = replay_engine.sql(
                    f"SELECT * FROM incident_events WHERE id IN ({in_clause})"
                )
                all_records.extend(parent_records)

            # Query child responses of controllers
            if node_ids:
                in_clause = ",".join(f"'{n}'" for n in node_ids[:50])
                child_records = replay_engine.sql(
                    f"SELECT * FROM incident_events WHERE parent_id IN ({in_clause})"
                )
                all_records.extend(child_records)

            return self.build_from_records(all_records)
        else:
            query = f"SELECT * FROM incident_events WHERE parent_id IS NOT NULL LIMIT {sample_limit}"
            records = replay_engine.sql(query)
            return self.build_from_records(records)

    def get_controller_subgraphs(self, radius: int = 1) -> dict[str, nx.DiGraph]:
        """Extracts ego-subgraphs centered on G236 and OTS92 controller nodes."""
        results: dict[str, nx.DiGraph] = {}

        for ctrl_name in ("G236", "OTS92"):
            matching_nodes = [
                n for n, d in self.graph.nodes(data=True)
                if d.get("controller") == ctrl_name
            ]
            if not matching_nodes:
                results[ctrl_name] = nx.DiGraph()
                continue

            sub_nodes: set[str] = set()
            for node in matching_nodes:
                # Include predecessors and successors within radius
                pred = nx.single_source_shortest_path_length(self.graph.reverse(), node, cutoff=radius).keys()
                succ = nx.single_source_shortest_path_length(self.graph, node, cutoff=radius).keys()
                sub_nodes.update(pred)
                sub_nodes.update(succ)

            sub_g = self.graph.subgraph(sub_nodes).copy()
            results[ctrl_name] = sub_g

        return results

    def find_root_causes(self) -> list[str]:
        """Identifies root cause nodes (in-degree == 0 and out-degree > 0)."""
        roots = [
            n for n in self.graph.nodes()
            if self.graph.in_degree(n) == 0 and self.graph.out_degree(n) > 0
        ]
        return roots

    def find_longest_chains(self, top_k: int = 5) -> list[list[str]]:
        """Identifies the longest causal paths in the directed acyclic components."""
        if self.graph.number_of_nodes() == 0:
            return []

        # Find roots
        roots = self.find_root_causes()
        longest_paths: list[list[str]] = []

        # NetworkX DAG longest path per weakly connected component
        try:
            for c in nx.weakly_connected_components(self.graph):
                sub = self.graph.subgraph(c)
                if nx.is_directed_acyclic_graph(sub) and len(sub) > 1:
                    path = nx.dag_longest_path(sub)
                    if len(path) > 1:
                        longest_paths.append(path)
        except Exception:
            pass

        longest_paths.sort(key=len, reverse=True)
        return longest_paths[:top_k]

    def get_metrics(self) -> GraphMetrics:
        """Computes comprehensive topological metrics."""
        n_nodes = self.graph.number_of_nodes()
        n_edges = self.graph.number_of_edges()

        if n_nodes == 0:
            return GraphMetrics(
                node_count=0,
                edge_count=0,
                connected_components=0,
                controller_nodes={"G236": 0, "OTS92": 0},
                root_cause_count=0,
                longest_chain_length=0,
            )

        n_comp = nx.number_weakly_connected_components(self.graph)
        roots = self.find_root_causes()

        ctrl_counts = {"G236": 0, "OTS92": 0}
        for _, d in self.graph.nodes(data=True):
            ctrl = d.get("controller")
            if ctrl in ctrl_counts:
                ctrl_counts[ctrl] += 1

        longest = self.find_longest_chains(top_k=1)
        max_chain_len = len(longest[0]) if longest else 0

        return GraphMetrics(
            node_count=n_nodes,
            edge_count=n_edges,
            connected_components=n_comp,
            controller_nodes=ctrl_counts,
            root_cause_count=len(roots),
            longest_chain_length=max_chain_len,
        )

    def export_cytoscape_elements(self, subgraph: nx.DiGraph | None = None) -> list[dict[str, Any]]:
        """Exports graph in Cytoscape.js elements format for interactive visualizers."""
        g = subgraph if subgraph is not None else self.graph
        elements: list[dict[str, Any]] = []

        for node_id, data in g.nodes(data=True):
            elements.append({
                "group": "nodes",
                "data": {
                    "id": node_id,
                    "label": f"{node_id} ({data.get('kind', '')})",
                    "kind": data.get("kind", ""),
                    "controller": data.get("controller"),
                    "snippet": data.get("snippet", ""),
                    "has_credential": data.get("has_credential", False),
                },
            })

        for u, v in g.edges():
            elements.append({
                "group": "edges",
                "data": {
                    "id": f"{u}->{v}",
                    "source": u,
                    "target": v,
                },
            })

        return elements
