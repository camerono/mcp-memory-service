#!/usr/bin/env python3
"""Benchmark NER domain extraction — MultilingualDomainExtractor.

Usage:
    python scripts/benchmarks/benchmark_ner_domain.py --corpus-size 200
"""
import argparse
import os
import sys
import time

# Ensure the src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from mcp_memory_service.extraction.multilingual import MultilingualDomainExtractor


# Synthetic corpus samples for benchmarking
_EN_SAMPLES = [
    'The UserService handles authentication and PaymentController processes orders via "Redis Cache".',
    "We deployed the project Kubernetes on the cluster staging-01 using the framework Spring Boot.",
    "The database PostgreSQL stores data for the service analytics and the tool Grafana monitors it.",
    'The system MIR integrates with SICAR and SIGEF for rural property validation.',
    "AuthenticationService validates tokens, SessionManager handles state, CacheProvider stores results.",
    'The platform AWS hosts our "production-cluster" with the library React for frontend.',
    "Use the module DataSync to replicate between the database Primary and database Replica.",
    'The project "Meu Imóvel Rural" uses INCRA data from SNCR integration.',
    "NotificationHandler sends alerts, SchedulerConfig manages cron, FactoryClient builds connections.",
    "The service HCSO provides RITM and CHG management for DATAPREV infrastructure.",
]

_PT_BR_SAMPLES = [
    "O sistema MIR precisa de atualização no módulo Cadastro para integrar com SICAR.",
    "O serviço RegularidadeService valida imóveis usando dados do INCRA e SIGEF.",
    "A plataforma Roma Connect gerencia as APIs do HCSO e do WSO2.",
    "O projeto RER usa o banco PostgreSQL e o cluster Kubernetes para deploy.",
    'A ferramenta "Jenkins" orquestra o CI/CD no servidor BuildPrimary.',
    "O programa PRONAF distribui recursos via DAP para agricultores familiares.",
    "O módulo AutenticacaoController valida tokens do Gov.br usando SERPRO.",
    "A aplicação MCR consulta dados do BCB e BNDES para crédito rural.",
    "O portal Cadastro Rural usa IntegracaoService para consultar CAFIR e NIRF.",
    "O sistema ELK monitora logs do cluster produção via ferramenta Kibana.",
]


def generate_corpus(size: int, locales: list) -> list:
    """Generate a benchmark corpus of given size."""
    samples = []
    if "en" in locales:
        samples.extend(_EN_SAMPLES)
    if "pt_BR" in locales:
        samples.extend(_PT_BR_SAMPLES)
    if not samples:
        samples = _EN_SAMPLES

    corpus = []
    for i in range(size):
        corpus.append(samples[i % len(samples)])
    return corpus


def run_benchmark(corpus_size: int, locales: list):
    """Run the NER domain extraction benchmark."""
    print(f"📊 NER Domain Extraction Benchmark")
    print(f"   Corpus size: {corpus_size}")
    print(f"   Locales: {locales}")
    print()

    extractor = MultilingualDomainExtractor(locales=locales)
    corpus = generate_corpus(corpus_size, locales)

    # Warmup
    for text in corpus[:10]:
        extractor.extract(text)

    # Benchmark
    start = time.perf_counter()
    total_entities = 0
    for text in corpus:
        entities = extractor.extract(text)
        total_entities += len(entities)
    elapsed = time.perf_counter() - start

    docs_per_sec = corpus_size / elapsed if elapsed > 0 else 0
    entities_per_doc = total_entities / corpus_size if corpus_size > 0 else 0

    print(f"✅ Results:")
    print(f"   Time: {elapsed:.3f}s")
    print(f"   Throughput: {docs_per_sec:.0f} docs/sec")
    print(f"   Total entities: {total_entities}")
    print(f"   Entities/doc: {entities_per_doc:.1f}")
    print()

    # Sample output
    print("📋 Sample extractions (first 3 docs):")
    for i, text in enumerate(corpus[:3]):
        entities = extractor.extract(text)
        print(f"   [{i+1}] {text[:80]}...")
        for e in entities:
            print(f"       → {e.name} ({e.entity_type}, src={e.source})")
        print()

    return {
        "corpus_size": corpus_size,
        "elapsed_s": elapsed,
        "docs_per_sec": docs_per_sec,
        "total_entities": total_entities,
        "entities_per_doc": entities_per_doc,
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark NER domain extraction")
    parser.add_argument("--corpus-size", type=int, default=200, help="Number of documents")
    parser.add_argument("--locales", type=str, default="en,pt_BR", help="Comma-separated locales")
    args = parser.parse_args()

    locales = [loc.strip() for loc in args.locales.split(",")]
    os.environ["MCP_LOCALE"] = ",".join(locales)

    run_benchmark(args.corpus_size, locales)


if __name__ == "__main__":
    main()
