# Domain-Specific Entity Extractors

mcp-memory-service supports pluggable domain-specific NER (Named Entity Recognition) extractors.

## How it works

When `MCP_ENTITY_LINKING_ENABLED=true`, the service extracts entities from stored memories. By default, it extracts @mentions, #tags, URLs, and file paths.

You can extend this with domain-specific extractors (medical, legal, technical, etc.) that run alongside the built-in patterns.

## Creating a Domain Extractor

Implement a class with an `extract` method:

```python
from mcp_memory_service.reasoning.entities import Entity, DomainExtractor

class MedicalExtractor:
    def extract(self, content: str, metadata: dict | None = None) -> list[Entity]:
        entities = []
        # Your extraction logic here
        if 'diabetes' in content.lower():
            entities.append(Entity(name='diabetes', entity_type='condition', source='domain'))
        return entities
```

## Registering Extractors

Set the `MCP_ENTITY_EXTRACTOR_MODULES` environment variable:

```bash
# Single extractor
export MCP_ENTITY_EXTRACTOR_MODULES="mypackage.ner:MedicalExtractor"

# Multiple extractors (comma-separated)
export MCP_ENTITY_EXTRACTOR_MODULES="mypackage.ner:MedicalExtractor,other.mod:LegalExtractor"
```

Format: `module.path:ClassName` (colon-separated module and class name).

## Notes

- Extractors are loaded once at first use (lazy initialization)
- If an extractor raises an exception, it's logged and skipped (non-fatal)
- Entities are deduplicated across all extractors
- No additional dependencies required — your extractor is pure Python
- For ML-based extraction (spaCy, etc.), install those deps in your environment
