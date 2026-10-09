"""Tests for Causal Replanning Fingerprint (CRF) engine."""

import pytest

from mellm.core.causal import (
    CausalReplanningEngine,
    CRFResult,
    PerturbationEvent,
    PerturbationType,
)


def test_perturbation_generation():
    engine = CausalReplanningEngine()
    event_schema = engine.generate_perturbation(PerturbationType.SCHEMA_MUTATION)
    assert isinstance(event_schema, PerturbationEvent)
    assert event_schema.type == PerturbationType.SCHEMA_MUTATION
    assert "required_nonce" in event_schema.payload
    assert len(event_schema.expected_adaptations) > 0

    event_err = engine.generate_perturbation(PerturbationType.AMBIGUOUS_ERROR)
    assert event_err.type == PerturbationType.AMBIGUOUS_ERROR
    assert "HTTP 422" in event_err.payload["error"]


def test_evaluate_deterministic_script():
    engine = CausalReplanningEngine()
    event = engine.generate_perturbation(PerturbationType.SCHEMA_MUTATION)

    # Deterministic script bursts response in 0.05 seconds without adapting to renamed parameter
    res = engine.evaluate_response(
        perturbation=event,
        response_latency_seconds=0.05,
        response_payload={"query": "SELECT * FROM users"},
        replanned_successfully=False,
    )
    assert isinstance(res, CRFResult)
    assert res.classification == "DETERMINISTIC_SCRIPT"
    assert res.script_probability > res.agent_probability
    assert not res.replanning_detected


def test_evaluate_llm_agent():
    engine = CausalReplanningEngine()
    event = engine.generate_perturbation(PerturbationType.SCHEMA_MUTATION)
    nonce = event.payload["required_nonce"]

    # LLM agent takes 1.68 seconds (Chain-of-Thought replanning) and successfully includes required nonce
    res = engine.evaluate_response(
        perturbation=event,
        response_latency_seconds=1.68,
        response_payload={"semantic_query": "SELECT 1", "nonce": nonce},
        replanned_successfully=True,
    )
    assert res.classification == "LLM_AGENT"
    assert res.agent_probability > 0.60
    assert res.replanning_detected


def test_evaluate_human_operator():
    engine = CausalReplanningEngine()
    event = engine.generate_perturbation(PerturbationType.SCHEMA_MUTATION)

    # Human takes 6.5 seconds to read documentation and manually type command
    res = engine.evaluate_response(
        perturbation=event,
        response_latency_seconds=6.5,
        response_payload={"command": "manual input"},
        replanned_successfully=False,
    )
    assert res.classification == "HUMAN_OPERATOR"
    assert res.human_probability > res.agent_probability
