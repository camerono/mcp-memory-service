"""Tests for MultilingualDomainExtractor and NLI locale patterns."""
import asyncio
import os
from unittest.mock import patch

import pytest


class TestMultilingualNEREnOnly:
    """Tests with EN-only locale."""

    def setup_method(self):
        # Clear lru_cache between tests
        from mcp_memory_service.config.locale import get_active_locales
        from mcp_memory_service.extraction.ner_patterns import load_ner_patterns
        get_active_locales.cache_clear()
        load_ner_patterns.cache_clear()

    @patch.dict(os.environ, {"MCP_LOCALE": "en"}, clear=False)
    def test_extracts_camelcase_services(self):
        """EN locale: extracts CamelCase service names with known suffixes."""
        from mcp_memory_service.config.locale import get_active_locales
        get_active_locales.cache_clear()
        from mcp_memory_service.extraction.multilingual import MultilingualDomainExtractor

        extractor = MultilingualDomainExtractor(locales=["en"])
        entities = extractor.extract("The UserService handles authentication and PaymentController processes orders.")
        names = [e.name for e in entities]
        assert "UserService" in names
        assert "PaymentController" in names

    @patch.dict(os.environ, {"MCP_LOCALE": "en"}, clear=False)
    def test_extracts_quoted_terms(self):
        """EN locale: extracts quoted terms (3-50 chars, not allcaps)."""
        from mcp_memory_service.extraction.multilingual import MultilingualDomainExtractor

        extractor = MultilingualDomainExtractor(locales=["en"])
        entities = extractor.extract('We deployed the "staging-cluster" and used "Redis Cache" for sessions.')
        names = [e.name for e in entities]
        assert "staging-cluster" in names
        assert "Redis Cache" in names


class TestMultilingualNERPtBR:
    """Tests with PT-BR locale."""

    def setup_method(self):
        from mcp_memory_service.config.locale import get_active_locales
        from mcp_memory_service.extraction.ner_patterns import load_ner_patterns
        get_active_locales.cache_clear()
        load_ner_patterns.cache_clear()

    def test_extracts_gov_acronyms(self):
        """PT-BR locale: extracts known government acronyms."""
        from mcp_memory_service.extraction.multilingual import MultilingualDomainExtractor

        extractor = MultilingualDomainExtractor(locales=["pt_BR"])
        entities = extractor.extract(
            "O SICAR e o INCRA precisam de integração com o SIGEF para validação."
        )
        names = [e.name for e in entities]
        assert "SICAR" in names
        assert "INCRA" in names
        assert "SIGEF" in names

    def test_extracts_contextual_nouns(self):
        """PT-BR locale: extracts contextual proper nouns after markers."""
        from mcp_memory_service.extraction.multilingual import MultilingualDomainExtractor

        extractor = MultilingualDomainExtractor(locales=["pt_BR"])
        entities = extractor.extract("O sistema MIR precisa de atualização no módulo Cadastro.")
        names = [e.name for e in entities]
        assert "MIR" in names or "Cadastro" in names

    def test_extracts_camelcase_services_pt_br(self):
        """PT-BR locale: also extracts CamelCase services (shared suffixes)."""
        from mcp_memory_service.extraction.multilingual import MultilingualDomainExtractor

        extractor = MultilingualDomainExtractor(locales=["pt_BR"])
        entities = extractor.extract("Chamamos o RegularidadeService para validar o imóvel.")
        names = [e.name for e in entities]
        assert "RegularidadeService" in names


class TestMultilingualNERMultiLocale:
    """Tests with multi-locale (en,pt_BR)."""

    def setup_method(self):
        from mcp_memory_service.config.locale import get_active_locales
        from mcp_memory_service.extraction.ner_patterns import load_ner_patterns
        get_active_locales.cache_clear()
        load_ner_patterns.cache_clear()

    def test_extracts_from_both_locales(self):
        """Multi-locale: extracts acronyms from PT-BR and services from EN."""
        from mcp_memory_service.extraction.multilingual import MultilingualDomainExtractor

        extractor = MultilingualDomainExtractor(locales=["en", "pt_BR"])
        entities = extractor.extract(
            "The DATAPREV team uses UserService to integrate with SICAR platform."
        )
        names = [e.name for e in entities]
        assert "DATAPREV" in names
        assert "UserService" in names
        assert "SICAR" in names


class TestMultilingualNEREdgeCases:
    """Edge cases and filters."""

    def setup_method(self):
        from mcp_memory_service.config.locale import get_active_locales
        from mcp_memory_service.extraction.ner_patterns import load_ner_patterns
        get_active_locales.cache_clear()
        load_ner_patterns.cache_clear()

    def test_missing_yaml_locale_logs_warning(self, caplog):
        """Missing YAML locale: logs warning, continues without crash."""
        import logging
        from mcp_memory_service.extraction.multilingual import MultilingualDomainExtractor

        with caplog.at_level(logging.WARNING):
            extractor = MultilingualDomainExtractor(locales=["xx_MISSING"])
            entities = extractor.extract("Some text with UserService in it.")
            # Should still work (empty patterns, no crash)
            assert isinstance(entities, list)
        assert "xx_MISSING" in caplog.text

    def test_stop_entities_filtered(self):
        """Stop entities (API, URL, SQL, etc.) are NOT extracted."""
        from mcp_memory_service.extraction.multilingual import MultilingualDomainExtractor

        extractor = MultilingualDomainExtractor(locales=["en"])
        # "API" appears after a context marker but should be filtered
        entities = extractor.extract('The service API handles requests. Use the tool HTTP for calls.')
        names = [e.name for e in entities]
        assert "API" not in names
        assert "HTTP" not in names

    def test_no_ignorecase_bug(self):
        """Lowercase word after marker is NOT extracted as entity (no IGNORECASE on capture)."""
        from mcp_memory_service.extraction.multilingual import MultilingualDomainExtractor

        extractor = MultilingualDomainExtractor(locales=["en"])
        # "simple" is lowercase — should NOT be captured as a proper noun
        entities = extractor.extract("The project simple setup worked fine.")
        names = [e.name for e in entities]
        # "simple" starts with lowercase, should NOT be extracted
        assert "simple" not in names
        # But "Simple" with uppercase would be fine
        entities2 = extractor.extract("The project Simple setup worked fine.")
        names2 = [e.name for e in entities2]
        assert "Simple" in names2

    def test_empty_content_returns_empty_list(self):
        """Empty content: returns empty list."""
        from mcp_memory_service.extraction.multilingual import MultilingualDomainExtractor

        extractor = MultilingualDomainExtractor(locales=["en"])
        assert extractor.extract("") == []
        assert extractor.extract(None) == []  # type: ignore

    def test_performance_frozenset_lookups(self):
        """Performance: stop_entities is a frozenset (O(1) lookups)."""
        from mcp_memory_service.extraction.ner_patterns import load_ner_patterns

        patterns = load_ner_patterns(("en",))
        assert isinstance(patterns["stop_entities"], frozenset)
        # O(1) membership test
        assert "api" in patterns["stop_entities"]
        assert "url" in patterns["stop_entities"]


class TestNLIPtBRPatterns:
    """Tests for NLI contradiction detection with PT-BR patterns."""

    def setup_method(self):
        from mcp_memory_service.config.locale import get_active_locales
        from mcp_memory_service.reasoning.nli_patterns import load_nli_patterns
        get_active_locales.cache_clear()
        load_nli_patterns.cache_clear()

    @patch.dict(os.environ, {"MCP_LOCALE": "pt_BR"}, clear=False)
    def test_desativado_vs_ativado_contradiction(self):
        """PT-BR NLI: 'desativado' vs 'ativado' detected as contradiction."""
        from mcp_memory_service.config.locale import get_active_locales
        get_active_locales.cache_clear()
        from mcp_memory_service.reasoning.nli_patterns import load_nli_patterns
        load_nli_patterns.cache_clear()

        from mcp_memory_service.reasoning.nli import NLIClassifier, _PATTERNS

        # Reload patterns with pt_BR
        import mcp_memory_service.reasoning.nli as nli_module
        nli_module._PATTERNS = load_nli_patterns(("pt_BR",))

        classifier = NLIClassifier(backend="heuristic")
        result = classifier._heuristic_classify(
            "O serviço está desativado no ambiente de produção.",
            "O serviço está ativado no ambiente de produção."
        )
        assert result.label == "contradiction"
        assert result.confidence >= 0.5

    @patch.dict(os.environ, {"MCP_LOCALE": "en"}, clear=False)
    def test_disabled_vs_enabled_contradiction(self):
        """EN NLI: 'disabled' vs 'enabled' detected as contradiction."""
        from mcp_memory_service.config.locale import get_active_locales
        get_active_locales.cache_clear()
        from mcp_memory_service.reasoning.nli_patterns import load_nli_patterns
        load_nli_patterns.cache_clear()

        from mcp_memory_service.reasoning.nli import NLIClassifier
        import mcp_memory_service.reasoning.nli as nli_module
        nli_module._PATTERNS = load_nli_patterns(("en",))

        classifier = NLIClassifier(backend="heuristic")
        result = classifier._heuristic_classify(
            "The caching feature is disabled in production.",
            "The caching feature is enabled in production."
        )
        assert result.label == "contradiction"
        assert result.confidence >= 0.5
