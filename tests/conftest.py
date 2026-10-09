"""Pytest configuration and shared fixtures for MeLLM."""

import os
import pytest
from mellm.forensics.replay import IncidentReplayEngine
from mellm.honeynet.mcp_server import McpHoneypotServer
from mellm.honeynet.a2a_server import A2AServer
from mellm.honeynet.web_traps import SemanticCanaryInjector, VacuumHeuristicDetector
from mellm.api.server import get_app


@pytest.fixture
def replay_engine():
    data_file = "redacted.jsonl.gz"
    if not os.path.exists(data_file):
        pytest.skip("redacted.jsonl.gz not present in working directory")
    return IncidentReplayEngine(data_path=data_file)


@pytest.fixture
def mcp_server():
    return McpHoneypotServer()


@pytest.fixture
def a2a_server():
    return A2AServer()


@pytest.fixture
def web_traps():
    return SemanticCanaryInjector(), VacuumHeuristicDetector()


@pytest.fixture
def test_app():
    return get_app()
