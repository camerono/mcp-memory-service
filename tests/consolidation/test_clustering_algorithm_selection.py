"""Clustering picks an algorithm honestly, or says why it cannot.

Before this, `MCP_CLUSTERING_ALGORITHM` defaulted to `dbscan` while scikit-learn
was declared in no extra, and a missing import silently rewrote the choice to
`simple` behind a single WARNING. These tests pin down the replacement: `auto`
resolves to whatever is installed and says so, an explicitly configured
sklearn algorithm fails loudly instead of becoming a different algorithm, and
the health check reports what is actually in use.
"""

import importlib
import tempfile

import pytest

from mcp_memory_service.config import consolidation as config_mod
from mcp_memory_service.consolidation import clustering as clustering_mod
from mcp_memory_service.consolidation.base import (
    ConsolidationConfig,
    ConsolidationError,
)
from mcp_memory_service.consolidation.clustering import (
    SemanticClusteringEngine,
    resolve_clustering_algorithm,
)
from mcp_memory_service.consolidation.health import ConsolidationHealthMonitor


def _config(algorithm):
    return ConsolidationConfig(
        clustering_algorithm=algorithm,
        min_cluster_size=8,
        archive_location=tempfile.mkdtemp(),
    )


@pytest.fixture
def without_sklearn(monkeypatch):
    monkeypatch.setattr(clustering_mod, "SKLEARN_AVAILABLE", False)


@pytest.fixture
def with_sklearn(monkeypatch):
    monkeypatch.setattr(clustering_mod, "SKLEARN_AVAILABLE", True)


class TestDefault:
    def test_default_algorithm_is_auto(self):
        """The default must be satisfiable without optional dependencies."""
        assert ConsolidationConfig().clustering_algorithm == "auto"

    def test_env_default_is_auto(self, monkeypatch):
        """With MCP_CLUSTERING_ALGORITHM unset the config must land on 'auto'.

        Reloaded deliberately: CONSOLIDATION_CONFIG reads the environment while
        being imported, so asserting on the already-imported module would test
        whichever value the developer happens to have in their .env.
        """
        monkeypatch.delenv("MCP_CLUSTERING_ALGORITHM", raising=False)
        reloaded = importlib.reload(config_mod)
        try:
            assert reloaded.CONSOLIDATION_CONFIG["clustering_algorithm"] == "auto"
        finally:
            importlib.reload(config_mod)


class TestResolveAlgorithm:
    def test_auto_picks_dbscan_when_sklearn_present(self, with_sklearn):
        assert resolve_clustering_algorithm("auto") == "dbscan"

    def test_auto_falls_back_to_simple_without_sklearn(self, without_sklearn):
        assert resolve_clustering_algorithm("auto") == "simple"

    def test_simple_is_honoured_even_with_sklearn(self, with_sklearn):
        assert resolve_clustering_algorithm("simple") == "simple"

    @pytest.mark.parametrize("algorithm", ["dbscan", "hierarchical"])
    def test_explicit_sklearn_algorithm_is_honoured_when_available(
        self, with_sklearn, algorithm
    ):
        assert resolve_clustering_algorithm(algorithm) == algorithm

    @pytest.mark.parametrize("algorithm", ["dbscan", "hierarchical"])
    def test_explicit_sklearn_algorithm_raises_without_sklearn(
        self, without_sklearn, algorithm
    ):
        """No silent downgrade: a configured algorithm never becomes another one."""
        with pytest.raises(ConsolidationError) as exc:
            resolve_clustering_algorithm(algorithm)

        message = str(exc.value)
        assert algorithm in message
        assert "scikit-learn" in message
        assert "clustering" in message  # names the extra to install


class TestEngineUsesResolvedAlgorithm:
    def test_engine_resolves_auto_to_simple_without_sklearn(self, without_sklearn):
        engine = SemanticClusteringEngine(_config("auto"))
        assert engine.algorithm == "simple"

    def test_engine_resolves_auto_to_dbscan_with_sklearn(self, with_sklearn):
        engine = SemanticClusteringEngine(_config("auto"))
        assert engine.algorithm == "dbscan"

    def test_engine_refuses_to_start_on_unsatisfiable_config(self, without_sklearn):
        with pytest.raises(ConsolidationError):
            SemanticClusteringEngine(_config("dbscan"))


class TestHealthReportsRealState:
    @pytest.mark.asyncio
    async def test_health_reports_the_algorithm_actually_in_use(self, without_sklearn):
        monitor = ConsolidationHealthMonitor(_config("auto"))

        health = await monitor._check_clustering_engine_health()

        assert health["checks"]["clustering_algorithm"] == "simple"
        assert health["checks"]["sklearn"] == "unavailable"

    @pytest.mark.asyncio
    async def test_health_reports_dbscan_when_available(self, with_sklearn):
        monitor = ConsolidationHealthMonitor(_config("auto"))

        health = await monitor._check_clustering_engine_health()

        assert health["checks"]["clustering_algorithm"] == "dbscan"
        assert health["checks"]["sklearn"] == "available"

    @pytest.mark.asyncio
    async def test_health_does_not_claim_available_on_broken_config(
        self, without_sklearn
    ):
        """A health check must not raise, but it must not call this healthy either."""
        monitor = ConsolidationHealthMonitor(_config("dbscan"))

        health = await monitor._check_clustering_engine_health()

        assert health["checks"]["clustering_algorithm"] != "available"
        assert "unsatisfiable" in health["checks"]["clustering_algorithm"]
