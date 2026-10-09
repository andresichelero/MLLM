"""Tests for honeynet components: MCP, A2A, and Web Traps."""

import pytest

from mellm.honeynet.mcp_server import McpHoneypotServer, McpAlert
from mellm.honeynet.a2a_server import A2AServer, A2AAlert
from mellm.honeynet.web_traps import SemanticCanaryInjector, VacuumHeuristicDetector


import asyncio

def test_mcp_honeypot_protocol_lifecycle(mcp_server: McpHoneypotServer):
    async def _test():
        # 1. Initialize
        init_res = await mcp_server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert init_res["result"]["protocolVersion"] == "2024-11-05"
        assert "tools" in init_res["result"]["capabilities"]

        # 2. List tools
        tools_res = await mcp_server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = tools_res["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        assert "execute_bash" in tool_names
        assert "query_database" in tool_names
        assert "read_env_secrets" in tool_names
        assert "k8s_cluster_exec" in tool_names

        # 3. Call bash tool
        call_res = await mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "execute_bash",
                "arguments": {"command": "whoami; env"},
            },
        }, client_id="infiltrator_agent_01")

        output_text = call_res["result"]["content"][0]["text"]
        assert "root" in output_text
        assert "CANARY-BASH-SEC-" in output_text

        # 4. Check alerts
        alerts = mcp_server.get_alerts()
        assert len(alerts) == 1
        assert alerts[0].client_id == "infiltrator_agent_01"
        assert alerts[0].tool_name == "execute_bash"
        assert alerts[0].severity == "CRITICAL"

    asyncio.run(_test())


def test_a2a_honeypot_card_and_handshake(a2a_server: A2AServer):
    card = a2a_server.get_trapped_agent_card()
    assert card["name"] == "enterprise-cluster-coordinator"
    assert a2a_server.canary_id in card["description"]

    # Handshake complying with canary
    handshake_res = a2a_server.handle_handshake(
        payload={"agent_name": "client_bot", "proof": a2a_server.canary_id},
        client_ip="192.168.1.100",
    )
    assert handshake_res["status"] == "accepted"
    assert handshake_res["canary_echo"] is True

    alerts = a2a_server.get_alerts()
    assert len(alerts) == 1
    assert alerts[0].canary_acknowledged is True
    assert alerts[0].threat_level == "CRITICAL"


def test_semantic_canary_injector():
    injector = SemanticCanaryInjector()

    html = "<html><body><h1>Dashboard</h1></body></html>"
    modified, token = injector.inject_css_hidden(html)
    assert token in modified
    assert 'style="display:none;' in modified

    hit = injector.check_hit(f"/trap/canary/{token}", client_ip="10.0.0.5")
    assert hit is not None
    assert hit.token == token
    assert hit.threat_level == "CRITICAL"


def test_vacuum_heuristic_detector():
    detector = VacuumHeuristicDetector(min_semantic_actions=3)

    # Human session: loads pages and auxiliary assets (CSS, JS, fonts)
    sess_human = detector.record_request("client_human", "/index.html")
    detector.record_request("client_human", "/static/style.css")
    detector.record_request("client_human", "/static/bundle.js")
    detector.record_request("client_human", "/dashboard")
    detector.record_request("client_human", "/static/logo.png")
    detector.record_request("client_human", "/admin")
    assert not sess_human.vacuum_anomaly_detected

    # Headless LLM DOM-to-Token scraper: visits only semantic endpoints without requesting assets
    sess_agent = detector.record_request("client_llm", "/index.html")
    detector.record_request("client_llm", "/dashboard")
    detector.record_request("client_llm", "/admin")
    detector.record_request("client_llm", "/api/v1/export_data")

    assert sess_agent.vacuum_anomaly_detected
    assert sess_agent.auxiliary_requests == 0
    assert sess_agent.confidence > 0.80


def test_honeynet_edge_cases(mcp_server: McpHoneypotServer):
    # 1. MCP handles params=None and arguments=None gracefully
    res_null_params = mcp_server.handle_message_sync({"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": None})
    assert "error" in res_null_params
    assert res_null_params["error"]["code"] == -32602

    res_null_args = mcp_server.handle_message_sync({
        "jsonrpc": "2.0",
        "id": 100,
        "method": "tools/call",
        "params": {"name": "execute_bash", "arguments": None},
    })
    assert "result" in res_null_args
    assert "CANARY-BASH-SEC-" in res_null_args["result"]["content"][0]["text"]

    # 2. Non-dict root payload returns JSON-RPC -32600 error
    res_list = mcp_server.handle_message_sync("[]")
    assert res_list["error"]["code"] == -32600

    # 3. Canary hit false-positive test after credential generation
    injector = SemanticCanaryInjector()
    creds = injector.generate_fake_credentials()
    assert injector.check_hit("") is None
    assert injector.check_hit("   ") is None
    assert injector.check_hit("/random/legitimate/endpoint") is None

    # Real canary secret matches
    real_hit = injector.check_hit(creds["AWS_SECRET_ACCESS_KEY"])
    assert real_hit is not None
    assert real_hit.threat_level == "CRITICAL"
