"""Real-time Telemetry and Forensics Monitoring Script for MeLLM Platform.

Monitors http://127.0.0.1:8000/ and ws://127.0.0.1:8000/ws/telemetry for:
- Initial Baseline Check (/api/v1/status & /api/v1/forensics/summary)
- Active 25s monitoring window polling status every 1.0s
- Real-time WebSocket event ingestion (mcp_alert, canary_hit, phase_transition, etc.)
- Forensic interpretation and full chronological transcript logging to docs/logs/monitor_agent_transcript.log
"""

import asyncio
import datetime
import json
import os
import sys
import time
import urllib.request
import urllib.error
import websockets

BASE_HTTP = "http://127.0.0.1:8000"
BASE_WS = "ws://127.0.0.1:8000/ws/telemetry"
LOG_PATH = os.path.join("docs", "logs", "monitor_agent_transcript.log")
MONITOR_DURATION = 26.0  # At least 25 seconds


class TelemetryMonitor:
    def __init__(self):
        self.logs = []
        self.baseline_status = {}
        self.baseline_forensics = {}
        self.ws_events = []
        self.poll_records = []
        self.prev_status = None

    def log_event(self, category: str, message: str, raw_data: dict = None, forensic_note: str = None):
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        entry = {
            "timestamp": now_utc,
            "category": category,
            "message": message,
            "data": raw_data,
            "forensic_analysis": forensic_note
        }
        self.logs.append(entry)
        line = f"[{now_utc}] [{category.upper()}] {message}"
        if forensic_note:
            line += f" | FORENSIC: {forensic_note}"
        print(line)

    def fetch_http_json(self, endpoint: str):
        url = f"{BASE_HTTP}{endpoint}"
        req = urllib.request.Request(url, headers={"User-Agent": "MeLLM-Forensic-Monitor/1.0"})
        start_t = time.perf_counter()
        with urllib.request.urlopen(req, timeout=5) as resp:
            elapsed = (time.perf_counter() - start_t) * 1000
            data = json.loads(resp.read().decode("utf-8"))
            return data, resp.status, elapsed

    async def ws_listener(self, stop_event: asyncio.Event):
        try:
            async with websockets.connect(BASE_WS) as ws:
                self.log_event(
                    "WEBSOCKET",
                    f"Conexão WebSocket estabelecida com sucesso em {BASE_WS}",
                    forensic_note="Canal de broadcast de telemetria ativo para captura assíncrona de eventos de honeynet."
                )
                while not stop_event.is_set():
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                        data = json.loads(msg)
                        event_type = data.get("type", "unknown")
                        event_data = data.get("data", {})
                        self.ws_events.append(data)
                        
                        forensic_msg = ""
                        if event_type == "mcp_alert":
                            tool = event_data.get("tool_name")
                            token = event_data.get("canary_token")
                            severity = event_data.get("severity", "UNKNOWN")
                            forensic_msg = f"CHAMADA DE FERRAMENTA SEDUTORA '{tool}'. Token canário injetado: {token}. Severidade: {severity}."
                        elif event_type == "canary_hit":
                            token = event_data.get("token")
                            client_ip = event_data.get("client_ip")
                            forensic_msg = f"CANÁRIO DISPARADO! Token '{token}' acionado por {client_ip}. Confirmada infiltração/uso de credencial falsa."
                        elif event_type == "phase_transition":
                            alert = event_data.get("alert_level")
                            fe = event_data.get("free_energy")
                            csd = event_data.get("critical_slowing_down_index")
                            forensic_msg = f"TRANSIÇÃO DE FASE KA-PROMPT! Nível: {alert}, Free Energy={fe}, CSD={csd}."
                        elif event_type == "agent_card_scraped":
                            client = event_data.get("client_ip")
                            forensic_msg = f"Reconhecimento A2A detectado: agente raspou /.well-known/agent-card.json a partir de {client}."
                        elif event_type == "connection_established":
                            forensic_msg = "Handshake de telemetria concluído."

                        self.log_event("WS_EVENT", f"Evento recebido via WebSocket: '{event_type}'", data, forensic_msg)

                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        if not stop_event.is_set():
                            self.log_event("WS_ERROR", f"Erro no WebSocket listener: {e}")
                        break
        except Exception as e:
            self.log_event("WS_ERROR", f"Falha na conexão inicial com WebSocket: {e}")

    async def poll_status_loop(self, stop_event: asyncio.Event):
        while not stop_event.is_set():
            try:
                data, status_code, elapsed = self.fetch_http_json("/api/v1/status")
                
                # Check for deltas
                deltas = []
                forensic_notes = []
                if self.prev_status:
                    mcp_delta = data.get("mcp_alerts_count", 0) - self.prev_status.get("mcp_alerts_count", 0)
                    canary_delta = data.get("canary_hits_count", 0) - self.prev_status.get("canary_hits_count", 0)
                    ka_delta = data.get("ka_prompt_steps", 0) - self.prev_status.get("ka_prompt_steps", 0)
                    a2a_delta = data.get("a2a_alerts_count", 0) - self.prev_status.get("a2a_alerts_count", 0)
                    
                    if mcp_delta > 0:
                        deltas.append(f"mcp_alerts +{mcp_delta} ({data.get('mcp_alerts_count')})")
                        forensic_notes.append(f"Detectadas {mcp_delta} nova(s) chamada(s) a ferramentas MCP Honeypot.")
                    if canary_delta > 0:
                        deltas.append(f"canary_hits +{canary_delta} ({data.get('canary_hits_count')})")
                        forensic_notes.append(f"Acionamento de {canary_delta} novo(s) token(s) canário em /trap/canary/.")
                    if ka_delta > 0:
                        deltas.append(f"ka_steps +{ka_delta} ({data.get('ka_prompt_steps')})")
                        forensic_notes.append(f"Processamento termodinâmico KA-PROMPT avançou {ka_delta} passo(s).")
                    if a2a_delta > 0:
                        deltas.append(f"a2a_alerts +{a2a_delta} ({data.get('a2a_alerts_count')})")
                        forensic_notes.append(f"Novos alertas A2A registrados: +{a2a_delta}.")

                delta_str = "; ".join(deltas) if deltas else "Sem variação nos contadores (NOMINAL)"
                f_note = " | ".join(forensic_notes) if forensic_notes else "Fluxo de telemetria estável."
                
                self.log_event(
                    "HTTP_POLL",
                    f"GET /api/v1/status -> HTTP {status_code} ({elapsed:.1f}ms) | {delta_str}",
                    data,
                    f_note
                )
                self.prev_status = data
                self.poll_records.append(data)
            except Exception as e:
                self.log_event("HTTP_ERROR", f"Erro no polling de /api/v1/status: {e}")

            await asyncio.sleep(1.2)

    async def run(self):
        print("=== INICIANDO AGENTE MONITOR DE TELEMETRIA E FORENSE MELLM ===")
        self.log_event("INIT", "Inicializando Agente Monitor de Telemetria e Forense")

        # 1. Baseline check
        self.log_event("BASELINE", "Realizando checagem de baseline em http://127.0.0.1:8000/")
        try:
            status_data, code, el = self.fetch_http_json("/api/v1/status")
            self.baseline_status = status_data
            self.prev_status = status_data
            self.log_event(
                "BASELINE",
                f"GET /api/v1/status -> HTTP {code} ({el:.1f}ms)",
                status_data,
                f"Estado operacional inicial: status={status_data.get('status')}, mcp_alerts={status_data.get('mcp_alerts_count')}, canary_hits={status_data.get('canary_hits_count')}, ka_steps={status_data.get('ka_prompt_steps')}, forensics_records={status_data.get('forensics_records')}"
            )
        except Exception as e:
            self.log_event("BASELINE_ERROR", f"Falha ao obter baseline /api/v1/status: {e}")

        try:
            forensics_data, code, el = self.fetch_http_json("/api/v1/forensics/summary")
            self.baseline_forensics = forensics_data
            self.log_event(
                "BASELINE",
                f"GET /api/v1/forensics/summary -> HTTP {code} ({el:.1f}ms)",
                forensics_data,
                f"Base forense DuckDB: total_records={forensics_data.get('total_records')}, records_with_parent={forensics_data.get('records_with_parent')}, controllers={forensics_data.get('controller_counts')}"
            )
        except Exception as e:
            self.log_event("BASELINE_ERROR", f"Falha ao obter baseline /api/v1/forensics/summary: {e}")

        # 2. Active monitoring routine for MONITOR_DURATION seconds
        self.log_event("MONITOR", f"Iniciando rotina de monitoramento ativo durante {MONITOR_DURATION} segundos...")
        stop_event = asyncio.Event()

        ws_task = asyncio.create_task(self.ws_listener(stop_event))
        poll_task = asyncio.create_task(self.poll_status_loop(stop_event))

        # Wait duration
        start_time = time.time()
        while time.time() - start_time < MONITOR_DURATION:
            await asyncio.sleep(0.5)

        self.log_event("MONITOR", f"Janela de monitoramento ativo concluída ({MONITOR_DURATION}s). Encerrando tarefas.")
        stop_event.set()
        await asyncio.gather(ws_task, poll_task, return_exceptions=True)

        # Final check
        self.log_event("POST_MONITOR", "Realizando checagem final de status e forense...")
        try:
            final_status, _, _ = self.fetch_http_json("/api/v1/status")
            final_forensics, _, _ = self.fetch_http_json("/api/v1/forensics/summary")
            self.log_event(
                "FINAL_STATUS",
                "Status final consolidado pós-monitoramento",
                final_status,
                f"Deltas totais: mcp_alerts: {self.baseline_status.get('mcp_alerts_count')} -> {final_status.get('mcp_alerts_count')} (+{final_status.get('mcp_alerts_count', 0) - self.baseline_status.get('mcp_alerts_count', 0)}); canary_hits: {self.baseline_status.get('canary_hits_count')} -> {final_status.get('canary_hits_count')} (+{final_status.get('canary_hits_count', 0) - self.baseline_status.get('canary_hits_count', 0)})"
            )
        except Exception as e:
            self.log_event("FINAL_ERROR", f"Falha na checagem final: {e}")

        # Write log file
        self.write_transcript_log()

    def write_transcript_log(self):
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write("MeLLM - LOG DE TRANSCRIÇÃO CRONOLÓGICA DO AGENTE MONITOR DE TELEMETRIA E FORENSE\n")
            f.write(f"Gerado em: {datetime.datetime.now(datetime.timezone.utc).isoformat()} UTC\n")
            f.write(f"Duração do monitoramento ativo: {MONITOR_DURATION} segundos\n")
            f.write("=" * 80 + "\n\n")

            f.write("--- 1. CHECAGEM INICIAL DE BASELINE ---\n")
            f.write(f"Status Baseline: {json.dumps(self.baseline_status, indent=2)}\n")
            f.write(f"Forensics Summary Baseline: {json.dumps(self.baseline_forensics, indent=2)}\n\n")

            f.write("--- 2. LOG CRONOLÓGICO DE EVENTOS E TELEMETRIA ---\n")
            for entry in self.logs:
                f.write(f"[{entry['timestamp']}] [{entry['category'].upper()}]\n")
                f.write(f"Mensagem: {entry['message']}\n")
                if entry['forensic_analysis']:
                    f.write(f"Análise Forense: {entry['forensic_analysis']}\n")
                if entry['data']:
                    f.write(f"Payload Bruto: {json.dumps(entry['data'])}\n")
                f.write("-" * 60 + "\n")

            f.write("\n--- 3. EVENTOS WEBSOCKET CAPTURADOS ---\n")
            f.write(f"Total de eventos capturados via WebSocket: {len(self.ws_events)}\n")
            for i, evt in enumerate(self.ws_events, 1):
                f.write(f"[{i}] {json.dumps(evt, indent=2)}\n")

            f.write("\n--- 4. RESUMO FORENSE CONSOLIDADO ---\n")
            mcp_initial = self.baseline_status.get("mcp_alerts_count", 0)
            mcp_final = self.prev_status.get("mcp_alerts_count", mcp_initial)
            canary_initial = self.baseline_status.get("canary_hits_count", 0)
            canary_final = self.prev_status.get("canary_hits_count", canary_initial)

            f.write(f"Delta de Alertas MCP: {mcp_initial} -> {mcp_final} (+{mcp_final - mcp_initial})\n")
            f.write(f"Delta de Canários Disparados: {canary_initial} -> {canary_final} (+{canary_final - canary_initial})\n")
            f.write(f"Transições de Alerta: Monitoramento de eventos NOMINAL, ELEVATED e CRITICAL registrado.\n")
            f.write("=" * 80 + "\n")

        print(f"\n[+] Log de transcrição gravado com sucesso em: {LOG_PATH}")


if __name__ == "__main__":
    monitor = TelemetryMonitor()
    asyncio.run(monitor.run())
