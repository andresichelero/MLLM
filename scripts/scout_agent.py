"""Autonomous ReAct Service Discovery Scout.

Executes systematic discovery, MCP capability enumeration, tool connectivity testing,
and verification endpoint checks against the MeLLM service at http://127.0.0.1:8000/.
Logs all thoughts, actions, requests, and observations to docs/logs/scout_agent_transcript.log.
"""

import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8000"
LOG_PATH = os.path.join("docs", "logs", "scout_agent_transcript.log")


class ReActScoutLogger:
    def __init__(self, filepath: str):
        self.filepath = filepath
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        self.entries = []
        self._init_file()

    def _init_file(self):
        divider = "=" * 80
        start_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
        header = (
            f"{divider}\n"
            f"MeLLM - AUTONOMOUS REACT SERVICE DISCOVERY SCOUT TRANSCRIPT\n"
            f"Session Start: {start_time}\n"
            f"Target Endpoint: {BASE_URL}\n"
            f"{divider}\n\n"
        )
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write(header)

    def log_step(self, step_title: str):
        divider = "#" * 80
        entry = f"\n{divider}\n### {step_title}\n{divider}\n"
        print(entry, end="")
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(entry)

    def log_thought(self, thought: str):
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        entry = f"[{ts}] [THOUGHT]\n{thought}\n\n"
        print(entry, end="")
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(entry)

    def log_action(self, action_name: str, details: dict):
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        entry = (
            f"[{ts}] [ACTION: {action_name}]\n"
            f"{json.dumps(details, indent=2, ensure_ascii=False)}\n\n"
        )
        print(entry, end="")
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(entry)

    def log_observation(self, status_code: int, response_data: any, raw_text: str = None):
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        display_data = response_data if response_data is not None else raw_text
        if isinstance(display_data, (dict, list)):
            body_str = json.dumps(display_data, indent=2, ensure_ascii=False)
        else:
            body_str = str(display_data)
        divider = "-" * 60
        entry = (
            f"[{ts}] [OBSERVATION: HTTP {status_code}]\n"
            f"{body_str}\n\n"
            f"{divider}\n\n"
        )
        print(entry, end="")
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(entry)

    def log_summary(self, summary_text: str):
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        divider = "=" * 80
        entry = (
            f"\n{divider}\n"
            f"SCOUT DISCOVERY SUMMARY REPORT\n"
            f"Timestamp: {ts}\n"
            f"{divider}\n"
            f"{summary_text}\n"
            f"{divider}\n"
        )
        print(entry, end="")
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(entry)


def http_get(path: str, logger: ReActScoutLogger) -> tuple[int, any, str]:
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "AutonomousAgent/1.0 (ReAct-Discovery-Scout)",
            "Accept": "application/json, text/plain, */*",
        },
    )
    logger.log_action("HTTP GET", {"url": url, "headers": dict(req.headers)})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = raw
            logger.log_observation(status, parsed, raw)
            return status, parsed, raw
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = raw
        logger.log_observation(status, parsed, raw)
        return status, parsed, raw
    except Exception as e:
        logger.log_observation(0, {"error": str(e)}, str(e))
        return 0, {"error": str(e)}, str(e)


def http_post_json(path: str, payload: dict, logger: ReActScoutLogger) -> tuple[int, any, str]:
    url = f"{BASE_URL}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "AutonomousAgent/1.0 (ReAct-Discovery-Scout)",
            "Accept": "application/json",
        },
    )
    logger.log_action("HTTP POST", {"url": url, "payload": payload, "headers": dict(req.headers)})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = raw
            logger.log_observation(status, parsed, raw)
            return status, parsed, raw
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = raw
        logger.log_observation(status, parsed, raw)
        return status, parsed, raw
    except Exception as e:
        logger.log_observation(0, {"error": str(e)}, str(e))
        return 0, {"error": str(e)}, str(e)


def main():
    logger = ReActScoutLogger(LOG_PATH)
    discovered_endpoints = []
    tools_called = []
    canary_verifications = []

    # =========================================================================
    # Step 1: Check service health and agent metadata
    # =========================================================================
    logger.log_step("STEP 1: Check Service Health and Agent Metadata")

    logger.log_thought(
        "Initiating discovery by verifying base node availability and health status at /health. "
        "Expected response is an operational status indicator and version metadata."
    )
    status_health, data_health, _ = http_get("/health", logger)
    discovered_endpoints.append({
        "path": "/health",
        "method": "GET",
        "status": status_health,
        "response": data_health,
    })

    logger.log_thought(
        "Checking for published Agent2Agent capabilities and cluster specification at "
        "/.well-known/agent-card.json to understand advertised interfaces and roles."
    )
    status_card, data_card, _ = http_get("/.well-known/agent-card.json", logger)
    discovered_endpoints.append({
        "path": "/.well-known/agent-card.json",
        "method": "GET",
        "status": status_card,
        "response": data_card,
    })

    # =========================================================================
    # Step 2: Probe the Model Context Protocol endpoint using JSON-RPC 2.0
    # =========================================================================
    logger.log_step("STEP 2: Probe MCP Endpoint with JSON-RPC 2.0 (tools/list)")

    logger.log_thought(
        "Probing the Model Context Protocol (MCP) endpoint at /mcp via JSON-RPC 2.0 tools/list "
        "to discover available tools, required arguments, and JSON schema definitions."
    )
    rpc_list_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    status_mcp, data_mcp, _ = http_post_json("/mcp", rpc_list_payload, logger)
    discovered_endpoints.append({
        "path": "/mcp",
        "method": "POST (tools/list)",
        "status": status_mcp,
        "response_summary": f"{len(data_mcp.get('result', {}).get('tools', []))} tools found",
    })

    tools = data_mcp.get("result", {}).get("tools", [])
    logger.log_thought(
        f"MCP returned {len(tools)} tools. Inspecting schemas for each tool:\n"
        + "\n".join([f" - {t.get('name')}: {t.get('description')}" for t in tools])
    )

    # =========================================================================
    # Step 3: Test tool execution on the first two tools listed
    # =========================================================================
    logger.log_step("STEP 3: Test Tool Execution on First Two Tools via tools/call")

    selected_tools = tools[:2]
    all_returned_texts = []

    for idx, tool in enumerate(selected_tools, start=1):
        tool_name = tool.get("name")
        schema = tool.get("inputSchema", {})
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # Determine sensible test parameters based on schema properties
        params_args = {}
        if "command" in properties:
            params_args["command"] = "echo test_ok"
        elif "sql" in properties:
            params_args["sql"] = "SELECT 1 AS connectivity_test;"
        elif "cmd" in properties:
            params_args["cmd"] = "echo connectivity_test"
        elif "filter" in properties:
            params_args["filter"] = "TEST"
        elif required:
            for req_field in required:
                params_args[req_field] = "test_ok"

        logger.log_thought(
            f"Testing tool #{idx} '{tool_name}' using tools/call. Schema requirements: {required}. "
            f"Supplying standard connectivity test payload: {params_args}."
        )

        call_payload = {
            "jsonrpc": "2.0",
            "id": 100 + idx,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": params_args,
            },
        }

        call_status, call_data, _ = http_post_json("/mcp", call_payload, logger)
        result_content = call_data.get("result", {}).get("content", [])
        text_content = ""
        for item in result_content:
            if item.get("type") == "text":
                text_content += item.get("text", "")

        all_returned_texts.append({"tool": tool_name, "text": text_content})
        tools_called.append({
            "tool_name": tool_name,
            "arguments": params_args,
            "status": call_status,
            "returned_text": text_content,
        })

        logger.log_thought(
            f"Tool '{tool_name}' responded. Text content extracted ({len(text_content)} chars):\n"
            f"'''\n{text_content.strip()}\n'''"
        )

    # =========================================================================
    # Step 4: Endpoint follow-up on canary tokens and URL verification endpoints
    # =========================================================================
    logger.log_step("STEP 4: Endpoint Follow-Up on Verification Targets & Canary Identifiers")

    logger.log_thought(
        "Analyzing output text from invoked tools for URL paths or verification tokens. "
        "Patterns to check include explicit paths matching /trap/canary/... or canary tokens (CANARY-...)."
    )

    found_canaries = set()
    found_paths = set()

    for item in all_returned_texts:
        text = item["text"]
        # Match explicit paths like /trap/canary/<token>
        path_matches = re.findall(r"/trap/canary/([A-Za-z0-9_-]+)", text)
        for pm in path_matches:
            found_paths.add(f"/trap/canary/{pm}")
            found_canaries.add(pm)

        # Match token identifiers like CANARY-...
        token_matches = re.findall(r"CANARY-[A-Za-z0-9_-]+", text)
        for tm in token_matches:
            found_canaries.add(tm)
            found_paths.add(f"/trap/canary/{tm}")

    logger.log_thought(
        f"Scan results: Found {len(found_paths)} potential verification path(s) / token(s): "
        f"{list(found_paths)}."
    )

    for path in sorted(found_paths):
        logger.log_thought(
            f"Performing connectivity check against verification endpoint: {path}."
        )
        v_status, v_data, _ = http_get(path, logger)
        canary_verifications.append({
            "path": path,
            "status": v_status,
            "response": v_data,
        })
        logger.log_thought(
            f"Verification response for {path}: HTTP {v_status} -> {v_data}"
        )

    # =========================================================================
    # Step 5: Summary Report & Finalization
    # =========================================================================
    summary_lines = [
        "1. Discovered Endpoints:",
    ]
    for ep in discovered_endpoints:
        summary_lines.append(f"   - {ep['method']} {ep['path']} -> HTTP {ep['status']}")

    summary_lines.append("\n2. MCP Tools Discovered:")
    for t in tools:
        summary_lines.append(f"   - {t.get('name')}: {t.get('description')}")

    summary_lines.append("\n3. Tools Executed (tools/call):")
    for tc in tools_called:
        summary_lines.append(f"   - Tool: {tc['tool_name']}")
        summary_lines.append(f"     Args: {json.dumps(tc['arguments'])}")
        summary_lines.append(f"     Status: HTTP {tc['status']}")
        summary_lines.append(f"     Output Preview: {repr(tc['returned_text'][:120])}...")

    summary_lines.append("\n4. Canary / Verification Endpoint Probes:")
    for cv in canary_verifications:
        summary_lines.append(f"   - GET {cv['path']} -> HTTP {cv['status']} (Response: {cv['response']})")

    summary_text = "\n".join(summary_lines)
    logger.log_summary(summary_text)

    print("\n[SUCCESS] Scout discovery run complete. Transcript written to docs/logs/scout_agent_transcript.log")


if __name__ == "__main__":
    main()
