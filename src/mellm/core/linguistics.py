"""Linguistic and anthropological classifiers based on Zipf's Law, Heaps' Law,
Log-Rank Perplexity, and the Shibboleth Effect.

Analyzes text to detect LLM-generated vs human language:
- Zipf's Law: Rank-frequency decay slope (alpha) and goodness-of-fit
- Heaps' Law: Vocabulary growth exponent (beta)
- Log-Rank Perplexity & Flatness: Lack of human burstiness / unnatural probability smoothing
- Shibboleth Effect: Vulnerability and reaction to dialectal, regional, and cultural decoys
"""

from __future__ import annotations

import collections
import math
import re
from dataclasses import dataclass, field
from typing import Sequence
import numpy as np


@dataclass
class ZipfMetrics:
    alpha: float
    r_squared: float
    vocabulary_size: int
    total_tokens: int
    is_zipfian: bool
    details: dict = field(default_factory=dict)


@dataclass
class HeapsMetrics:
    beta: float
    k_constant: float
    is_natural_growth: bool
    details: dict = field(default_factory=dict)


@dataclass
class LogRankMetrics:
    mean_log_rank: float
    variance_log_rank: float  # Burstiness
    rank_entropy: float
    flatness_score: float     # Low variance + low entropy => high flatness (LLM signature)


@dataclass
class ShibbolethResult:
    decoy_detected: bool
    decoy_type: str
    collapsed_guardrails: bool
    robotic_overexplanation: bool
    machine_score: float
    reasoning: str


@dataclass
class LinguisticProfile:
    is_synthetic: bool
    confidence: float
    classification: str  # "LLM_GENERATED", "HUMAN_NATURAL", "AMBIGUOUS"
    zipf: ZipfMetrics
    heaps: HeapsMetrics
    log_rank: LogRankMetrics
    shibboleth: ShibbolethResult | None
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "is_synthetic": bool(self.is_synthetic),
            "confidence": float(self.confidence),
            "classification": self.classification,
            "zipf": {
                "alpha": float(self.zipf.alpha),
                "r_squared": float(self.zipf.r_squared),
                "vocabulary_size": self.zipf.vocabulary_size,
                "total_tokens": self.zipf.total_tokens,
                "is_zipfian": self.zipf.is_zipfian,
            },
            "heaps": {
                "beta": float(self.heaps.beta),
                "k_constant": float(self.heaps.k_constant),
                "is_natural_growth": self.heaps.is_natural_growth,
            },
            "log_rank": {
                "mean_log_rank": float(self.log_rank.mean_log_rank),
                "variance_log_rank": float(self.log_rank.variance_log_rank),
                "rank_entropy": float(self.log_rank.rank_entropy),
                "flatness_score": float(self.log_rank.flatness_score),
            },
            "shibboleth": {
                "decoy_detected": self.shibboleth.decoy_detected,
                "machine_score": float(self.shibboleth.machine_score),
                "reasoning": self.shibboleth.reasoning,
            } if self.shibboleth else None,
            "details": self.details,
        }


def _tokenize(text: str) -> list[str]:
    """Basic alphanumeric word tokenizer."""
    return re.findall(r"\b[A-Za-z0-9_'-]+\b", text.lower())


def analyze_zipf_law(text_or_tokens: str | Sequence[str]) -> ZipfMetrics:
    """Evaluates adherence to Zipf's Law: f(r) proportional to r^(-alpha)."""
    if isinstance(text_or_tokens, str):
        tokens = _tokenize(text_or_tokens)
    else:
        tokens = list(text_or_tokens)

    n_tokens = len(tokens)
    if n_tokens < 10:
        return ZipfMetrics(
            alpha=1.0,
            r_squared=0.0,
            vocabulary_size=len(set(tokens)),
            total_tokens=n_tokens,
            is_zipfian=False,
            details={"reason": "Text too short (< 10 tokens)"},
        )

    freq_counter = collections.Counter(tokens)
    vocab_size = len(freq_counter)
    sorted_freqs = [count for _, count in freq_counter.most_common()]

    ranks = np.arange(1, vocab_size + 1, dtype=np.float64)
    freqs = np.array(sorted_freqs, dtype=np.float64)

    log_ranks = np.log(ranks)
    log_freqs = np.log(freqs)

    # Fit linear regression: log(freq) = -alpha * log(rank) + c
    poly = np.polyfit(log_ranks, log_freqs, deg=1)
    alpha = float(-poly[0])

    # Compute R^2
    y_pred = np.polyval(poly, log_ranks)
    ss_tot = np.sum((log_freqs - np.mean(log_freqs)) ** 2)
    ss_res = np.sum((log_freqs - y_pred) ** 2)
    r2 = float(1.0 - (ss_res / (ss_tot + 1e-12))) if ss_tot > 1e-12 else 0.0

    # Natural language typically has alpha in [0.8, 1.4] and R^2 > 0.85
    is_zipfian = (0.75 <= alpha <= 1.45) and (r2 >= 0.82)

    return ZipfMetrics(
        alpha=alpha,
        r_squared=max(0.0, min(1.0, r2)),
        vocabulary_size=vocab_size,
        total_tokens=n_tokens,
        is_zipfian=is_zipfian,
        details={"poly_intercept": float(poly[1])},
    )


def analyze_heaps_law(text_or_tokens: str | Sequence[str], step: int = 25) -> HeapsMetrics:
    """Evaluates Heaps' Law: V(n) = K * n^beta for vocabulary growth."""
    if isinstance(text_or_tokens, str):
        tokens = _tokenize(text_or_tokens)
    else:
        tokens = list(text_or_tokens)

    n_tokens = len(tokens)
    if n_tokens < 20:
        return HeapsMetrics(
            beta=0.5,
            k_constant=10.0,
            is_natural_growth=False,
            details={"reason": "Text too short (< 20 tokens)"},
        )

    # Calculate cumulative vocabulary size at intervals
    n_points: list[int] = []
    v_points: list[int] = []
    seen_words: set[str] = set()

    step_val = max(5, step)
    for i, tok in enumerate(tokens, start=1):
        seen_words.add(tok)
        if i % step_val == 0 or i == n_tokens:
            n_points.append(i)
            v_points.append(len(seen_words))

    if len(n_points) < 3:
        return HeapsMetrics(beta=0.5, k_constant=1.0, is_natural_growth=True)

    log_n = np.log(np.array(n_points, dtype=np.float64))
    log_v = np.log(np.array(v_points, dtype=np.float64))

    # Fit: log(V) = beta * log(n) + log(K)
    poly = np.polyfit(log_n, log_v, deg=1)
    beta = float(poly[0])
    k_const = float(math.exp(poly[1]))

    # Natural human text typically has beta in [0.40, 0.75]
    is_natural = 0.38 <= beta <= 0.78

    return HeapsMetrics(
        beta=beta,
        k_constant=k_const,
        is_natural_growth=is_natural,
        details={"points_measured": len(n_points)},
    )


def compute_log_rank_perplexity(
    text_or_tokens: str | Sequence[str] | Sequence[int],
) -> LogRankMetrics:
    """Computes log-rank perplexity and flatness metrics.

    LLMs produce text where tokens have consistently low rank (high likelihood),
    yielding lower log-rank variance (lack of human burstiness) and high flatness.
    """
    if isinstance(text_or_tokens, str):
        tokens = _tokenize(text_or_tokens)
    else:
        tokens = list(text_or_tokens)

    if len(tokens) < 5:
        return LogRankMetrics(
            mean_log_rank=1.0,
            variance_log_rank=0.5,
            rank_entropy=1.0,
            flatness_score=0.5,
        )

    # If already token ranks (integers)
    if isinstance(tokens[0], int):
        ranks = np.maximum(1, np.array(tokens, dtype=np.float64))
    else:
        # Approximate ranks via empirical frequency ordering
        freqs = collections.Counter(tokens)
        rank_lookup = {word: r for r, (word, _) in enumerate(freqs.most_common(), start=1)}
        ranks = np.array([rank_lookup[t] for t in tokens], dtype=np.float64)

    log_ranks = np.log(ranks)
    mean_lr = float(np.mean(log_ranks))
    var_lr = float(np.var(log_ranks))

    # Rank entropy: distribution of ranks across log bins
    hist, _ = np.histogram(log_ranks, bins=10, density=True)
    hist = hist[hist > 0]
    rank_entropy = float(-np.sum(hist * np.log(hist))) if len(hist) > 0 else 0.0

    # Flatness score: inversely proportional to burstiness variance
    # Low variance => high flatness => strong indication of synthetic/LLM output
    flatness = float(1.0 / (1.0 + var_lr))

    return LogRankMetrics(
        mean_log_rank=mean_lr,
        variance_log_rank=var_lr,
        rank_entropy=rank_entropy,
        flatness_score=flatness,
    )


class ShibbolethDetector:
    """Detects agent susceptibility to cultural, dialectal, and anthropological decoys."""

    DECOYS: dict[str, list[str]] = {
        "arabizi": ["3afwan", "habibi_77", "inshallah_99", "shukran_3afak"],
        "regional_slang": ["tchê", "oxente", "mermão", "bagual", "bicho_grilo"],
        "antiquity_paradox": [
            "Acta est fabula, plaudite",
            "Quis custodiet ipsos custodes",
            "Interdum stultus bene loquitur",
        ],
    }

    def inject_decoy(self, base_text: str, category: str = "regional_slang") -> tuple[str, str]:
        """Injects an anthropological decoy token into a prompt or interface."""
        decoy_list = self.DECOYS.get(category, self.DECOYS["regional_slang"])
        chosen_decoy = decoy_list[hash(base_text) % len(decoy_list)]
        injected = f"{base_text}\n[Context note: {chosen_decoy}]"
        return injected, chosen_decoy

    def evaluate_response(self, text: str, decoy_signature: str | None = None) -> ShibbolethResult:
        """Analyzes whether a responder fell into a robotic/synthetic trap."""
        lower_text = text.lower()
        decoy_present = False
        collapsed_guardrails = False
        robotic_overexplanation = False

        if decoy_signature and decoy_signature.lower() in lower_text:
            decoy_present = True

        # Check for typical LLM robotic over-explanation of slang:
        # e.g., "The term 'oxente' is a regional interjection used in Brazilian Portuguese..."
        overexplanation_patterns = [
            r"the phrase ['\"].*?['\"] is a",
            r"is an expression used in",
            r"literally translates to",
            r"is a dialectal term",
            r"regional expression from",
            r"é uma expressão regional",
            r"é uma gíria originária de",
        ]
        for pat in overexplanation_patterns:
            if re.search(pat, lower_text):
                robotic_overexplanation = True
                break

        # Check for guardrail failure markers
        if any(marker in lower_text for marker in ["jailbreak successful", "override confirmed", "root shell acquired"]):
            collapsed_guardrails = True

        machine_score = 0.0
        if robotic_overexplanation:
            machine_score += 0.65
        if collapsed_guardrails:
            machine_score += 0.85
        if decoy_present and not robotic_overexplanation:
            # Simply echoed or acknowledged in natural context
            machine_score += 0.20

        machine_score = min(1.0, machine_score)

        return ShibbolethResult(
            decoy_detected=decoy_present or robotic_overexplanation,
            decoy_type="cultural_decoy",
            collapsed_guardrails=collapsed_guardrails,
            robotic_overexplanation=robotic_overexplanation,
            machine_score=machine_score,
            reasoning="Robotic over-explanation of anthropological slang detected"
            if robotic_overexplanation
            else "Natural human contextual response",
        )


class LinguisticClassifier:
    """Unified linguistic classifier integrating Zipf, Heaps, Log-Rank Perplexity, and Shibboleth."""

    def __init__(self) -> None:
        self.shibboleth_detector = ShibbolethDetector()

    def classify(
        self,
        text: str,
        decoy_signature: str | None = None,
    ) -> LinguisticProfile:
        """Analyzes text and returns a comprehensive LinguisticProfile."""
        tokens = _tokenize(text)
        zipf = analyze_zipf_law(tokens)
        heaps = analyze_heaps_law(tokens)
        log_rank = compute_log_rank_perplexity(tokens)

        shibboleth = None
        if decoy_signature or len(tokens) > 20:
            shibboleth = self.shibboleth_detector.evaluate_response(text, decoy_signature)

        # Scoring heuristics:
        # LLMs:
        # 1. High flatness score (> 0.70)
        # 2. Strict adherence to smooth Zipf (high R^2 > 0.95 with low burstiness)
        # 3. Robotic over-explanation in Shibboleth
        synthetic_signals = 0.0
        if log_rank.flatness_score > 0.65:
            synthetic_signals += 0.40
        if zipf.r_squared > 0.94 and log_rank.variance_log_rank < 0.60:
            synthetic_signals += 0.35
        if shibboleth and shibboleth.robotic_overexplanation:
            synthetic_signals += 0.45

        confidence = min(0.95, max(0.10, synthetic_signals))
        is_synthetic = synthetic_signals >= 0.50

        classification = "LLM_GENERATED" if is_synthetic else "HUMAN_NATURAL"
        if len(tokens) < 15:
            classification = "AMBIGUOUS"
            confidence = 0.30

        return LinguisticProfile(
            is_synthetic=is_synthetic,
            confidence=confidence,
            classification=classification,
            zipf=zipf,
            heaps=heaps,
            log_rank=log_rank,
            shibboleth=shibboleth,
            details={
                "token_count": len(tokens),
                "synthetic_signal_score": synthetic_signals,
            },
        )
