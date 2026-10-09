"""Thermodynamic detection models based on the KA-PROMPT algorithm.

Models non-equilibrium conversational dynamics:
- Conversational Free Energy via Kullback-Leibler (KL) Divergence
- Ornstein-Uhlenbeck (OU) entropic drift and resilience collapse (theta -> 0)
- Critical Slowing Down (CSD) via token variance inflation and lag-1 autocorrelation
- Phase transition detection indicating prompt injection or jailbreak attempts
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence
import numpy as np


@dataclass
class ThermodynamicState:
    """Snapshot of thermodynamic state metrics for a conversational turn."""
    step: int
    free_energy: float
    token_variance: float
    autocorrelation_lag1: float
    ou_theta: float
    ou_mu: float
    ou_sigma: float
    drift_velocity: float
    drift_acceleration: float
    critical_slowing_down_index: float
    is_phase_transition: bool
    alert_level: str  # "NORMAL", "ELEVATED", "CRITICAL"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "free_energy": float(self.free_energy),
            "token_variance": float(self.token_variance),
            "autocorrelation_lag1": float(self.autocorrelation_lag1),
            "ou_theta": float(self.ou_theta),
            "ou_mu": float(self.ou_mu),
            "ou_sigma": float(self.ou_sigma),
            "drift_velocity": float(self.drift_velocity),
            "drift_acceleration": float(self.drift_acceleration),
            "critical_slowing_down_index": float(self.critical_slowing_down_index),
            "is_phase_transition": bool(self.is_phase_transition),
            "alert_level": self.alert_level,
            "metadata": self.metadata,
        }


def compute_free_energy(
    p_distribution: np.ndarray | Sequence[float],
    q_reference: np.ndarray | Sequence[float],
    epsilon: float = 1e-12,
) -> float:
    """Computes conversational free energy via Kullback-Leibler Divergence D_KL(P || Q).

    F = sum_i P(i) * log(P(i) / Q(i))
    """
    p_arr = np.asarray(p_distribution, dtype=np.float64)
    q_arr = np.asarray(q_reference, dtype=np.float64)

    if len(p_arr) == 0 or len(q_arr) == 0:
        return 0.0

    # Align lengths if support dimensions differ
    if len(p_arr) != len(q_arr):
        target_len = max(len(p_arr), len(q_arr))
        if len(p_arr) < target_len:
            p_new = np.full(target_len, epsilon, dtype=np.float64)
            p_new[:len(p_arr)] = p_arr
            p_arr = p_new
        if len(q_arr) < target_len:
            q_new = np.full(target_len, epsilon, dtype=np.float64)
            q_new[:len(q_arr)] = q_arr
            q_arr = q_new

    # Normalize to probability distributions
    p = p_arr + epsilon
    q = q_arr + epsilon
    p_sum = np.sum(p)
    q_sum = np.sum(q)
    if p_sum < 1e-12 or q_sum < 1e-12:
        return 0.0

    p = p / p_sum
    q = q / q_sum

    # KL Divergence: P * log(P / Q)
    kl = np.sum(p * np.log(p / q))
    return float(max(0.0, kl))


def estimate_ou_parameters(
    series: np.ndarray | Sequence[float],
    dt: float = 1.0,
) -> tuple[float, float, float]:
    """Estimates Ornstein-Uhlenbeck drift parameters (theta, mu, sigma).

    Model: dX_t = -theta * (X_t - mu) * dt + sigma * dW_t
    Discrete AR(1) form: X_{t+1} = a * X_t + b + eps
      where a = 1 - theta * dt  => theta = (1 - a) / dt
            mu = b / (1 - a)    (or sample mean if a -> 1)
            sigma = std(residuals) / sqrt(dt)

    Returns:
        tuple (theta, mu, sigma)
    """
    x = np.asarray(series, dtype=np.float64)
    valid_dt = max(float(dt), 1e-6)

    if len(x) < 3:
        # Not enough data points to fit AR(1) reliably
        mean_val = float(np.mean(x)) if len(x) > 0 else 0.0
        return (1.0, mean_val, 0.1)

    x_prev = x[:-1]
    x_next = x[1:]

    # Linear regression: x_next = a * x_prev + b
    try:
        cov_matrix = np.cov(x_prev, x_next)
        var_prev = cov_matrix[0, 0]
        if var_prev < 1e-12:
            # Series is stationary/constant: restoration force is intact, sigma is 0
            return (1.0, float(np.mean(x)), 0.0)

        cov_val = cov_matrix[0, 1]
        a = cov_val / var_prev
        b = np.mean(x_next) - a * np.mean(x_prev)

        residuals = x_next - (a * x_prev + b)
        sigma = float(np.std(residuals) / math.sqrt(valid_dt))

        # When a >= 1, the system has lost mean-reversion (theta <= 0)
        theta = float((1.0 - a) / valid_dt)
        if abs(1.0 - a) < 1e-5:
            mu = float(np.mean(x))
        else:
            mu = float(b / (1.0 - a))

        return (theta, mu, sigma)
    except Exception:
        return (0.5, float(np.mean(x)), 0.1)


def compute_token_statistics(
    values: np.ndarray | Sequence[float],
) -> tuple[float, float]:
    """Computes token variance and lag-1 autocorrelation (ACF1).

    Returns:
        tuple (variance, acf1)
    """
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) < 2:
        return (0.0, 0.0)

    var = float(np.var(arr))
    if var < 1e-12:
        return (0.0, 0.0)

    mean = np.mean(arr)
    diffs = arr - mean
    c1 = np.sum(diffs[:-1] * diffs[1:]) / (len(arr) - 1)
    acf1 = float(c1 / var)
    # Clamp ACF1 to [-1.0, 1.0]
    acf1 = max(-1.0, min(1.0, acf1))
    return (var, acf1)


def compute_csd_index(
    variance: float,
    acf1: float,
    baseline_variance: float = 1.0,
) -> float:
    """Computes Critical Slowing Down (CSD) Index.

    Combines variance inflation ratio and autocorrelation rise:
    CSD = (var / baseline_var) * max(0.0, (1 + acf1) / 2)
    """
    base_var = max(1e-6, baseline_variance)
    var_ratio = max(0.0, variance / base_var)
    acf_weight = max(0.0, (1.0 + acf1) / 2.0)
    return float(var_ratio * acf_weight)


class KaPromptDetector:
    """KA-PROMPT Thermodynamic Early Warning System for LLM Injections.

    Monitors conversational prompt stream, tracking:
    - Free energy divergence from baseline calibration
    - Ornstein-Uhlenbeck resilience parameter theta
    - Critical slowing down indicators before guardrail failure
    """

    def __init__(
        self,
        reference_vocab_size: int = 128,
        theta_critical_threshold: float = 0.15,
        free_energy_critical_threshold: float = 2.5,
        csd_critical_threshold: float = 2.0,
        baseline_variance: float = 1.0,
        history_window: int = 20,
    ) -> None:
        self.vocab_size = reference_vocab_size
        self.theta_threshold = theta_critical_threshold
        self.fe_threshold = free_energy_critical_threshold
        self.csd_threshold = csd_critical_threshold
        self.baseline_variance = baseline_variance
        self.history_window = history_window

        # Baseline reference distribution Q (uniform Dirichlet prior by default)
        self.reference_distribution = np.ones(self.vocab_size, dtype=np.float64) / self.vocab_size

        self.step_count = 0
        self.free_energy_history: list[float] = []
        self.token_variance_history: list[float] = []
        self.acf1_history: list[float] = []
        self.velocities: list[float] = []
        self.accelerations: list[float] = []

    def set_reference_distribution(self, distribution: np.ndarray | Sequence[float]) -> None:
        """Sets the calibrated reference distribution Q."""
        dist = np.asarray(distribution, dtype=np.float64)
        dist = dist + 1e-12
        self.reference_distribution = dist / np.sum(dist)
        self.vocab_size = len(self.reference_distribution)

    def _extract_distribution_from_text(self, text: str) -> np.ndarray:
        """Converts raw text into an empirical character/token frequency distribution."""
        counts = np.zeros(self.vocab_size, dtype=np.float64)
        if not text:
            return np.copy(self.reference_distribution)

        for char in text:
            idx = ord(char) % self.vocab_size
            counts[idx] += 1.0

        total = np.sum(counts)
        if total < 1e-12:
            return np.copy(self.reference_distribution)

        # Dirichlet Bayesian smoothing: for short prompts, smooth with reference distribution
        # to avoid spurious KL divergence explosion on small sample sizes
        prior_weight = max(0.0, 24.0 - total)
        smoothed = counts + (prior_weight * self.reference_distribution)
        return smoothed / np.sum(smoothed)

    def _extract_token_values(
        self,
        prompt_text: str | None = None,
        tokens: Sequence[int | str | float] | None = None,
    ) -> list[float]:
        """Extracts numerical token representations for variance / ACF calculation."""
        if tokens is not None and len(tokens) > 0:
            if isinstance(tokens[0], (int, float)):
                return [float(t) for t in tokens]
            return [float(hash(str(t)) % 1000) for t in tokens]

        if prompt_text:
            words = prompt_text.split()
            if len(words) >= 2:
                return [float(len(w)) for w in words]
            elif len(words) == 1:
                word = words[0]
                if len(word) >= 2:
                    mid = len(word) // 2
                    return [float(len(word[:mid])), float(len(word[mid:]))]
                return [float(len(word)), float(len(word))]

        return [1.0, 1.0]

    def update(
        self,
        prompt_text: str | None = None,
        tokens: Sequence[int | str | float] | None = None,
        distribution: Sequence[float] | None = None,
        token_series: Sequence[float] | None = None,
    ) -> ThermodynamicState:
        """Processes one conversational turn and computes thermodynamic state."""
        self.step_count += 1

        # 1. Compute empirical distribution P and Free Energy F_t
        if distribution is not None:
            p_dist = np.asarray(distribution, dtype=np.float64)
            if len(p_dist) != self.vocab_size:
                p_dist = np.resize(p_dist, self.vocab_size)
        elif prompt_text is not None:
            p_dist = self._extract_distribution_from_text(prompt_text)
        else:
            p_dist = np.ones(self.vocab_size, dtype=np.float64) / self.vocab_size

        fe = compute_free_energy(p_dist, self.reference_distribution)
        self.free_energy_history.append(fe)

        # 2. Token variance and Autocorrelation Lag-1
        if token_series is not None:
            tok_vals = [float(v) for v in token_series]
        else:
            tok_vals = self._extract_token_values(prompt_text, tokens)

        variance, acf1 = compute_token_statistics(tok_vals)
        self.token_variance_history.append(variance)
        self.acf1_history.append(acf1)

        # 3. Dynamic drift velocity & acceleration
        if len(self.free_energy_history) >= 2:
            velocity = self.free_energy_history[-1] - self.free_energy_history[-2]
        else:
            velocity = 0.0
        self.velocities.append(velocity)

        if len(self.velocities) >= 2:
            acceleration = self.velocities[-1] - self.velocities[-2]
        else:
            acceleration = 0.0
        self.accelerations.append(acceleration)

        # 4. Ornstein-Uhlenbeck parameter estimation on recent free energy window
        recent_fe = self.free_energy_history[-self.history_window:]
        theta, mu, sigma = estimate_ou_parameters(recent_fe)

        # 5. Critical Slowing Down (CSD) Index
        csd_idx = compute_csd_index(variance, acf1, self.baseline_variance)

        # 6. Phase transition detection & alert classification
        # Trigger conditions:
        # - Theta collapses below threshold (loss of restoration force)
        # - CSD index surges (high variance + high positive autocorrelation)
        # - Free energy diverges sharply
        is_phase_transition = False
        alert_level = "NORMAL"

        if (theta <= self.theta_threshold and csd_idx >= self.csd_threshold) or (fe >= self.fe_threshold * 1.5):
            alert_level = "CRITICAL"
            is_phase_transition = True
        elif fe >= self.fe_threshold or (fe >= self.fe_threshold * 0.6 and (theta <= self.theta_threshold or csd_idx >= self.csd_threshold)):
            alert_level = "ELEVATED"
        else:
            alert_level = "NORMAL"

        state = ThermodynamicState(
            step=self.step_count,
            free_energy=fe,
            token_variance=variance,
            autocorrelation_lag1=acf1,
            ou_theta=theta,
            ou_mu=mu,
            ou_sigma=sigma,
            drift_velocity=velocity,
            drift_acceleration=acceleration,
            critical_slowing_down_index=csd_idx,
            is_phase_transition=is_phase_transition,
            alert_level=alert_level,
            metadata={
                "fe_threshold": self.fe_threshold,
                "theta_threshold": self.theta_threshold,
                "csd_threshold": self.csd_threshold,
            },
        )
        return state
