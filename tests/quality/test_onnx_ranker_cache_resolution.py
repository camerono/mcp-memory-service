"""Regression tests for issue #304: let huggingface_hub resolve its own cache.

onnx_ranker used to build the cache path by hand --
``~/.cache/huggingface/hub/models--<id>/snapshots`` -- and then take
``snapshots[0]`` from a glob. Two things were wrong with that. It ignored
``HF_HOME`` and ``HF_HUB_CACHE``, which this project sets itself in
``offline_mode.py`` and ``server/environment.py``, so with either set the lookup
missed the real cache entirely. And an interrupted download leaves an empty
snapshot directory next to the good one, so whichever the glob returned first
decided whether the model loaded at all.

This is the same class of bug as #171, where the ONNX model directory was
hardcoded to ``Path.home()``. The fix is to address models by repository id and
let the hub library resolve location and revision.
"""

import ast
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mcp_memory_service.quality import onnx_ranker

MODULE_SOURCE = Path(inspect.getfile(onnx_ranker)).read_text()


class TestNoHandRolledCachePaths:
    """Source-level guards. These need no ml extras and run everywhere."""

    def test_no_snapshot_path_helper(self):
        """The get_snapshot_path helper is gone and must not come back."""
        tree = ast.parse(MODULE_SOURCE)
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert "get_snapshot_path" not in names, (
            "get_snapshot_path reintroduces the hand-built cache lookup from #304; "
            "pass the repo id to from_pretrained instead."
        )

    def test_no_huggingface_cache_path_literals(self):
        """No string literal builds a huggingface cache path.

        Checked against literals rather than raw text so the explanatory comments,
        which name the old path on purpose, do not trip this. Matched on the two
        fragments that only a cache path contains, so the "pip install ...
        huggingface-hub" hint in the ImportError branch stays out of it.
        """
        tree = ast.parse(MODULE_SOURCE)
        offenders = [
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and (".cache/huggingface" in n.value or "models--" in n.value)
        ]
        assert not offenders, (
            f"Hardcoded huggingface cache path(s) {offenders!r}. huggingface_hub "
            "resolves its own cache and honors HF_HOME/HF_HUB_CACHE; see #304."
        )


@pytest.mark.skipif(
    not onnx_ranker.TRANSFORMERS_AVAILABLE,
    reason="Requires the ml extras (transformers, torch, huggingface-hub)",
)
class TestQualityModelLoadsByRepoId:
    """Behavioural guard: QualityModel must address the base model by repo id."""

    CONFIG = {
        "base_model": "microsoft/deberta-v3-base",
        "fc_dropout": 0.1,
        "id2label": {0: "Low", 1: "Medium", 2: "High"},
    }

    def _fake_auto_model(self):
        fake = MagicMock()
        fake.config.hidden_size = 768
        return fake

    def test_passes_repo_id_not_a_filesystem_path(self):
        with patch.object(onnx_ranker, "AutoModel") as auto_model:
            auto_model.from_pretrained.return_value = self._fake_auto_model()
            onnx_ranker.QualityModel(config=self.CONFIG)

        (called_with,), kwargs = auto_model.from_pretrained.call_args
        assert called_with == "microsoft/deberta-v3-base"
        assert "snapshots" not in called_with
        assert kwargs.get("local_files_only") is False

    def test_forwards_local_files_only(self):
        """The offline branch of the export path depends on this being honored."""
        with patch.object(onnx_ranker, "AutoModel") as auto_model:
            auto_model.from_pretrained.return_value = self._fake_auto_model()
            onnx_ranker.QualityModel(config=self.CONFIG, local_files_only=True)

        _, kwargs = auto_model.from_pretrained.call_args
        assert kwargs.get("local_files_only") is True
