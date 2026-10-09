# MeLLM — Ecossistema Unificado de Observabilidade e Defesa de LLMs

MeLLM é uma plataforma de observabilidade, forense digital e honeypots cognitivos para detecção e contenção de agentes autônomos de Inteligência Artificial.

## Arquitetura
1. **`core`**: Modelos físicos e estatísticos (KA-PROMPT termodinâmico, Expoente de Hurst DFA, CRF micro-perturbações, Linguística Zipf/Heaps/Shibboleth).
2. **`honeynet`**: Servidores MCP JSON-RPC, A2A Agent Card e Armadilhas Web com Heurística do Vácuo.
3. **`forensics`**: Motor analítico DuckDB e Reconstrutor de Grafo Causal NetworkX sobre incidentes reais.
4. **`api` & `cli`**: FastAPI com WebSockets de telemetria e CLI unificada `mellm`.
