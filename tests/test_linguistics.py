"""Tests for linguistic and anthropological classifiers."""

import pytest

from mellm.core.linguistics import (
    LinguisticClassifier,
    LinguisticProfile,
    ShibbolethDetector,
    analyze_heaps_law,
    analyze_zipf_law,
    compute_log_rank_perplexity,
)


def test_zipf_law():
    # Long text with natural Zipfian decay
    sample_text = (
        "the of and to a in is that for it as was with on at by this from they we an "
        "the of and to a in is that for it as the of and to a in is the of and to the of "
        "data model system algorithm network security agent evaluation benchmark log trace "
        "data model system algorithm data model data"
    )
    metrics = analyze_zipf_law(sample_text)
    assert metrics.total_tokens > 20
    assert metrics.alpha > 0.0
    assert 0.0 <= metrics.r_squared <= 1.0


def test_heaps_law():
    tokens = ["word_" + str(i % 15) for i in range(120)]
    metrics = analyze_heaps_law(tokens, step=20)
    assert 0.0 < metrics.beta < 1.0


def test_log_rank_perplexity():
    # High repetition / flat ranks
    flat_tokens = ["the", "the", "system", "the", "model", "the", "the", "system"]
    metrics = compute_log_rank_perplexity(flat_tokens)
    assert metrics.flatness_score > 0.50


def test_shibboleth_detector():
    detector = ShibbolethDetector()
    injected, decoy = detector.inject_decoy("Check the pod status on master", category="regional_slang")
    assert decoy in injected

    # Robotic over-explanation: typical LLM fallback
    robotic_response = (
        f"The term '{decoy}' is a regional expression from southern Brazil meaning friend or fellow. "
        "The cluster pod status is currently healthy."
    )
    result = detector.evaluate_response(robotic_response, decoy_signature=decoy)
    assert result.decoy_detected
    assert result.robotic_overexplanation
    assert result.machine_score > 0.50

    # Natural response: human who ignores or naturally incorporates
    natural_response = "Pod status checked, all 5 replicas up."
    res_nat = detector.evaluate_response(natural_response, decoy_signature=decoy)
    assert not res_nat.robotic_overexplanation
    assert res_nat.machine_score < 0.30


def test_linguistic_classifier_integration():
    classifier = LinguisticClassifier()
    synthetic_ai_text = (
        "In this comprehensive analysis, we systematically investigate the foundational paradigms of autonomous agents. "
        "The phrase 'oxente' is a regional interjection used in Brazilian Portuguese. "
        "Furthermore, the underlying architecture demonstrates robust adherence to systemic security requirements."
    )
    profile = classifier.classify(synthetic_ai_text, decoy_signature="oxente")
    assert isinstance(profile, LinguisticProfile)
    assert profile.shibboleth is not None
    assert profile.shibboleth.robotic_overexplanation
