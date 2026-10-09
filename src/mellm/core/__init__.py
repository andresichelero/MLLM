"""Core physical, mathematical, and linguistic models for agent detection."""

from .thermodynamics import KaPromptDetector, ThermodynamicState
from .fractals import detrended_fluctuation_analysis, classify_traffic, TrafficClassification
from .causal import CausalReplanningEngine, CRFResult, PerturbationType
from .linguistics import LinguisticClassifier, ShibbolethDetector, analyze_zipf_law, analyze_heaps_law

__all__ = [
    "KaPromptDetector",
    "ThermodynamicState",
    "detrended_fluctuation_analysis",
    "classify_traffic",
    "TrafficClassification",
    "CausalReplanningEngine",
    "CRFResult",
    "PerturbationType",
    "LinguisticClassifier",
    "ShibbolethDetector",
    "analyze_zipf_law",
    "analyze_heaps_law",
]
