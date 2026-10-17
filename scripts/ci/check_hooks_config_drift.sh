#!/bin/bash
#
# Bundled Hooks Config Template Drift Check
#
# claude-hooks/config.json (the shipped, functional bundled config that
# install_hooks.py actually parses to generate a user's real config) and
# claude-hooks/config.template.json (a reference copy install_hooks.py drops
# into ~/.claude/hooks/ verbatim, documenting the full schema) are two
# independent files with no shared source — nothing keeps their key
# structure in sync when one changes.
#
# That's how config.template.json ended up 8 top-level sections behind and
# using a stale memoryService shape (flat apiKey/endpoint instead of the
# real http/mcp sub-objects) — see issue #197. This gate fails the build
# when the two files' key structures diverge, so it can't happen silently
# again. It ignores values entirely (a real endpoint in config.json vs a
# placeholder in the template is expected and correct) and only compares
# keys, recursively, at every nesting level.
#
# Env overrides (for tests):
#   MCS_HOOKS_CONFIG           path to the bundled config (default: claude-hooks/config.json)
#   MCS_HOOKS_CONFIG_TEMPLATE  path to the template (default: claude-hooks/config.template.json)
#
# Exit codes:
#   0 - the two files have identical key structure
#   1 - the key structures diverged, or a file could not be parsed

set -uo pipefail

CONFIG="${MCS_HOOKS_CONFIG:-claude-hooks/config.json}"
TEMPLATE="${MCS_HOOKS_CONFIG_TEMPLATE:-claude-hooks/config.template.json}"

for f in "$CONFIG" "$TEMPLATE"; do
  if [ ! -f "$f" ]; then
    echo "FAIL: file not found: $f"
    exit 1
  fi
done

PY=""
for candidate in .venv/bin/python python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
  echo "FAIL: no python interpreter found - this check needs one to parse JSON"
  exit 1
fi

OUTPUT=$(MCS_HOOKS_CONFIG="$CONFIG" MCS_HOOKS_CONFIG_TEMPLATE="$TEMPLATE" "$PY" - <<'PYEOF'
import json
import os
import sys

config_path = os.environ["MCS_HOOKS_CONFIG"]
template_path = os.environ["MCS_HOOKS_CONFIG_TEMPLATE"]

for label, path in (("config", config_path), ("template", template_path)):
    try:
        with open(path, encoding="utf-8") as fh:
            globals()[label] = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"UNPARSEABLE: {path}: {exc}")
        sys.exit(0)

findings = []


def walk(path, a, b):
    a_keys = set(a.keys()) if isinstance(a, dict) else None
    b_keys = set(b.keys()) if isinstance(b, dict) else None
    if a_keys is None or b_keys is None:
        return
    label = path or "<root>"
    only_config = a_keys - b_keys
    only_template = b_keys - a_keys
    if only_config:
        findings.append(f"{label}: in config.json but missing from template: {sorted(only_config)}")
    if only_template:
        findings.append(f"{label}: in template but missing from config.json: {sorted(only_template)}")
    for key in a_keys & b_keys:
        walk(f"{path}.{key}" if path else key, a[key], b[key])


walk("", config, template)
print("\n".join(findings))
PYEOF
)

if printf '%s' "$OUTPUT" | grep -q '^UNPARSEABLE:'; then
  echo "FAIL: could not parse a config file"
  printf '%s\n' "$OUTPUT"
  exit 1
fi

if [ -n "$(printf '%s' "$OUTPUT" | tr -d '[:space:]')" ]; then
  echo "FAIL: $CONFIG and $TEMPLATE have diverged"
  printf '%s\n' "$OUTPUT" | sed 's/^/  /'
  echo
  echo "These files have no shared source, so nothing keeps their key structure"
  echo "in sync automatically. Add the same keys to whichever file is missing"
  echo "them (values may legitimately differ — e.g. a real default in"
  echo "config.json vs a placeholder in the template)."
  exit 1
fi

echo "PASS: $CONFIG and $TEMPLATE have identical key structure"
exit 0
