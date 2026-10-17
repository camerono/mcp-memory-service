"""
Regression guard for the setuptools bound on the [milvus] extra.

milvus-lite 2.5.x imports `pkg_resources` unguarded at the top of
milvus_lite/__init__.py and never declares setuptools as a dependency.
setuptools removed pkg_resources in 82.0.0, and Python 3.12 dropped setuptools
from ensurepip, so both "too new" and "absent" end in ModuleNotFoundError at
import time. The [milvus] extra therefore has to declare setuptools itself,
unconditionally and below 82.

The bound was previously `setuptools<83; python_version >= '3.13'`, which
allowed the broken 82.x and skipped every Python below 3.13 entirely. A bulk
dependency bump has widened a milvus bound by accident before (see the pymilvus
comment in pyproject.toml), which is what this test is here to catch.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

if sys.version_info >= (3, 11):
    import tomllib  # inline import: stdlib only from 3.11, project supports 3.10
else:
    try:
        import tomllib  # inline import: stdlib only from 3.11, project supports 3.10
    except ImportError:
        import tomli as tomllib  # inline import: 3.10 fallback


def _milvus_extra():
    with open(PYPROJECT_PATH, "rb") as f:
        data = tomllib.load(f)
    return data["project"]["optional-dependencies"]["milvus"]


def _setuptools_requirements():
    return [r for r in _milvus_extra() if r.split(";")[0].strip().startswith("setuptools")]


class TestMilvusSetuptoolsPin:
    def test_milvus_extra_declares_setuptools(self):
        """Without an explicit declaration, milvus-lite has no pkg_resources to import."""
        assert _setuptools_requirements(), (
            "The [milvus] extra must declare setuptools: milvus-lite imports "
            "pkg_resources but does not depend on setuptools itself."
        )

    def test_setuptools_bound_excludes_82(self):
        """82.0.0 removed pkg_resources, so the upper bound has to stop below it."""
        for req in _setuptools_requirements():
            spec = req.split(";")[0].strip()
            assert "<82" in spec, (
                f"Expected an upper bound below 82 on setuptools, found {spec!r}. "
                "setuptools 82.0.0 removed pkg_resources, which milvus-lite imports."
            )

    def test_setuptools_bound_is_unconditional(self):
        """A python_version marker leaves the older Pythons unguarded."""
        for req in _setuptools_requirements():
            assert ";" not in req, (
                f"The setuptools bound must apply to every Python, found a marker in {req!r}. "
                "Python 3.12 already ships venvs without setuptools."
            )


@pytest.mark.parametrize("required", ["pymilvus", "milvus-lite", "onnxruntime"])
def test_milvus_extra_keeps_its_core_pins(required):
    """Guard the rest of the extra against the same kind of accidental drop."""
    names = [r.split(";")[0].strip() for r in _milvus_extra()]
    assert any(n.startswith(required) for n in names), f"{required} missing from the [milvus] extra"
