"""Extension points.

A domain adapter (EADE Geo for orthophotos and cadastre, or any other domain)
plugs into the core by implementing these protocols. The core only ever sees
Candidates and feature vectors.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from .decision import Candidate
from .features import FeatureCatalog, FeatureVector


@runtime_checkable
class CandidateProvider(Protocol):
    """Produces candidates from an input (a raster tile, a document, a record...).

    It should return the candidates it rejected too, flagged with
    `classic_accepted=False`: EADE may send a wrongly rejected object to review.
    """

    name: str
    version: str

    def candidates(self, source: Any, options: Mapping[str, Any] | None = None) -> Iterable[Candidate]: ...


@runtime_checkable
class FeatureExtractor(Protocol):
    """Measures an object, including one drawn by an operator, with the domain features."""

    version: str

    def catalog(self) -> FeatureCatalog: ...

    def measure(self, obj: Any, source: Any, context: Mapping[str, Any] | None = None) -> FeatureVector: ...
