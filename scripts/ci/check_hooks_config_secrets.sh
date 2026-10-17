#!/bin/bash
#
# Bundled Hooks Config Secret Check
#
# claude-hooks/config.json is a shipped package asset, not a user-local file:
# utilities/config-loader.js falls back to it when ~/.claude/hooks/config.json
# is absent, and install_hooks.py copies it into the user's home as the base
# config when no existing MCP install is detected. Anything personal committed
# into it is therefore published AND distributed to every installing user.
#
# That is what happened in issue #197 (reported by @timkjr): a real 40-character
# memoryService.http.apiKey and a maintainer-local serverWorkingDir sat in the
# tracked file from 24af496c onward. The installer's key-generation path
# (issue #531) only mints a fresh key when the value is empty or "auto-detect",
# so every install adopted the committed key verbatim.
#
# This gate fails when the bundled config carries a value that looks like a real
# credential or an absolute local path, so the leak cannot come back.
#
# Env overrides (for tests):
#   MCS_HOOKS_CONFIG  path to the bundled config (default: claude-hooks/config.json)
#
# Exit codes:
#   0 - config is free of credentials and local paths
#   1 - a real-looking secret or local path is present, or the check could not run

set -uo pipefail

CONFIG="${MCS_HOOKS_CONFIG:-claude-hooks/config.json}"

# Values that mean "no key set" — the installer replaces these with a generated
# per-user key. Keep in sync with install_hooks.py's key-generation sentinel.
PLACEHOLDER_KEYS=("auto-detect" "" "your-api-key-here" "test-key-123")

if [ ! -f "$CONFIG" ]; then
  echo "FAIL: bundled hooks config not found: $CONFIG"
  echo "If it was removed on purpose, drop this gate and give config-loader.js a"
  echo "bundled default in the same change — hooks fall back to port 8889 without one."
  exit 1
fi

PY=""
for candidate in .venv/bin/python python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
  echo "FAIL: no python interpreter found - this check needs one to parse JSON"
  exit 1
fi

FINDINGS=$(MCS_HOOKS_CONFIG="$CONFIG" \
  MCS_PLACEHOLDERS="$(printf '%s\n' "${PLACEHOLDER_KEYS[@]}")" \
  "$PY" - <<'PYEOF'
import json
import os
import re
import sys

path = os.environ["MCS_HOOKS_CONFIG"]
placeholders = set(os.environ["MCS_PLACEHOLDERS"].split("\n"))

try:
    with open(path, encoding="utf-8") as fh:
        config = json.load(fh)
except (OSError, json.JSONDecodeError) as exc:
    print(f"UNPARSEABLE: {exc}")
    sys.exit(0)

# A committed credential: long, unbroken, and not one of the sentinels the
# installer recognises. Key names are matched loosely so apiKey, api_key, token,
# secret and password are all covered.
SECRET_NAME = re.compile(r"(api_?key|token|secret|password)", re.IGNORECASE)
# Any run of 20+ non-whitespace characters. Deliberately not a character class:
# an earlier version allowed only [A-Za-z0-9_+=/-] and would have waved a JWT
# through on its dots. Prose fails this because prose contains spaces.
SECRET_SHAPE = re.compile(r"^\S{20,}$")
# ...but a key named tokenEndpoint or secretUrl legitimately holds a URL, which
# is long and unbroken too. Exempt anything with a scheme.
URL_SHAPE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
# Absolute POSIX or Windows paths leak the maintainer's checkout layout.
LOCAL_PATH = re.compile(r"^(/(?!$)|[A-Za-z]:[\\/])")

findings = []


def walk(node, trail):
    if isinstance(node, dict):
        for key, value in node.items():
            walk(value, f"{trail}.{key}" if trail else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            walk(value, f"{trail}[{index}]")
    elif isinstance(node, str):
        leaf = trail.rsplit(".", 1)[-1]
        if (
            SECRET_NAME.search(leaf)
            and node not in placeholders
            and SECRET_SHAPE.match(node)
            and not URL_SHAPE.match(node)
        ):
            findings.append(f"{trail}: real-looking credential ({len(node)} chars)")
        elif LOCAL_PATH.match(node):
            findings.append(f"{trail}: absolute local path ({node})")


walk(config, "")
print("\n".join(findings))
PYEOF
)

if [ -n "$(printf '%s' "$FINDINGS" | grep '^UNPARSEABLE:' || true)" ]; then
  echo "FAIL: could not parse $CONFIG"
  printf '%s\n' "$FINDINGS"
  exit 1
fi

if [ -n "$(printf '%s' "$FINDINGS" | tr -d '[:space:]')" ]; then
  echo "FAIL: $CONFIG contains values that must not ship"
  printf '%s\n' "$FINDINGS" | sed 's/^/  /'
  echo
  echo "This file is copied into every user's ~/.claude/hooks/config.json and read"
  echo "directly from the plugin cache. Use a placeholder instead:"
  echo "  apiKey          -> \"auto-detect\"  (the installer mints a per-user key)"
  echo "  serverWorkingDir -> null           (resolved at install time)"
  echo "See issue #197."
  exit 1
fi

echo "PASS: $CONFIG carries no credentials or local paths"
exit 0
