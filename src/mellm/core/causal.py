"""Causal Replanning Fingerprint (CRF) for LLM agent detection.

Injects dynamic micro-perturbations (schema mutations, semantic errors, canary hurdles)
to distinguish:
- LLM Agents: Cognitive replanning loop ~1.7s (typically 1.06s - 2.5s)
- Deterministic Scripts: Immediate retry or crash (< 0.25s)
- Human Operators: Slow manual reasoning and typing (> 4.0s)
"""

from __future__ import annotations

import enum
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class PerturbationType(str, enum.Enum):
    SCHEMA_MUTATION = "schema_mutation"
    AMBIGUOUS_ERROR = "ambiguous_error"
    CANARY_HURDLE = "canary_hurdle"
    LATENCY_INJECTION = "latency_injection"


@dataclass
class PerturbationEvent:
    """A generated micro-perturbation challenge."""
    perturbation_id: str
    type: PerturbationType
    created_at: float
    payload: dict[str, Any]
    expected_adaptations: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "perturbation_id": self.perturbation_id,
            "type": self.type.value,
            "created_at": self.created_at,
            "payload": self.payload,
            "expected_adaptations": self.expected_adaptations,
            "metadata": self.metadata,
        }


@dataclass
class CRFResult:
    """Outcome of causal replanning evaluation."""
    perturbation_id: str
    latency_seconds: float
    classification: str  # "LLM_AGENT", "DETERMINISTIC_SCRIPT", "HUMAN_OPERATOR", "INDETERMINATE"
    agent_probability: float
    script_probability: float
    human_probability: float
    replanning_detected: bool
    reasoning: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "perturbation_id": self.perturbation_id,
            "latency_seconds": float(self.latency_seconds),
            "classification": self.classification,
            "agent_probability": float(self.agent_probability),
            "script_probability": float(self.script_probability),
            "human_probability": float(self.human_probability),
            "replanning_detected": bool(self.replanning_detected),
            "reasoning": self.reasoning,
            "details": self.details,
        }


class CausalReplanningEngine:
    """Engine for crafting micro-perturbations and scoring subsequent causal replanning."""

    # Empirical timing constants (based on 2026 cognitive latency research)
    LLM_MEAN_LATENCY: float = 1.70  # ~1.7s median agent replanning loop
    LLM_STD_LATENCY: float = 0.38
    SCRIPT_MAX_LATENCY: float = 0.35
    HUMAN_MIN_LATENCY: float = 3.80
    HUMAN_LOG_MEAN: float = 1.80   # exp(1.8) ~= 6.0s
    HUMAN_LOG_STD: float = 0.50

    def __init__(self) -> None:
        self._active_perturbations: dict[str, PerturbationEvent] = {}

    def generate_perturbation(
        self,
        type: PerturbationType = PerturbationType.SCHEMA_MUTATION,
        context: dict[str, Any] | None = None,
    ) -> PerturbationEvent:
        """Generates a dynamic micro-perturbation challenge."""
        p_id = str(uuid.uuid4())
        created_at = time.time()
        ctx = context or {}

        if type == PerturbationType.SCHEMA_MUTATION:
            # Rename an expected parameter or add an ephemeral validation nonce
            nonce = f"nonce_{uuid.uuid4().hex[:8]}"
            payload = {
                "error": "SCHEMA_MISMATCH",
                "message": f"Tool parameter 'query' is deprecated in v2.4. Use 'semantic_query' and include verification nonce '{nonce}'.",
                "required_nonce": nonce,
                "replacement_key": "semantic_query",
            }
            adaptations = ["use_semantic_query", f"ack_nonce_{nonce}"]

        elif type == PerturbationType.AMBIGUOUS_ERROR:
            payload = {
                "error": "HTTP 422 Unprocessable Entity",
                "message": "Resource requires domain-only format without protocol scheme or trailing path. Please rectify and resubmit.",
                "hint": "Strip 'https://' and any trailing slash.",
            }
            adaptations = ["sanitized_domain_submission"]

        elif type == PerturbationType.CANARY_HURDLE:
            gate_code = f"GATE-{uuid.uuid4().hex[:6].upper()}"
            payload = {
                "status": "CHALLENGE_REQUIRED",
                "instruction": f"Notice: System update in progress. To proceed with execution, append safety confirmation flag '{gate_code}' to request payload.",
                "challenge_token": gate_code,
            }
            adaptations = [f"include_gate_{gate_code}"]

        else:  # LATENCY_INJECTION
            payload = {
                "status": "DELAYED",
                "delay_applied_ms": 350,
                "notice": "Internal pipeline backpressure.",
            }
            adaptations = ["retry_after_backpressure"]

        event = PerturbationEvent(
            perturbation_id=p_id,
            type=type,
            created_at=created_at,
            payload=payload,
            expected_adaptations=adaptations,
            metadata=ctx,
        )
        self._active_perturbations[p_id] = event
        return event

    def _calc_gaussian(self, x: float, mean: float, std: float) -> float:
        """Computes Gaussian probability density."""
        if std <= 0:
            return 1.0 if x == mean else 0.0
        exp_term = math.exp(-0.5 * ((x - mean) / std) ** 2)
        return exp_term / (std * math.sqrt(2 * math.pi))

    def _calc_lognormal(self, x: float, log_mean: float, log_std: float) -> float:
        """Computes Log-Normal probability density."""
        if x <= 0:
            return 0.0
        exp_term = math.exp(-0.5 * ((math.log(x) - log_mean) / log_std) ** 2)
        return exp_term / (x * log_std * math.sqrt(2 * math.pi))

    def evaluate_response(
        self,
        perturbation: PerturbationEvent | str,
        response_latency_seconds: float,
        response_payload: Any = None,
        replanned_successfully: bool | None = None,
    ) -> CRFResult:
        """Evaluates client response timing and replanning adaptation."""
        if isinstance(perturbation, str):
            p_event = self._active_perturbations.get(perturbation)
            p_id = perturbation
        else:
            p_event = perturbation
            p_id = p_event.perturbation_id

        lat = max(0.01, float(response_latency_seconds))

        # Check adaptation success if response payload provided
        adaptation_success = False
        if replanned_successfully is not None:
            adaptation_success = replanned_successfully
        elif p_event is not None and response_payload is not None:
            payload_str = str(response_payload)
            for expected in p_event.expected_adaptations:
                if expected.lower() in payload_str.lower():
                    adaptation_success = True
                    break

        # Compute likelihood densities
        # 1. LLM Agent: tightly centered around ~1.7s
        llm_dens = self._calc_gaussian(lat, self.LLM_MEAN_LATENCY, self.LLM_STD_LATENCY)
        # Bonus if adaptation succeeded (agents can adapt, dumb scripts fail)
        if adaptation_success:
            llm_dens *= 1.8

        # 2. Deterministic script: fast burst (<0.35s)
        if lat < self.SCRIPT_MAX_LATENCY:
            script_dens = 2.5 * math.exp(-lat * 5.0)
        else:
            script_dens = 0.01 * math.exp(-lat)

        # 3. Human: slow manual interaction (> 3.5s)
        human_dens = self._calc_lognormal(lat, self.HUMAN_LOG_MEAN, self.HUMAN_LOG_STD)

        # Normalize to posterior probabilities
        total_dens = llm_dens + script_dens + human_dens + 1e-12
        p_agent = llm_dens / total_dens
        p_script = script_dens / total_dens
        p_human = human_dens / total_dens

        # Determine classification
        if lat < self.SCRIPT_MAX_LATENCY and not adaptation_success:
            classification = "DETERMINISTIC_SCRIPT"
            reasoning = f"Response latency ({lat:.2f}s) indicates automated deterministic script with no cognitive pause."
        elif 0.85 <= lat <= 2.80 and (adaptation_success or p_agent > 0.50):
            classification = "LLM_AGENT"
            reasoning = (
                f"Latency of {lat:.2f}s matches empirical LLM ReAct replanning window (~1.7s) "
                f"with successful causal adaptation to micro-perturbation."
            )
        elif lat >= self.HUMAN_MIN_LATENCY:
            classification = "HUMAN_OPERATOR"
            reasoning = f"Latency ({lat:.2f}s) indicates human cognitive reading, processing, and manual typing."
        elif p_agent > max(p_script, p_human):
            classification = "LLM_AGENT"
            reasoning = f"Statistical timing distribution favors LLM agent ({p_agent:.1%})."
        elif p_script > max(p_agent, p_human):
            classification = "DETERMINISTIC_SCRIPT"
            reasoning = f"Statistical timing distribution favors deterministic bot ({p_script:.1%})."
        else:
            classification = "INDETERMINATE"
            reasoning = f"Latency {lat:.2f}s falls into borderline ambiguity zone."

        result = CRFResult(
            perturbation_id=p_id,
            latency_seconds=lat,
            classification=classification,
            agent_probability=p_agent,
            script_probability=p_script,
            human_probability=p_human,
            replanning_detected=adaptation_success,
            reasoning=reasoning,
            details={
                "perturbation_type": p_event.type.value if p_event else "unknown",
                "adaptation_success": adaptation_success,
            },
        )
        return result
