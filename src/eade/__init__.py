"""EADE - an explainable, knowledge-driven and adaptive detection engine."""

from .core.decision import Candidate, Decision, Engine, Result
from .core.evaluation import Metrics, PublicationCriteria, Reference, Verdict, compare_decisions, evaluate, judge
from .core.features import FeatureCatalog, FeatureDef, Normalizer
from .core.knowledge import EngineConfig, FrozenVersionError, KnowledgeVersion, Profile, Ramp, Status
from .core.learning import TEST, TRAIN, Example, LearningOptions, build_candidate, split_for
from .core.rules import Effect, Rule, describe, validate
from .core.signatures import NEGATIVE, POSITIVE, Signature, SimilarityParams

__version__ = "0.1.0.dev0"

__all__ = [
    "Candidate", "Decision", "Engine", "Result",
    "Metrics", "PublicationCriteria", "Reference", "Verdict", "compare_decisions", "evaluate", "judge",
    "FeatureCatalog", "FeatureDef", "Normalizer",
    "EngineConfig", "FrozenVersionError", "KnowledgeVersion", "Profile", "Ramp", "Status",
    "TEST", "TRAIN", "Example", "LearningOptions", "build_candidate", "split_for",
    "Effect", "Rule", "describe", "validate",
    "NEGATIVE", "POSITIVE", "Signature", "SimilarityParams",
]
