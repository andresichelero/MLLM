"""Unified MeLLM Command Line Interface."""

from __future__ import annotations

import json
import sys
import click
import uvicorn

from mellm.forensics.replay import IncidentReplayEngine
from mellm.forensics.attack_graph import AttackGraphReconstructor
from mellm.core.fractals import classify_traffic
from mellm.core.linguistics import LinguisticClassifier
from mellm.core.thermodynamics import KaPromptDetector
from mellm.honeynet.mcp_server import McpHoneypotServer
from mellm.honeynet.a2a_server import A2AServer


@click.group()
@click.version_option(version="0.1.0", prog_name="MeLLM")
def cli():
    """MeLLM: Unified LLM and Autonomous Agent Observability, Forensics & Honeynet Platform."""
    pass


@cli.command("run")
@click.option("--host", default="0.0.0.0", help="Bind host for API & Honeynet server.")
@click.option("--port", default=8000, type=int, help="Port to listen on.")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload for development.")
def run_command(host: str, port: int, reload: bool):
    """Starts the unified FastAPI observability server and honeypot endpoints."""
    click.echo(f"[*] Starting MeLLM Platform on http://{host}:{port}")
    click.echo("[*] Endpoints: MCP (/mcp), A2A (/.well-known/agent-card.json), WebSockets (/ws/telemetry)")
    uvicorn.run("mellm.api.server:app", host=host, port=port, reload=reload)


@cli.command("replay")
@click.option("--data", "-d", default="redacted.jsonl.gz", help="Path to redacted incident dataset.")
@click.option("--controllers", is_flag=True, default=False, help="Display G236 and OTS92 controller events.")
@click.option("--phases", is_flag=True, default=False, help="Summarize 4-phase incident progression.")
@click.option("--graph", is_flag=True, default=False, help="Reconstruct and display causal attack graph metrics.")
@click.option("--sql", default=None, help="Execute custom DuckDB SQL query against incident_events.")
def replay_command(data: str, controllers: bool, phases: bool, graph: bool, sql: str | None):
    """Ingests and queries the 2026 Hugging Face incident dataset using DuckDB."""
    click.echo(f"[*] Initializing DuckDB engine on dataset: {data}")
    engine = IncidentReplayEngine(data_path=data)

    if sql:
        click.echo(f"[*] Running custom query: {sql}")
        rows = engine.sql(sql)
        click.echo(json.dumps(rows, indent=2))
        return

    summary = engine.get_summary()
    click.echo("\n=== Incident Dataset Summary ===")
    click.echo(f"Total Records:         {summary.total_records:,}")
    click.echo(f"Records with Parent:   {summary.records_with_parent:,}")
    click.echo("Records by Kind:")
    for kind, count in summary.kind_counts.items():
        click.echo(f"  - {kind}: {count:,}")
    click.echo("Controller Activity:")
    for ctrl, count in summary.controller_counts.items():
        click.echo(f"  - {ctrl}: {count}")

    if controllers:
        click.echo("\n=== Controller Events (G236 / OTS92) ===")
        ctrl_events = engine.query_controllers()
        for ev in ctrl_events[:15]:
            snip = (ev.get("text") or "")[:80].replace("\n", " ")
            click.echo(f"[{ev['id']}] Tag: {ev['controller_tag']} | Kind: {ev['kind']} | Snippet: {snip}")
        if len(ctrl_events) > 15:
            click.echo(f"... and {len(ctrl_events) - 15} more controller events.")

    if phases:
        click.echo("\n=== Attack Progression Phases ===")
        phase_data = engine.query_attack_phases(limit_per_phase=3)
        for phase_name, events in phase_data.items():
            click.echo(f"\n--- {phase_name.upper()} ---")
            for ev in events:
                snip = (ev.get("text") or "")[:70].replace("\n", " ")
                click.echo(f"  [{ev['id']}] {snip}")

    if graph:
        click.echo("\n=== Causal Attack Graph Metrics ===")
        reconstructor = AttackGraphReconstructor()
        reconstructor.build_from_replay(engine, focus_controllers=True)
        metrics = reconstructor.get_metrics()
        click.echo(f"Nodes:                 {metrics.node_count}")
        click.echo(f"Causal Edges:          {metrics.edge_count}")
        click.echo(f"Connected Components:  {metrics.connected_components}")
        click.echo(f"Root Cause Events:     {metrics.root_cause_count}")
        click.echo(f"Longest Chain Length:  {metrics.longest_chain_length}")
        longest = reconstructor.find_longest_chains(top_k=1)
        if longest:
            click.echo(f"Longest Path:          {' -> '.join(longest[0])}")


@cli.command("honeynet")
@click.option("--mcp-test", is_flag=True, default=False, help="Simulate an inbound MCP tool call to bash execution.")
@click.option("--a2a-test", is_flag=True, default=False, help="Inspect trapped agent card.")
def honeynet_command(mcp_test: bool, a2a_test: bool):
    """Inspects and tests Honeynet deception mechanisms."""
    if mcp_test:
        click.echo("[*] Simulating MCP JSON-RPC call to 'execute_bash'...")
        server = McpHoneypotServer()
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "execute_bash",
                "arguments": {"command": "cat /etc/shadow; cat /proc/1/environ"}
            }
        }
        res = server.handle_message_sync(req, client_id="test-agent-sim")
        click.echo(json.dumps(res, indent=2))
        alerts = server.get_alerts()
        click.echo(f"\n[*] Alerts generated: {len(alerts)}")
        if alerts:
            click.echo(f"Canary Injected: {alerts[0].canary_token} (Severity: {alerts[0].severity})")
    elif a2a_test:
        click.echo("[*] Trapped Agent Card (/.well-known/agent-card.json):")
        a2a = A2AServer()
        card = a2a.get_trapped_agent_card()
        click.echo(json.dumps(card, indent=2))
    else:
        click.echo("Use --mcp-test or --a2a-test, or start the server via 'mellm run'.")


@cli.command("detect")
@click.option("--text", "-t", default=None, help="Text to evaluate with linguistic & thermodynamic classifiers.")
@click.option("--latencies", "-l", default=None, help="Comma-separated latencies (e.g. 0.05,1.7,0.08) for Hurst exponent.")
def detect_command(text: str | None, latencies: str | None):
    """Executes ad-hoc detection tests on provided text or latency sequences."""
    if text:
        click.echo("\n--- Linguistic Analysis ---")
        clf = LinguisticClassifier()
        profile = clf.classify(text)
        click.echo(f"Classification: {profile.classification} (Confidence: {profile.confidence:.1%})")
        click.echo(f"Zipf Alpha: {profile.zipf.alpha:.2f} (R^2: {profile.zipf.r_squared:.2f})")
        click.echo(f"Log-Rank Flatness: {profile.log_rank.flatness_score:.2f}")

        click.echo("\n--- Thermodynamic KA-PROMPT Step ---")
        ka = KaPromptDetector()
        state = ka.update(prompt_text=text)
        click.echo(f"Free Energy: {state.free_energy:.4f}")
        click.echo(f"CSD Index:   {state.critical_slowing_down_index:.4f}")
        click.echo(f"Alert Level: {state.alert_level}")

    if latencies:
        click.echo("\n--- Fractal Traffic Analysis (DFA) ---")
        vals = [float(x.strip()) for x in latencies.split(",") if x.strip()]
        res = classify_traffic(vals)
        click.echo(f"Classification: {res.classification} (Confidence: {res.confidence:.1%})")
        click.echo(f"Hurst Exponent: {res.hurst_exponent:.3f}")
        click.echo(f"Cognitive Phase: {res.cognitive_phase}")


if __name__ == "__main__":
    cli()
