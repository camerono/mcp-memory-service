"""NLI pattern loader — reads YAML locale files and compiles negation/version patterns."""
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

_PATTERNS_DIR = Path(__file__).parent


def _load_yaml(locale: str) -> dict:
    """Load a single locale YAML file."""
    yaml_path = _PATTERNS_DIR / f"{locale}.yaml"
    if not yaml_path.exists():
        logger.warning("NLI patterns YAML not found for locale '%s' at %s", locale, yaml_path)
        return {}
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=4)
def load_nli_patterns(locales: tuple) -> dict:
    """Load and merge NLI patterns for given locales.

    Returns dict with:
    - negation_pairs: list of (compiled_re_a, compiled_re_b | None) tuples
    - version_patterns: list of compiled regex objects
    """
    negation_pairs: List[Tuple[re.Pattern, Optional[re.Pattern]]] = []
    version_patterns: List[re.Pattern] = []

    for locale in locales:
        data = _load_yaml(locale)
        if not data:
            continue

        for pair in data.get("negation_pairs", []):
            if len(pair) != 2:
                continue
            pat_a_str, pat_b_str = pair
            pat_a = re.compile(pat_a_str, re.IGNORECASE)
            pat_b = re.compile(pat_b_str, re.IGNORECASE) if pat_b_str else None
            negation_pairs.append((pat_a, pat_b))

        for vp in data.get("version_patterns", []):
            version_patterns.append(re.compile(vp, re.IGNORECASE))

    return {
        "negation_pairs": negation_pairs,
        "version_patterns": version_patterns,
    }
