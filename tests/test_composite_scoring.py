"""Tests for composite scoring (Issue #55)."""
import pytest

from mcp_memory_service.scoring.composite import (
    DEFAULT_WEIGHTS,
    ScoreWeights,
    centrality_score,
    composite_score,
    proximity_score,
    score_components,
)


class TestProximityScore:
    def test_none_returns_zero(self):
        assert proximity_score(None) == 0.0

    def test_zero_hop_returns_zero(self):
        assert proximity_score(0) == 0.0

    def test_one_hop(self):
        assert proximity_score(1) == pytest.approx(0.5)

    def test_two_hops(self):
        assert proximity_score(2) == pytest.approx(1 / 3, rel=1e-3)

    def test_decay_monotonic(self):
        scores = [proximity_score(i) for i in range(1, 10)]
        assert scores == sorted(scores, reverse=True)


class TestCentralityScore:
    def test_none_returns_zero(self):
        assert centrality_score(None) == 0.0

    def test_zero_degree_returns_zero(self):
        assert centrality_score(0) == 0.0

    def test_max_degree_returns_one(self):
        assert centrality_score(20, max_degree=20) == 1.0

    def test_over_max_capped(self):
        assert centrality_score(100, max_degree=20) == 1.0

    def test_half_degree(self):
        assert centrality_score(10, max_degree=20) == pytest.approx(0.5)


class TestCompositeScore:
    def test_pure_relevance(self):
        score = composite_score(0.8, hop_distance=None, entity_degree=None)
        assert score == pytest.approx(0.8 * 0.6)  # only relevance contributes

    def test_all_components(self):
        score = composite_score(0.8, hop_distance=1, entity_degree=10)
        expected = 0.6 * 0.8 + 0.25 * 0.5 + 0.15 * 0.5
        assert score == pytest.approx(expected)

    def test_custom_weights(self):
        w = ScoreWeights(relevance=0.5, proximity=0.3, centrality=0.2)
        score = composite_score(1.0, hop_distance=1, entity_degree=20, weights=w)
        expected = 0.5 * 1.0 + 0.3 * 0.5 + 0.2 * 1.0
        assert score == pytest.approx(expected)

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError):
            ScoreWeights(relevance=0.5, proximity=0.5, centrality=0.5)

    def test_perfect_score(self):
        score = composite_score(1.0, hop_distance=1, entity_degree=20)
        assert score == pytest.approx(0.6 + 0.25 * 0.5 + 0.15)

    def test_no_graph_data_equals_weighted_relevance(self):
        score = composite_score(0.9)
        assert score == pytest.approx(0.9 * 0.6)


class TestScoreComponents:
    def test_returns_dict(self):
        result = score_components(0.8, hop_distance=1, entity_degree=10)
        assert result == {
            "relevance": 0.8,
            "proximity": pytest.approx(0.5),
            "centrality": pytest.approx(0.5),
        }

    def test_defaults(self):
        result = score_components(0.5)
        assert result == {"relevance": 0.5, "proximity": 0.0, "centrality": 0.0}
