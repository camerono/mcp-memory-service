"""Composite scoring — relevance + graph proximity + entity centrality.

Opt-in scoring model for memory_explore / memory_detail (Issue #55).
Default weights tuned for knowledge navigation (not flat retrieval).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ScoreWeights:
    relevance: float = 0.6
    proximity: float = 0.25
    centrality: float = 0.15

    def __post_init__(self):
        total = self.relevance + self.proximity + self.centrality
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total}")


DEFAULT_WEIGHTS = ScoreWeights()


def proximity_score(hop_distance: Optional[int]) -> float:
    """Decay function for graph hop distance. 1-hop=0.5, 2-hop=0.33, None=0."""
    if hop_distance is None or hop_distance <= 0:
        return 0.0
    return 1.0 / (1.0 + hop_distance)


def centrality_score(entity_degree: Optional[int], max_degree: int = 20) -> float:
    """Normalize entity degree to 0-1. Capped at max_degree."""
    if entity_degree is None or entity_degree <= 0:
        return 0.0
    return min(entity_degree / max_degree, 1.0)


def composite_score(
    relevance: float,
    hop_distance: Optional[int] = None,
    entity_degree: Optional[int] = None,
    weights: ScoreWeights = DEFAULT_WEIGHTS,
    max_degree: int = 20,
) -> float:
    """Compute composite score combining semantic relevance, graph proximity, and centrality.

    Args:
        relevance: Semantic similarity score (0-1)
        hop_distance: Hops from query entity (1=direct, None=no graph connection)
        entity_degree: Number of entity links (centrality proxy)
        weights: Score component weights (must sum to 1.0)
        max_degree: Cap for centrality normalization

    Returns:
        Weighted composite score (0-1)
    """
    prox = proximity_score(hop_distance)
    cent = centrality_score(entity_degree, max_degree)
    return (
        weights.relevance * relevance
        + weights.proximity * prox
        + weights.centrality * cent
    )


def score_components(
    relevance: float,
    hop_distance: Optional[int] = None,
    entity_degree: Optional[int] = None,
    max_degree: int = 20,
) -> dict:
    """Return individual score components for transparency."""
    return {
        "relevance": relevance,
        "proximity": proximity_score(hop_distance),
        "centrality": centrality_score(entity_degree, max_degree),
    }
