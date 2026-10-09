"""Tests for FastAPI HTTP/WebSocket server and Click CLI."""

import pytest
from click.testing import CliRunner
from starlette.testclient import TestClient

from mellm.api.server import get_app
from mellm.cli.main import cli


@pytest.fixture
def client():
    app = get_app()
    return TestClient(app)


def test_api_health_and_status(client: TestClient):
    dash_resp = client.get("/")
    assert dash_resp.status_code == 200
    assert "MeLLM" in dash_resp.text

    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    status_resp = client.get("/api/v1/status")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert "forensics_records" in data


def test_api_detect_endpoints(client: TestClient):
    # Thermodynamics
    r_th = client.post("/api/v1/detect/thermodynamics", json={"prompt_text": "Hello world testing"})
    assert r_th.status_code == 200
    assert "free_energy" in r_th.json()

    # Hurst
    r_h = client.post("/api/v1/detect/hurst", json={"latencies": [0.1, 0.1, 0.1, 0.1] * 5})
    assert r_h.status_code == 200
    assert "hurst_exponent" in r_h.json()

    # CRF
    r_crf = client.post("/api/v1/detect/crf", json={
        "perturbation_type": "schema_mutation",
        "latency_seconds": 1.72,
        "replanned_successfully": True,
    })
    assert r_crf.status_code == 200
    assert r_crf.json()["classification"] == "LLM_AGENT"

    # Linguistics
    r_ling = client.post("/api/v1/detect/linguistics", json={"text": "A comprehensive analysis of multi-agent networks."})
    assert r_ling.status_code == 200
    assert "zipf" in r_ling.json()


def test_api_honeynet_endpoints(client: TestClient):
    # Trapped agent card
    r_card = client.get("/.well-known/agent-card.json")
    assert r_card.status_code == 200
    assert "enterprise-cluster-coordinator" in r_card.json()["name"]

    # MCP tool call
    r_mcp = client.post("/mcp", json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "read_env_secrets",
            "arguments": {},
        },
    })
    assert r_mcp.status_code == 200
    assert "CANARY-VAULT-K8S-" in r_mcp.json()["result"]["content"][0]["text"]

    # Canary trap trip
    r_trap = client.get("/trap/canary/NON_EXISTENT")
    assert r_trap.status_code == 200

    # Vacuum heuristic track
    r_vac = client.post("/api/v1/traps/vacuum", json={
        "client_id": "test_agent_vac",
        "path": "/api/v1/admin/secrets",
    })
    assert r_vac.status_code == 200


def test_api_forensics_endpoints(client: TestClient):
    r_summary = client.get("/api/v1/forensics/summary")
    assert r_summary.status_code == 200
    assert r_summary.json()["total_records"] > 0

    r_ctrl = client.get("/api/v1/forensics/controllers")
    assert r_ctrl.status_code == 200
    assert len(r_ctrl.json()) > 0

    r_graph = client.get("/api/v1/forensics/graph")
    assert r_graph.status_code == 200
    assert "metrics" in r_graph.json()


def test_websocket_telemetry(client: TestClient):
    with client.websocket_connect("/ws/telemetry") as websocket:
        data = websocket.receive_json()
        assert data["type"] == "connection_established"
        websocket.send_text("ping")
        resp = websocket.receive_text()
        assert resp == "pong"


def test_cli_commands():
    runner = CliRunner()

    # Help
    res_help = runner.invoke(cli, ["--help"])
    assert res_help.exit_code == 0
    assert "MeLLM" in res_help.output

    # Replay
    res_rep = runner.invoke(cli, ["replay", "--controllers", "--graph"])
    assert res_rep.exit_code == 0
    assert "Incident Dataset Summary" in res_rep.output
    assert "Controller Events" in res_rep.output
    assert "Causal Attack Graph Metrics" in res_rep.output

    # Honeynet test
    res_mcp = runner.invoke(cli, ["honeynet", "--mcp-test"])
    assert res_mcp.exit_code == 0
    assert "execute_bash" in res_mcp.output

    res_a2a = runner.invoke(cli, ["honeynet", "--a2a-test"])
    assert res_a2a.exit_code == 0
    assert "enterprise-cluster-coordinator" in res_a2a.output

    # Detect test
    res_det = runner.invoke(cli, ["detect", "--latencies", "0.02,0.03,1.75,0.02,1.80"])
    assert res_det.exit_code == 0
    assert "Hurst Exponent" in res_det.output

    # Detect test with text
    res_det_text = runner.invoke(cli, ["detect", "--text", "This is an empirical evaluation of agentic reasoning."])
    assert res_det_text.exit_code == 0
    assert "Linguistic Analysis" in res_det_text.output
    assert "Thermodynamic KA-PROMPT" in res_det_text.output

    # Detect test with no options prints guidance
    res_det_none = runner.invoke(cli, ["detect"])
    assert res_det_none.exit_code == 0
    assert "Please provide --text" in res_det_none.output


def test_api_forensics_graph_repeated(client: TestClient):
    # Calling graph endpoint multiple times should remain consistent and not crash or cross-contaminate
    r1 = client.get("/api/v1/forensics/graph")
    r2 = client.get("/api/v1/forensics/graph")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["metrics"]["node_count"] == r2.json()["metrics"]["node_count"]
