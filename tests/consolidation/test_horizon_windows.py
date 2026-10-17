"""Time horizons select memories from the last N days, as the tool documents.

`memory_consolidate` documents its horizons as "Consolidate last 24 hours /
7 days / 30 days / 90 days / 365 days" (tools/registry.py). These tests pin that
contract down at the level of `_get_memories_for_horizon`, which is the single
place that decides which memories a consolidation run may touch.
"""

import tempfile
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from mcp_memory_service.consolidation.base import ConsolidationConfig
from mcp_memory_service.consolidation.consolidator import (
    HORIZON_CONFIGS,
    DreamInspiredConsolidator,
)
from mcp_memory_service.models.memory import Memory

# The windows the tool description promises, in days.
DOCUMENTED_WINDOW_DAYS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
    "quarterly": 90,
    "yearly": 365,
}


def _make_memory(content_hash: str, age_days: float) -> Memory:
    created_at = time.time() - age_days * 86400
    return Memory(
        content=f"memory {content_hash}",
        content_hash=content_hash,
        tags=["test"],
        memory_type="observation",
        embedding=[0.1] * 320,
        created_at=created_at,
        created_at_iso=datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat(),
    )


def _make_range_honouring_storage(memories):
    """Storage mock whose time-range read actually respects the range.

    Without this, a mock returns the whole corpus for any window and a test
    cannot tell a correct window from a missing one.
    """
    storage = AsyncMock()
    storage.db_path = "/tmp/test_memories.db"

    async def _by_range(start_time, end_time, **kwargs):
        return [
            m for m in memories
            if m.created_at and start_time <= m.created_at <= end_time
        ]

    storage.get_memories_by_time_range = AsyncMock(side_effect=_by_range)
    storage.get_all_memories = AsyncMock(return_value=list(memories))
    storage.get_memory_connections = AsyncMock(return_value={})
    storage.get_access_patterns = AsyncMock(return_value={})
    storage.search_by_tag = AsyncMock(return_value=[])
    storage.update_memories_batch = AsyncMock(return_value=[True])
    return storage


def _make_config(**overrides):
    kwargs = dict(
        decay_enabled=True,
        retention_periods={"observation": 30},
        associations_enabled=True,
        min_similarity=0.3,
        max_similarity=0.7,
        max_pairs_per_run=10,
        clustering_enabled=True,
        min_cluster_size=3,
        clustering_algorithm="simple",
        compression_enabled=True,
        max_summary_length=200,
        preserve_originals=True,
        forgetting_enabled=True,
        relevance_threshold=0.1,
        access_threshold_days=30,
        archive_location=tempfile.mkdtemp(),
    )
    kwargs.update(overrides)
    return ConsolidationConfig(**kwargs)


class TestDocumentedWindows:
    """The config table is the contract the tool description advertises."""

    @pytest.mark.parametrize("horizon,days", sorted(DOCUMENTED_WINDOW_DAYS.items()))
    def test_horizon_window_matches_documentation(self, horizon, days):
        assert HORIZON_CONFIGS[horizon]["window"] == timedelta(days=days)

    def test_no_horizon_carries_a_dead_delta_field(self):
        """`delta` was the pre-refactor name and is read nowhere. It must go."""
        for horizon, config in HORIZON_CONFIGS.items():
            assert "delta" not in config, f"{horizon} still carries a dead delta"


class TestHorizonSelectsRecentMemories:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("horizon,days", sorted(DOCUMENTED_WINDOW_DAYS.items()))
    async def test_horizon_returns_memories_inside_its_window(self, horizon, days):
        inside = _make_memory("inside", age_days=days * 0.5)
        outside = _make_memory("outside", age_days=days + 10)
        storage = _make_range_honouring_storage([inside, outside])
        consolidator = DreamInspiredConsolidator(storage, _make_config())

        selected = await consolidator._get_memories_for_horizon(horizon)

        hashes = {m.content_hash for m in selected}
        assert "inside" in hashes
        assert "outside" not in hashes

    @pytest.mark.asyncio
    @pytest.mark.parametrize("horizon", sorted(DOCUMENTED_WINDOW_DAYS))
    async def test_horizon_never_scans_the_whole_store(self, horizon):
        """A bounded window must not be implemented as read-everything-then-filter."""
        storage = _make_range_honouring_storage([_make_memory("h1", age_days=0.1)])
        consolidator = DreamInspiredConsolidator(storage, _make_config())

        await consolidator._get_memories_for_horizon(horizon)

        storage.get_all_memories.assert_not_called()

    @pytest.mark.asyncio
    async def test_quarterly_no_longer_selects_only_ancient_memories(self):
        """Regression guard: quarterly used to keep memories OLDER than 90 days."""
        recent = _make_memory("recent", age_days=10)
        ancient = _make_memory("ancient", age_days=400)
        storage = _make_range_honouring_storage([recent, ancient])
        consolidator = DreamInspiredConsolidator(storage, _make_config())

        selected = await consolidator._get_memories_for_horizon("quarterly")

        assert [m.content_hash for m in selected] == ["recent"]

    @pytest.mark.asyncio
    async def test_weekly_and_monthly_differ_on_the_same_corpus(self):
        """The bug in issue #324: both horizons returned an identical set."""
        memories = [
            _make_memory("day3", age_days=3),
            _make_memory("day20", age_days=20),
        ]
        storage = _make_range_honouring_storage(memories)
        consolidator = DreamInspiredConsolidator(storage, _make_config())

        weekly = await consolidator._get_memories_for_horizon("weekly")
        monthly = await consolidator._get_memories_for_horizon("monthly")

        assert {m.content_hash for m in weekly} == {"day3"}
        assert {m.content_hash for m in monthly} == {"day3", "day20"}


class TestBatchCapAppliesInsideWindow:
    @pytest.mark.asyncio
    async def test_batch_size_keeps_the_oldest_memories_of_the_window(self):
        memories = [
            _make_memory("newest", age_days=1),
            _make_memory("middle", age_days=3),
            _make_memory("oldest", age_days=5),
        ]
        storage = _make_range_honouring_storage(memories)
        config = _make_config(batch_size=2, incremental_mode=True)
        consolidator = DreamInspiredConsolidator(storage, config)

        selected = await consolidator._get_memories_for_horizon("weekly")

        assert [m.content_hash for m in selected] == ["oldest", "middle"]

    @pytest.mark.asyncio
    async def test_window_is_applied_before_the_batch_cap(self):
        """A memory outside the window must not consume a batch slot."""
        memories = [
            _make_memory("in_window", age_days=2),
            _make_memory("way_older", age_days=300),
        ]
        storage = _make_range_honouring_storage(memories)
        config = _make_config(batch_size=1, incremental_mode=True)
        consolidator = DreamInspiredConsolidator(storage, config)

        selected = await consolidator._get_memories_for_horizon("weekly")

        assert [m.content_hash for m in selected] == ["in_window"]
