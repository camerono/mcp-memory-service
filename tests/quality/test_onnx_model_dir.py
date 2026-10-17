"""Tests for the MCP_QUALITY_ONNX_MODEL_DIR override (issue #171, from #170).

The ONNX model cache directory used to be hardcoded to
``Path.home() / ".cache" / "mcp_memory" / "onnx_models"``. In a container that
resolved to ``/root/.cache/...`` only because the images run as root and set
neither USER nor HOME, so mounting pre-exported models depended on an
implementation accident. These tests pin the override and, just as importantly,
pin the default so existing installs do not move.
"""

import os
from pathlib import Path

import pytest

from mcp_memory_service.quality import onnx_ranker
from mcp_memory_service.quality.onnx_ranker import (
    DEFAULT_ONNX_MODEL_DIR,
    onnx_model_dir,
)

ENV_VAR = "MCP_QUALITY_ONNX_MODEL_DIR"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts with the override unset."""
    monkeypatch.delenv(ENV_VAR, raising=False)


def test_default_is_unchanged():
    """No override means the historical path, so existing installs do not move."""
    assert onnx_model_dir() == Path.home() / ".cache" / "mcp_memory" / "onnx_models"
    assert onnx_model_dir() == DEFAULT_ONNX_MODEL_DIR


def test_override_is_honored(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "baked"))
    assert onnx_model_dir() == tmp_path / "baked"


def test_override_is_independent_of_home(monkeypatch, tmp_path):
    """The point of the override: it must not depend on HOME resolving usefully.

    A read-only-rootfs, non-root container had to point HOME at a writable
    volume purely to place the models. With the override set, HOME is irrelevant.
    """
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "models"))
    monkeypatch.setenv("HOME", str(tmp_path / "somewhere-else"))
    assert onnx_model_dir() == tmp_path / "models"


def test_tilde_is_expanded(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "~/onnx-elsewhere")
    assert onnx_model_dir() == Path.home() / "onnx-elsewhere"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_override_falls_back_to_default(monkeypatch, blank):
    """An empty or whitespace-only value is 'unset', not 'use the empty path'.

    Compose and Kubernetes both make it easy to define a variable with no value;
    treating that as Path('') would send the loader to the process working
    directory.
    """
    monkeypatch.setenv(ENV_VAR, blank)
    assert onnx_model_dir() == DEFAULT_ONNX_MODEL_DIR


def test_loader_appends_the_model_name(monkeypatch, tmp_path):
    """The override is the parent, so one setting covers every model.

    This is the layout the documented mount recipe uses: a directory of
    per-model subdirectories.
    """
    monkeypatch.setenv(ENV_VAR, str(tmp_path))
    base = onnx_model_dir()
    assert base / "nvidia-quality-classifier-deberta" == tmp_path / "nvidia-quality-classifier-deberta"
    assert base / "ms-marco-MiniLM-L-6-v2" == tmp_path / "ms-marco-MiniLM-L-6-v2"


class TestFactoryHonorsTheOverride:
    """get_onnx_ranker_model used to check Path.home() directly.

    ONNXRankerModel resolves its own paths through onnx_model_dir(), but the
    factory in front of it hardcoded the default. With the override set, the
    gate looked under HOME, found nothing, and returned None for a model that
    was sitting in the configured directory the whole time (issue #304).
    """

    MODEL = "nvidia-quality-classifier-deberta"

    @pytest.fixture(autouse=True)
    def _isolate_home(self, monkeypatch, tmp_path):
        """Point HOME somewhere empty.

        Without this the tests pass against the old code too on any machine that
        happens to have a model exported under the real HOME -- which is exactly
        the state that made this bug invisible.
        """
        monkeypatch.setenv("HOME", str(tmp_path / "home"))

    def _export(self, base: Path) -> None:
        target = base / self.MODEL
        target.mkdir(parents=True)
        (target / "model.onnx").write_bytes(b"not a real graph")

    def test_finds_an_exported_model_under_the_override(self, monkeypatch, tmp_path):
        self._export(tmp_path / "models")
        monkeypatch.setenv(ENV_VAR, str(tmp_path / "models"))
        monkeypatch.setattr(onnx_ranker, "ONNX_AVAILABLE", True)
        # transformers absent is the interesting case: the export path is
        # unavailable, so an already-exported model is the only way through.
        monkeypatch.setattr(onnx_ranker, "TRANSFORMERS_AVAILABLE", False)
        sentinel = object()
        monkeypatch.setattr(onnx_ranker, "ONNXRankerModel", lambda **kwargs: sentinel)

        assert onnx_ranker.get_onnx_ranker_model(self.MODEL) is sentinel

    def test_returns_none_when_the_override_holds_no_export(self, monkeypatch, tmp_path):
        monkeypatch.setenv(ENV_VAR, str(tmp_path))
        monkeypatch.setattr(onnx_ranker, "ONNX_AVAILABLE", True)
        monkeypatch.setattr(onnx_ranker, "TRANSFORMERS_AVAILABLE", False)

        assert onnx_ranker.get_onnx_ranker_model(self.MODEL) is None
