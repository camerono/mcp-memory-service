"""
A disabled quality system must not load a model.

Both public entry points on QualityEvaluator returned a neutral score when
`enabled=False`, but they called `_ensure_initialized()` first, so the local ONNX
ranker was loaded anyway. With onnxscript installed that load performs a real
torch.onnx.export of DeBERTa, and in CI it pushed
tests/test_quality_system.py::TestQualityEvaluator::test_disabled_quality_system
past pytest's 120s timeout — a feature that is switched off paying for a model
export.

These tests assert the ordering, not the timing: with the system disabled the
loader is never called. Imports go through `mcp_memory_service.*` rather than the
`src.` prefix on purpose, so the patch target is the same module object the code
under test uses (see issue #308).
"""

from unittest.mock import patch

import pytest

from mcp_memory_service.models.memory import Memory
from mcp_memory_service.quality.ai_evaluator import QualityEvaluator
from mcp_memory_service.quality.config import QualityConfig

LOADER = "mcp_memory_service.quality.ai_evaluator.get_onnx_ranker_model"


def _memory(content="Test content", content_hash="test_hash"):
    return Memory(content=content, content_hash=content_hash, metadata={})


@pytest.mark.asyncio
async def test_disabled_evaluate_quality_loads_no_model():
    evaluator = QualityEvaluator(QualityConfig(enabled=False))

    with patch(LOADER) as loader:
        score = await evaluator.evaluate_quality("test query", _memory())

    assert score == 0.5
    loader.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_evaluate_quality_batch_loads_no_model():
    evaluator = QualityEvaluator(QualityConfig(enabled=False))
    memories = [_memory(content=f"Test content {i}", content_hash=f"hash_{i}") for i in range(3)]

    with patch(LOADER) as loader:
        scores = await evaluator.evaluate_quality_batch("test query", memories)

    assert scores == [0.5, 0.5, 0.5]
    loader.assert_not_called()


def test_disabled_ensure_initialized_is_a_no_op():
    """The guard lives in _ensure_initialized, so a direct call is covered too.

    _initialized stays False on purpose: flipping the config to enabled later
    must still initialize.
    """
    evaluator = QualityEvaluator(QualityConfig(enabled=False))

    with patch(LOADER) as loader:
        evaluator._ensure_initialized()

    loader.assert_not_called()
    assert evaluator._initialized is False
