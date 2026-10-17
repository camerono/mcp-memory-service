"""NER pattern loader — reads YAML locale files and merges/compiles patterns."""
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

import yaml

logger = logging.getLogger(__name__)

_PATTERNS_DIR = Path(__file__).parent


def _load_yaml(locale: str) -> dict:
    """Load a single locale YAML file."""
    yaml_path = _PATTERNS_DIR / f"{locale}.yaml"
    if not yaml_path.exists():
        logger.warning("NER patterns YAML not found for locale '%s' at %s", locale, yaml_path)
        return {}
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=4)
def load_ner_patterns(locales: tuple) -> dict:
    """Load and merge NER patterns for given locales.

    Returns dict with compiled patterns ready for extraction:
    - context_markers_re: compiled regex matching any context marker
    - service_suffixes: set of suffixes
    - stop_entities: frozenset (lowercased for O(1) lookup)
    - known_acronyms_re: compiled regex for known acronyms (word boundary)
    - known_acronyms: set of raw acronym strings
    - min_acronym_length: int
    """
    all_context_markers: List[str] = []
    all_service_suffixes: set = set()
    all_stop_entities: set = set()
    all_known_acronyms: set = set()
    min_acronym_length = 3

    for locale in locales:
        data = _load_yaml(locale)
        if not data:
            continue
        all_context_markers.extend(data.get("context_markers", []))
        all_service_suffixes.update(data.get("service_suffixes", []))
        all_stop_entities.update(data.get("stop_entities", []))
        all_known_acronyms.update(data.get("known_acronyms", []))
        if "min_acronym_length" in data:
            min_acronym_length = data["min_acronym_length"]

    # Compile context markers regex (case insensitive for markers, not for captured groups)
    if all_context_markers:
        markers_pattern = "|".join(re.escape(m) for m in all_context_markers)
        # Use IGNORECASE for marker matching. Capture the next word(s).
        # We'll filter post-match to ensure the captured group starts with uppercase.
        # Capture: one word (non-space sequence up to 50 chars)
        context_markers_re = re.compile(
            rf'(?:{markers_pattern})\s+(\S{{1,50}})',
            re.IGNORECASE
        )
        # Contextual uppercase: marker + ALLCAPS 3-10 chars (NO IGNORECASE on capture)
        context_upper_re = re.compile(
            rf'(?:{markers_pattern})\s+([A-Z]{{3,10}})\b',
            re.IGNORECASE  # for marker matching only
        )
    else:
        context_markers_re = None
        context_upper_re = None

    # Compile known acronyms regex
    if all_known_acronyms:
        acronyms_pattern = "|".join(re.escape(a) for a in sorted(all_known_acronyms, key=len, reverse=True))
        known_acronyms_re = re.compile(rf'\b({acronyms_pattern})\b')
    else:
        known_acronyms_re = None

    # Compile service suffix regex (CamelCase + suffix)
    if all_service_suffixes:
        suffixes_pattern = "|".join(re.escape(s) for s in all_service_suffixes)
        service_re = re.compile(rf'\b([A-Z][a-zA-Z0-9]+(?:{suffixes_pattern}))\b')
    else:
        service_re = None

    return {
        "context_markers_re": context_markers_re,
        "context_upper_re": context_upper_re,
        "service_re": service_re,
        "service_suffixes": frozenset(all_service_suffixes),
        "stop_entities": frozenset(s.lower() for s in all_stop_entities),
        "known_acronyms_re": known_acronyms_re,
        "known_acronyms": frozenset(all_known_acronyms),
        "min_acronym_length": min_acronym_length,
    }
