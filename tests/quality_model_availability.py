"""Whether the exported ONNX quality models can actually be exercised.

Four test modules used to answer this question with their own copy of

    Path.home().joinpath(".cache/mcp_memory/onnx_models/<model>/model.onnx").exists()

which was wrong twice over.

It ignored ``MCP_QUALITY_ONNX_MODEL_DIR``, the override added in #171 so the
export location does not depend on ``HOME`` -- with that set, the check looked
in the wrong directory and skipped tests that could have run.

And a file on disk is necessary but not sufficient. Scoring needs onnxruntime to
run the graph and transformers for ``AutoTokenizer``, which ``ONNXRankerModel``
loads from the export directory. Gating on the file alone let the integration
tests un-skip on any machine that had ever exported a model, in an environment
that could not run them, where ``get_onnx_ranker_model`` swallowed the
ImportError and returned None and every assertion died with
``'NoneType' object has no attribute 'score_quality'``.

Import ``DEBERTA_AVAILABLE`` / ``MS_MARCO_AVAILABLE`` from here instead of
rebuilding the check.
"""

import importlib.util

from mcp_memory_service.quality.onnx_ranker import onnx_model_dir

def _installed(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


_RUNTIME_AVAILABLE = _installed("onnxruntime") and _installed("transformers")


def model_exported(model_name: str) -> bool:
    """True when ``model_name`` has an exported graph in the configured directory."""
    return (onnx_model_dir() / model_name / "model.onnx").exists()


DEBERTA_AVAILABLE = _RUNTIME_AVAILABLE and model_exported("nvidia-quality-classifier-deberta")
MS_MARCO_AVAILABLE = _RUNTIME_AVAILABLE and model_exported("ms-marco-MiniLM-L-6-v2")
