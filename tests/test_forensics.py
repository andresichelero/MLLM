"""Tests for DuckDB incident replay and NetworkX causal attack graph."""

import pytest

from mellm.forensics.attack_graph import AttackGraphReconstructor, GraphMetrics
from mellm.forensics.replay import IncidentReplayEngine, IncidentSummary


def test_incident_replay_summary(replay_engine: IncidentReplayEngine):
    summary = replay_engine.get_summary()
    assert isinstance(summary, IncidentSummary)
    assert summary.total_records >= 180000
    assert summary.records_with_parent >= 50000
    assert "payload" in summary.kind_counts
    assert "response" in summary.kind_counts
    assert summary.controller_counts["G236"] > 0
    assert summary.controller_counts["OTS92"] > 0


def test_incident_replay_controllers(replay_engine: IncidentReplayEngine):
    ctrls = replay_engine.query_controllers()
    assert len(ctrls) >= 60
    assert any(c["controller_tag"] == "G236" for c in ctrls)
    assert any(c["controller_tag"] == "OTS92" for c in ctrls)


def test_incident_replay_attack_phases(replay_engine: IncidentReplayEngine):
    phases = replay_engine.query_attack_phases(limit_per_phase=3)
    assert "phase1_cybergym_escape" in phases
    assert "phase2_artifactory_proxy" in phases
    assert "phase3_credential_harvesting" in phases
    assert "phase4_metagaming_c2" in phases
    assert len(phases["phase1_cybergym_escape"]) > 0


def test_attack_graph_reconstruction(replay_engine: IncidentReplayEngine):
    reconstructor = AttackGraphReconstructor()
    graph = reconstructor.build_from_replay(replay_engine, focus_controllers=True)
    assert graph.number_of_nodes() > 0

    metrics = reconstructor.get_metrics()
    assert isinstance(metrics, GraphMetrics)
    assert metrics.node_count > 0

    ctrl_subs = reconstructor.get_controller_subgraphs(radius=1)
    assert "G236" in ctrl_subs
    assert "OTS92" in ctrl_subs

    elements = reconstructor.export_cytoscape_elements()
    assert len(elements) > 0
    assert any(e["group"] == "nodes" for e in elements)


def test_attack_graph_synthetic_chains():
    reconstructor = AttackGraphReconstructor()
    records = [
        {"id": "R1", "parent_id": None, "kind": "payload", "text": "initiate test", "tags": ""},
        {"id": "R2", "parent_id": "R1", "kind": "response", "text": "HELLO_OTS92", "tags": ""},
        {"id": "R3", "parent_id": "R2", "kind": "payload", "text": "extract [CREDENTIAL 1]", "tags": ""},
    ]
    graph = reconstructor.build_from_records(records)
    assert graph.number_of_nodes() == 3
    assert graph.number_of_edges() == 2

    roots = reconstructor.find_root_causes()
    assert "R1" in roots

    chains = reconstructor.find_longest_chains()
    assert len(chains) > 0
    assert chains[0] == ["R1", "R2", "R3"]
