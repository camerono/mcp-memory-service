"""Tests for belief semantic grouping + noise filter (#121 patches 1+2).

Verifies that derive_beliefs actually produces beliefs from realistic data
and that noise (checkpoints, associations) is excluded.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from mcp_memory_service.consolidation.belief_service import BeliefService, _is_noise


class TestNoiseFilter:
    def test_association_is_noise(self):
        assert _is_noise("Association between abc and def: semantic")

    def test_checkpoint_is_noise(self):
        assert _is_noise("[CHECKPOINT] Session DNBSCDC289...")

    def test_harvested_sessions_is_noise(self):
        assert _is_noise("harvested_sessions:abc,def,ghi")

    def test_cluster_is_noise(self):
        assert _is_noise("Cluster of 478 related memories")

    def test_mined_is_noise(self):
        assert _is_noise("[MINED:BUG] Some bug description")

    def test_sessao_is_noise(self):
        assert _is_noise("[SESSÃO] something about the session")

    def test_real_observation_is_not_noise(self):
        assert not _is_noise("Redis has no persistence in our deployment")

    def test_real_decision_is_not_noise(self):
        assert not _is_noise("We decided to use PostgreSQL for the cache")

    def test_empty_string_is_not_noise(self):
        assert not _is_noise("")


class TestSemanticGrouping:
    @pytest.mark.asyncio
    async def test_similar_observations_grouped(self):
        """Observations with similarity > 0.85 should be in same group."""
        storage = AsyncMock()

        # 3 similar observations about Redis
        obs1 = MagicMock(content="Redis has no persistence configured", content_hash="hash1")
        obs2 = MagicMock(content="Redis runs without persistence enabled", content_hash="hash2")
        obs3 = MagicMock(content="Redis persistence is not active", content_hash="hash3")
        # 1 unrelated observation
        obs4 = MagicMock(content="PostgreSQL backup runs daily at 3am", content_hash="hash4")

        observations = [obs1, obs2, obs3, obs4]

        # Mock storage.retrieve to return similar results for Redis obs
        async def mock_retrieve(content, n_results=50):
            if "Redis" in content:
                r1 = MagicMock(memory=MagicMock(content_hash="hash1"), relevance_score=0.95)
                r2 = MagicMock(memory=MagicMock(content_hash="hash2"), relevance_score=0.92)
                r3 = MagicMock(memory=MagicMock(content_hash="hash3"), relevance_score=0.90)
                return [r1, r2, r3]
            return []

        storage.retrieve = mock_retrieve

        service = BeliefService(storage)
        groups = await service._group_observations(observations)

        # Redis observations should be in one group (3 members)
        redis_group = None
        for content, obs_list in groups.items():
            if "Redis" in content:
                redis_group = obs_list
                break

        assert redis_group is not None
        assert len(redis_group) >= 2  # At least 2 similar grouped together

    @pytest.mark.asyncio
    async def test_dissimilar_observations_separate(self):
        """Observations below threshold should remain in separate groups."""
        storage = AsyncMock()

        obs1 = MagicMock(content="Redis has no persistence", content_hash="hash1")
        obs2 = MagicMock(content="PostgreSQL backup runs daily", content_hash="hash2")

        observations = [obs1, obs2]

        # No similar results returned
        storage.retrieve = AsyncMock(return_value=[])

        service = BeliefService(storage)
        groups = await service._group_observations(observations)

        assert len(groups) == 2

    @pytest.mark.asyncio
    async def test_storage_failure_graceful(self):
        """If storage.retrieve fails, each obs becomes its own group."""
        storage = AsyncMock()

        obs1 = MagicMock(content="Observation one", content_hash="hash1")
        obs2 = MagicMock(content="Observation two", content_hash="hash2")

        observations = [obs1, obs2]

        storage.retrieve = AsyncMock(side_effect=Exception("DB error"))

        service = BeliefService(storage)
        groups = await service._group_observations(observations)

        # Each observation is its own cluster (graceful degradation)
        assert len(groups) == 2

    @pytest.mark.asyncio
    async def test_noise_excluded_from_derive(self):
        """Noise observations should never reach grouping."""
        storage = AsyncMock()
        storage.get_all_memories = AsyncMock(return_value=[
            MagicMock(content="Association between x and y", content_hash="noise1"),
            MagicMock(content="[CHECKPOINT] session state", content_hash="noise2"),
            MagicMock(content="Real observation about deployment", content_hash="real1"),
        ])
        storage.retrieve = AsyncMock(return_value=[])

        service = BeliefService(storage)

        # Patch _get_belief and _create_belief to track calls
        service._get_belief = AsyncMock(return_value=None)
        service._create_belief = AsyncMock()
        service._find_contradictions = AsyncMock(return_value=[])

        stats = await service.derive_beliefs()

        # Only 1 real observation should be processed (noise filtered)
        # It won't promote (needs >=3) but should not error
        assert len(stats["errors"]) == 0
        # Should have created 1 belief (from the single real observation)
        assert stats["created"] == 1

    @pytest.mark.asyncio
    async def test_all_noise_returns_empty_stats(self):
        """If all observations are noise, return empty stats without error."""
        storage = AsyncMock()
        storage.get_all_memories = AsyncMock(return_value=[
            MagicMock(content="Association between x and y", content_hash="noise1"),
            MagicMock(content="[CHECKPOINT] session state", content_hash="noise2"),
            MagicMock(content="harvested_sessions:abc,def", content_hash="noise3"),
        ])

        service = BeliefService(storage)
        stats = await service.derive_beliefs()

        assert stats["created"] == 0
        assert stats["updated"] == 0
        assert len(stats["errors"]) == 0
