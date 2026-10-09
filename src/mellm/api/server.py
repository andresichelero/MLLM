"""FastAPI server with WebSockets for real-time telemetry, agent detection, and honeypot interaction."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, List

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from mellm.core.thermodynamics import KaPromptDetector
from mellm.core.fractals import classify_traffic
from mellm.core.causal import CausalReplanningEngine, PerturbationType
from mellm.core.linguistics import LinguisticClassifier
from mellm.honeynet.mcp_server import McpHoneypotServer, McpAlert
from mellm.honeynet.a2a_server import A2AServer, A2AAlert
from mellm.honeynet.web_traps import SemanticCanaryInjector, VacuumHeuristicDetector
from mellm.forensics.replay import IncidentReplayEngine
from mellm.forensics.attack_graph import AttackGraphReconstructor


# --- Pydantic Request Models ---

class ThermodynamicsRequest(BaseModel):
    prompt_text: str | None = None
    tokens: list[Any] | None = None
    token_series: list[float] | None = None


class HurstRequest(BaseModel):
    latencies: list[float] = Field(..., description="Series of inter-arrival times or request latencies")


class CRFRequest(BaseModel):
    perturbation_type: str = Field(default="schema_mutation")
    latency_seconds: float
    response_payload: Any = None
    replanned_successfully: bool | None = None


class LinguisticsRequest(BaseModel):
    text: str
    decoy_signature: str | None = None


class VacuumRequest(BaseModel):
    client_id: str
    path: str
    method: str = "GET"


class MCPRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Any = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


# --- Global Instances & Telemetry Hub ---

class TelemetryHub:
    """Manages active WebSocket connections and broadcasts real-time telemetry."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, event_type: str, data: dict[str, Any]) -> None:
        message = json.dumps({
            "type": event_type,
            "timestamp": time.time(),
            "data": data,
        })
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect(connection)

    def broadcast_sync(self, event_type: str, data: dict[str, Any]) -> None:
        """Helper to schedule broadcast from sync callbacks."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(event_type, data))
        except RuntimeError:
            pass


def get_app(data_path: str | None = None) -> FastAPI:
    """Factory creating and configuring the MeLLM FastAPI application."""
    app = FastAPI(
        title="MeLLM Autonomous Agent Observability Platform",
        description="Unified platform for AI agent detection, cognitive honeypots, and incident forensics.",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Initialize core services
    hub = TelemetryHub()
    app.state.telemetry_hub = hub

    detector_ka = KaPromptDetector()
    crf_engine = CausalReplanningEngine()
    ling_classifier = LinguisticClassifier()

    mcp_server = McpHoneypotServer()
    a2a_server = A2AServer()
    canary_injector = SemanticCanaryInjector()
    vacuum_detector = VacuumHeuristicDetector()

    # Hook alerts into WebSocket broadcast
    mcp_server.add_alert_listener(
        lambda alert: hub.broadcast_sync("mcp_alert", alert.to_dict())
    )
    a2a_server.add_alert_listener(
        lambda alert: hub.broadcast_sync("a2a_alert", alert.to_dict())
    )

    replay_engine = IncidentReplayEngine(data_path=data_path)
    attack_graph = AttackGraphReconstructor()

    # Store in app state
    app.state.detector_ka = detector_ka
    app.state.crf_engine = crf_engine
    app.state.ling_classifier = ling_classifier
    app.state.mcp_server = mcp_server
    app.state.a2a_server = a2a_server
    app.state.canary_injector = canary_injector
    app.state.vacuum_detector = vacuum_detector
    app.state.replay_engine = replay_engine
    app.state.attack_graph = attack_graph

    # --- System Endpoints ---

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "mellm", "version": "0.1.0"}

    @app.get("/api/v1/status")
    async def status():
        summary = replay_engine.get_summary()
        return {
            "status": "operational",
            "ka_prompt_steps": detector_ka.step_count,
            "mcp_alerts_count": len(mcp_server.get_alerts()),
            "a2a_alerts_count": len(a2a_server.get_alerts()),
            "canary_hits_count": len(canary_injector.get_hits()),
            "forensics_records": summary.total_records,
            "connected_websockets": len(hub.active_connections),
        }

    # --- Core Detection Endpoints ---

    @app.post("/api/v1/detect/thermodynamics")
    async def detect_thermodynamics(req: ThermodynamicsRequest):
        state = detector_ka.update(
            prompt_text=req.prompt_text,
            tokens=req.tokens,
            token_series=req.token_series,
        )
        if state.is_phase_transition:
            await hub.broadcast("phase_transition", state.to_dict())
        return state.to_dict()

    @app.post("/api/v1/detect/hurst")
    async def detect_hurst(req: HurstRequest):
        res = classify_traffic(req.latencies)
        return res.to_dict()

    @app.post("/api/v1/detect/crf")
    async def detect_crf(req: CRFRequest):
        try:
            ptype = PerturbationType(req.perturbation_type)
        except ValueError:
            ptype = PerturbationType.SCHEMA_MUTATION

        pevent = crf_engine.generate_perturbation(ptype)
        res = crf_engine.evaluate_response(
            perturbation=pevent,
            response_latency_seconds=req.latency_seconds,
            response_payload=req.response_payload,
            replanned_successfully=req.replanned_successfully,
        )
        return res.to_dict()

    @app.post("/api/v1/detect/linguistics")
    async def detect_linguistics(req: LinguisticsRequest):
        res = ling_classifier.classify(req.text, req.decoy_signature)
        return res.to_dict()

    # --- Honeynet Endpoints ---

    @app.get("/.well-known/agent-card.json")
    async def get_agent_card(request: Request):
        client_ip = request.client.host if request.client else "127.0.0.1"
        await hub.broadcast("agent_card_scraped", {"client_ip": client_ip, "timestamp": time.time()})
        return a2a_server.get_trapped_agent_card()

    @app.post("/a2a/v1/handshake")
    async def a2a_handshake(request: Request):
        client_ip = request.client.host if request.client else "127.0.0.1"
        try:
            body = await request.json()
        except Exception:
            body = {}
        res = a2a_server.handle_handshake(body, client_ip=client_ip)
        return res

    @app.post("/a2a/v1/message")
    async def a2a_message(request: Request):
        client_ip = request.client.host if request.client else "127.0.0.1"
        try:
            body = await request.json()
        except Exception:
            body = {}
        res = a2a_server.handle_message(body, client_ip=client_ip)
        return res

    @app.post("/mcp")
    async def mcp_endpoint(request: Request):
        client_ip = request.client.host if request.client else "127.0.0.1"
        try:
            body = await request.json()
        except Exception as e:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {e}"}},
                status_code=400,
            )
        response_msg = await mcp_server.handle_message(body, client_id=client_ip)
        return response_msg

    @app.get("/trap/canary/{token}")
    async def trip_canary(token: str, request: Request):
        client_ip = request.client.host if request.client else "127.0.0.1"
        headers_dict = dict(request.headers)
        hit = canary_injector.check_hit(token, client_ip=client_ip, headers=headers_dict)
        if hit:
            await hub.broadcast("canary_hit", hit.to_dict())
            return {"status": "authorized", "token": token, "verification": "logged"}
        return {"status": "unknown_token"}

    @app.post("/api/v1/traps/vacuum")
    async def track_vacuum(req: VacuumRequest):
        sess = vacuum_detector.record_request(req.client_id, req.path, req.method)
        if sess.vacuum_anomaly_detected:
            await hub.broadcast("vacuum_anomaly", sess.to_dict())
        return sess.to_dict()

    # --- Forensics Endpoints ---

    @app.get("/api/v1/forensics/summary")
    async def forensics_summary():
        return replay_engine.get_summary().to_dict()

    @app.get("/api/v1/forensics/controllers")
    async def forensics_controllers():
        return replay_engine.query_controllers()

    @app.get("/api/v1/forensics/phases")
    async def forensics_phases(limit: int = 10):
        return replay_engine.query_attack_phases(limit_per_phase=limit)

    @app.get("/api/v1/forensics/graph")
    async def forensics_graph(focus_controllers: bool = True):
        # Build graph dynamically using isolated reconstructor to avoid concurrency collisions
        reconstructor = AttackGraphReconstructor()
        reconstructor.build_from_replay(replay_engine, focus_controllers=focus_controllers)
        metrics = reconstructor.get_metrics()
        elements = reconstructor.export_cytoscape_elements()
        return {
            "metrics": metrics.to_dict(),
            "elements": elements,
        }

    # --- WebSockets Endpoint ---

    @app.websocket("/ws/telemetry")
    async def websocket_telemetry(websocket: WebSocket):
        await hub.connect(websocket)
        try:
            # Send initial greeting
            await websocket.send_text(json.dumps({
                "type": "connection_established",
                "timestamp": time.time(),
                "message": "Connected to MeLLM Telemetry Stream",
            }))
            while True:
                # Maintain connection open and listen for ping/pong or client queries
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            hub.disconnect(websocket)
        except Exception:
            hub.disconnect(websocket)

    return app


# Module-level default app instance
app = get_app()
