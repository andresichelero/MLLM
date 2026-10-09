"""Fractal traffic analysis via Detrended Fluctuation Analysis (DFA) and Hurst Exponent.

Calculates the Hurst exponent (H) for network inter-arrival times (IAT) and tool latencies:
- H ~ 0.5: Uncorrelated white noise / random walk increments (mechanical crawlers)
- H > 0.5 (e.g. 0.6 - 0.85): Long-range persistence / self-similarity (human browsing)
- Sudden regime switching (bursts of tool calls followed by inference valleys): LLM cognitive agent signature
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence
import numpy as np


@dataclass
class TrafficClassification:
    """Classification of traffic/latency dynamics based on fractal analysis."""
    hurst_exponent: float
    classification: str  # "HUMAN", "LLM_AGENT", "MECHANICAL_BOT", "INDETERMINATE"
    confidence: float
    cognitive_phase: str  # "BURST_RETRIEVAL", "INFERENCE_VALLEY", "STATIONARY", "UNKNOWN"
    mean_latency: float
    variance_latency: float
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "hurst_exponent": float(self.hurst_exponent),
            "classification": self.classification,
            "confidence": float(self.confidence),
            "cognitive_phase": self.cognitive_phase,
            "mean_latency": float(self.mean_latency),
            "variance_latency": float(self.variance_latency),
            "details": self.details,
        }


def detrended_fluctuation_analysis(
    series: np.ndarray | Sequence[float],
    scale_min: int = 4,
    scale_max: int | None = None,
    scale_step: float = 1.25,
    order: int = 1,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Performs Detrended Fluctuation Analysis (DFA) on a 1D time series.

    Args:
        series: 1D numerical sequence (e.g. inter-arrival times, request latencies).
        scale_min: Minimum window length (must be > order + 1).
        scale_max: Maximum window length (defaults to len(series) // 4).
        scale_step: Geometric scaling ratio between window sizes.
        order: Polynomial order for local trend removal (1 for linear DFA-1).

    Returns:
        tuple (scales, fluctuations, hurst_exponent)
    """
    x = np.asarray(series, dtype=np.float64)
    n = len(x)

    if n < 16:
        # For very short sequences, estimate with standard Rescaled Range or fallback
        return (np.array([4]), np.array([1.0]), 0.5)

    # 1. Profile integration: y(k) = sum_{i=1}^k (x_i - mean(x))
    mean_x = np.mean(x)
    y = np.cumsum(x - mean_x)

    # 2. Determine scales
    if scale_max is None or scale_max > n // 2:
        scale_max = max(scale_min + 2, n // 4)

    scales_list: list[int] = []
    current_scale = float(max(scale_min, order + 2))
    while current_scale <= scale_max:
        s = int(round(current_scale))
        if s not in scales_list and s <= n:
            scales_list.append(s)
        current_scale *= scale_step

    if len(scales_list) < 3:
        scales_list = sorted(list({scale_min, (scale_min + scale_max) // 2, scale_max}))

    fluctuations_list: list[float] = []
    valid_scales: list[int] = []

    for s in scales_list:
        n_segments = n // s
        if n_segments < 1:
            continue

        # Forward and backward segments
        fluct_sq_sum = 0.0
        total_segments = 0

        # Forward
        for v in range(n_segments):
            idx_start = v * s
            idx_end = idx_start + s
            y_seg = y[idx_start:idx_end]
            t = np.arange(s)
            poly = np.polyfit(t, y_seg, deg=order)
            trend = np.polyval(poly, t)
            residual_sq = np.mean((y_seg - trend) ** 2)
            fluct_sq_sum += residual_sq
            total_segments += 1

        # Backward
        for v in range(n_segments):
            idx_end = n - v * s
            idx_start = idx_end - s
            y_seg = y[idx_start:idx_end]
            t = np.arange(s)
            poly = np.polyfit(t, y_seg, deg=order)
            trend = np.polyval(poly, t)
            residual_sq = np.mean((y_seg - trend) ** 2)
            fluct_sq_sum += residual_sq
            total_segments += 1

        if total_segments > 0:
            f_s = math.sqrt(fluct_sq_sum / total_segments)
            if f_s > 1e-12:
                fluctuations_list.append(f_s)
                valid_scales.append(s)

    if len(valid_scales) < 2:
        return (np.array(scales_list), np.ones(len(scales_list)), 0.5)

    log_scales = np.log(np.array(valid_scales, dtype=np.float64))
    log_fluct = np.log(np.array(fluctuations_list, dtype=np.float64))

    # Linear fit: log(F(s)) = H * log(s) + C
    poly_fit = np.polyfit(log_scales, log_fluct, deg=1)
    hurst_exponent = float(poly_fit[0])

    return (np.array(valid_scales), np.array(fluctuations_list), hurst_exponent)


def rolling_hurst(
    series: np.ndarray | Sequence[float],
    window_size: int = 32,
    step: int = 4,
) -> np.ndarray:
    """Computes rolling Hurst exponent over sliding windows to detect cognitive regime shifts."""
    x = np.asarray(series, dtype=np.float64)
    n = len(x)
    if n < window_size:
        _, _, h = detrended_fluctuation_analysis(x)
        return np.array([h])

    results: list[float] = []
    for start in range(0, n - window_size + 1, step):
        sub = x[start : start + window_size]
        _, _, h = detrended_fluctuation_analysis(sub)
        results.append(h)

    return np.array(results, dtype=np.float64)


def classify_traffic(
    iat_or_latencies: np.ndarray | Sequence[float],
    window_size: int = 32,
) -> TrafficClassification:
    """Classifies a traffic / latency series into Human, LLM Agent, or Mechanical Bot."""
    x = np.asarray(iat_or_latencies, dtype=np.float64)
    n = len(x)

    if n == 0:
        return TrafficClassification(
            hurst_exponent=0.5,
            classification="INDETERMINATE",
            confidence=0.0,
            cognitive_phase="UNKNOWN",
            mean_latency=0.0,
            variance_latency=0.0,
            details={"reason": "Empty sequence"},
        )

    mean_lat = float(np.mean(x))
    var_lat = float(np.var(x))

    if n < 16:
        # Basic heuristic for short sequence
        if var_lat < 1e-4:
            return TrafficClassification(
                hurst_exponent=0.5,
                classification="MECHANICAL_BOT",
                confidence=0.7,
                cognitive_phase="STATIONARY",
                mean_latency=mean_lat,
                variance_latency=var_lat,
                details={"reason": "Constant deterministic latency with minimal variance"},
            )
        return TrafficClassification(
            hurst_exponent=0.5,
            classification="INDETERMINATE",
            confidence=0.4,
            cognitive_phase="UNKNOWN",
            mean_latency=mean_lat,
            variance_latency=var_lat,
            details={"reason": "Sequence too short for reliable DFA (< 16 samples)"},
        )

    scales, flucs, hurst = detrended_fluctuation_analysis(x)
    rolling_h = rolling_hurst(x, window_size=min(window_size, max(16, n // 2)))

    # Cognitive phase analysis
    h_variance = float(np.var(rolling_h)) if len(rolling_h) > 1 else 0.0
    cognitive_phase = "STATIONARY"

    # LLM agents exhibit cognitive regime shifts:
    # 1. Bursts of rapid tool requests (low latency, correlated)
    # 2. Significant pause for model inference (e.g. 1.0s - 2.5s)
    # 3. High variance in rolling Hurst values across windows
    has_inference_pauses = np.any((x >= 0.8) & (x <= 4.0))
    has_rapid_bursts = np.any(x < 0.15)

    if has_inference_pauses and has_rapid_bursts:
        classification = "LLM_AGENT"
        confidence = min(0.95, 0.75 + min(0.20, h_variance * 2.0))
        cognitive_phase = "BURST_RETRIEVAL" if x[-1] < 0.5 else "INFERENCE_VALLEY"
    elif var_lat < 0.001 or (0.45 <= hurst <= 0.55 and not has_inference_pauses):
        classification = "MECHANICAL_BOT"
        confidence = 0.85
        cognitive_phase = "STATIONARY"
    elif hurst > 0.60:
        classification = "HUMAN"
        confidence = min(0.90, 0.5 + (hurst - 0.5))
        cognitive_phase = "STATIONARY"
    elif hurst < 0.45:
        classification = "MECHANICAL_BOT"
        confidence = 0.80
        cognitive_phase = "STATIONARY"
    else:
        classification = "INDETERMINATE"
        confidence = 0.50

    return TrafficClassification(
        hurst_exponent=hurst,
        classification=classification,
        confidence=confidence,
        cognitive_phase=cognitive_phase,
        mean_latency=mean_lat,
        variance_latency=var_lat,
        details={
            "rolling_hurst_mean": float(np.mean(rolling_h)),
            "rolling_hurst_variance": h_variance,
            "has_inference_pauses": bool(has_inference_pauses),
            "has_rapid_bursts": bool(has_rapid_bursts),
            "scales_evaluated": [int(s) for s in scales],
        },
    )
