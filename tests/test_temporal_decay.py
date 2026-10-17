"""Tests for temporal decay opt-in behavior (#119)."""
import os
import time
from unittest.mock import patch

import pytest


class TestTemporalDecayDisabled:
    """When MEMORY_DECAY_WINDOW_DAYS=0 (default), ranking must be unchanged."""

    @patch.dict(os.environ, {"MEMORY_DECAY_WINDOW_DAYS": "0"})
    def test_effective_confidence_returns_base_confidence(self):
        """With decay disabled, effective_confidence returns confidence unchanged."""
        from mcp_memory_service.storage.mixins.metadata import MetadataMixin

        now = time.time()
        old_time = now - (90 * 86400)  # 90 days ago
        # Even for very old memories, with decay=0, returns original confidence
        result = MetadataMixin._effective_confidence(0.8, old_time, old_time, now)
        assert result == 0.8

    @patch.dict(os.environ, {"MEMORY_DECAY_WINDOW_DAYS": "0"})
    def test_decay_disabled_ranking_unchanged(self):
        """With decay disabled, old and new memories rank by pure similarity only."""
        from mcp_memory_service.storage.mixins.metadata import MetadataMixin

        now = time.time()
        old_time = now - (180 * 86400)  # 180 days ago
        new_time = now - (1 * 86400)  # 1 day ago
        # Both should return same confidence regardless of age
        old_result = MetadataMixin._effective_confidence(0.9, old_time, old_time, now)
        new_result = MetadataMixin._effective_confidence(0.9, new_time, new_time, now)
        assert old_result == new_result == 0.9


class TestTemporalDecayEnabled:
    """When MEMORY_DECAY_WINDOW_DAYS > 0, recent memories rank higher."""

    @patch.dict(os.environ, {"MEMORY_DECAY_WINDOW_DAYS": "30"})
    def test_recent_memory_scores_higher(self):
        """With decay enabled, recent memory has higher effective_confidence than old."""
        from mcp_memory_service.storage.mixins.metadata import MetadataMixin

        now = time.time()
        old_time = now - (90 * 86400)  # 90 days ago
        new_time = now - (1 * 86400)  # 1 day ago
        old_score = MetadataMixin._effective_confidence(0.9, old_time, old_time, now)
        new_score = MetadataMixin._effective_confidence(0.9, new_time, new_time, now)
        assert new_score > old_score
