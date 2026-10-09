"""Tests for Detrended Fluctuation Analysis (DFA) and Hurst exponent."""

import numpy as np
import pytest

from mellm.core.fractals import (
    detrended_fluctuation_analysis,
    rolling_hurst,
    classify_traffic,
    TrafficClassification,
)


def test_dfa_white_noise():
    np.random.seed(42)
    # White noise should yield Hurst exponent around 0.5 (+/- 0.15)
    noise = np.random.normal(0, 1, 1000)
    scales, flucs, hurst = detrended_fluctuation_analysis(noise)
    assert len(scales) >= 3
    assert len(flucs) >= 3
    assert 0.35 <= hurst <= 0.65


def test_dfa_persistent_walk():
    np.random.seed(42)
    # Random walk cumulative sum has persistent long memory
    steps = np.random.normal(0, 1, 1000)
    walk = np.cumsum(steps)
    _, _, hurst = detrended_fluctuation_analysis(walk)
    # Theoretical H for random walk is ~ 1.5 in standard fractional walk
    assert hurst > 0.70


def test_rolling_hurst():
    np.random.seed(42)
    series = np.concatenate([
        np.random.normal(0, 1, 100),
        np.cumsum(np.random.normal(0, 1, 100)),
    ])
    rh = rolling_hurst(series, window_size=32, step=8)
    assert len(rh) > 0
    assert isinstance(rh, np.ndarray)


def test_classify_traffic_mechanical_bot():
    # Exactly spaced requests (e.g. crontab crawler requesting every 0.10s)
    latencies = [0.10] * 30
    res = classify_traffic(latencies)
    assert isinstance(res, TrafficClassification)
    assert res.classification == "MECHANICAL_BOT"


def test_classify_traffic_llm_agent():
    # Characteristic LLM agent pattern:
    # Rapid tool queries (< 0.05s) followed by cognitive model inference pause (~1.7s)
    pattern = [0.02, 0.03, 0.04, 1.75, 0.03, 0.02, 1.80, 0.04, 0.03, 1.70] * 3
    res = classify_traffic(pattern)
    assert res.classification == "LLM_AGENT"
    assert res.confidence > 0.60
    assert res.to_dict()["cognitive_phase"] in ("BURST_RETRIEVAL", "INFERENCE_VALLEY")


def test_classify_traffic_edge_cases():
    # Empty
    empty_res = classify_traffic([])
    assert empty_res.classification == "INDETERMINATE"
    assert empty_res.confidence == 0.0

    # Short
    short_res = classify_traffic([0.1, 0.2, 0.3])
    assert short_res.classification in ("INDETERMINATE", "MECHANICAL_BOT")
