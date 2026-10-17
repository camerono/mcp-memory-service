#!/usr/bin/env bash
# Test harness for scripts/ci/check_hooks_config_secrets.sh
# Plain bash, same shape as test_plugin_version_check.sh (bats not available).
#
# Tests are self-contained: each one writes a throwaway config JSON in
# $TMPDIR_LOCAL and points the script at it via MCS_HOOKS_CONFIG. Nothing
# depends on the real claude-hooks/config.json, so the tests do not rot when it
# gains or loses fields.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/ci/check_hooks_config_secrets.sh"
TMPDIR_LOCAL="$(mktemp -d)"

PASS=0
FAIL=0

run_test() {
  local name="$1"
  shift
  if "$@" 2>&1; then
    echo "ok - $name"
    PASS=$((PASS + 1))
  else
    echo "not ok - $name"
    FAIL=$((FAIL + 1))
  fi
}

# Write a config fixture. $1 is the file name, $2 the JSON body.
write_config() {
  local file="$TMPDIR_LOCAL/$1"
  printf '%s\n' "$2" > "$file"
  echo "$file"
}

check() {
  ( cd "$REPO_ROOT" && MCS_HOOKS_CONFIG="$1" bash "$SCRIPT" )
}

test_placeholder_config_passes() {
  local cfg
  cfg="$(write_config clean.json '{
    "memoryService": {
      "http": {"endpoint": "http://127.0.0.1:8000", "apiKey": "auto-detect"},
      "mcp": {"serverCommand": ["uv", "run", "memory"], "serverWorkingDir": null}
    }
  }')"
  check "$cfg" >/dev/null
}

test_real_api_key_fails() {
  local cfg out
  cfg="$(write_config leaked-key.json '{
    "memoryService": {"http": {"apiKey": "VhOGAoUOE5xBMzuxphDORdyXHNMcDRBxvndKxUop"}}
  }')"
  if out="$(check "$cfg" 2>&1)"; then return 1; fi
  printf '%s' "$out" | grep -q "real-looking credential"
}

test_local_path_fails() {
  local cfg out
  cfg="$(write_config leaked-path.json '{
    "memoryService": {"mcp": {"serverWorkingDir": "/home/someone/repositories/mcp-memory-service"}}
  }')"
  if out="$(check "$cfg" 2>&1)"; then return 1; fi
  printf '%s' "$out" | grep -q "absolute local path"
}

test_windows_path_fails() {
  local cfg out
  cfg="$(write_config leaked-winpath.json '{
    "memoryService": {"mcp": {"serverWorkingDir": "C:\\Users\\someone\\mcp-memory-service"}}
  }')"
  if out="$(check "$cfg" 2>&1)"; then return 1; fi
  printf '%s' "$out" | grep -q "absolute local path"
}

# A nested secret must be found too - the leak was two levels deep.
test_nested_token_fails() {
  local cfg out
  cfg="$(write_config nested-token.json '{
    "sessionHarvest": {"llm": {"groqToken": "gsk1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"}}
  }')"
  if out="$(check "$cfg" 2>&1)"; then return 1; fi
  printf '%s' "$out" | grep -q "real-looking credential"
}

# A JWT's dots put it outside any sane character class - the shape check must be
# "no whitespace", not an allow-list. Mira flagged this false negative on #200.
test_jwt_fails() {
  local cfg out
  cfg="$(write_config leaked-jwt.json '{
    "memoryService": {"http": {"apiKey": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk"}}
  }')"
  if out="$(check "$cfg" 2>&1)"; then return 1; fi
  printf '%s' "$out" | grep -q "real-looking credential"
}

# Punctuation-heavy secrets must not slip through either.
test_punctuation_secret_fails() {
  local cfg out
  cfg="$(write_config leaked-punct.json '{
    "sessionHarvest": {"llm": {"apiSecret": "p@ssw0rd!#$%^&*()_+{}[]|:;<>,.?~-="}}
  }')"
  if out="$(check "$cfg" 2>&1)"; then return 1; fi
  printf '%s' "$out" | grep -q "real-looking credential"
}

# A key whose NAME matches the secret pattern but whose value is a URL is a
# legitimate config value - tokenEndpoint, not a token.
test_url_under_secret_named_key_passes() {
  local cfg
  cfg="$(write_config token-endpoint.json '{
    "oauth": {"tokenEndpoint": "https://auth.example.com/oauth2/v2/token"}
  }')"
  check "$cfg" >/dev/null
}

# Prose under a secret-named key contains spaces, so it must not trip the gate.
test_prose_under_secret_named_key_passes() {
  local cfg
  cfg="$(write_config prose.json '{
    "memoryService": {"http": {"apiKeyHint": "set this to the same value as MCP_API_KEY on your server"}}
  }')"
  check "$cfg" >/dev/null
}

# Relative paths and URLs are legitimate config values, not leaks.
test_relative_paths_and_urls_pass() {
  local cfg
  cfg="$(write_config relative.json '{
    "memoryService": {
      "http": {"endpoint": "https://memory.example.com:8443", "apiKey": ""},
      "mcp": {"serverWorkingDir": "./scripts", "serverCommand": ["uv", "run", "memory"]}
    }
  }')"
  check "$cfg" >/dev/null
}

# Short, human-readable values under a secret-ish name are placeholders, not keys.
test_short_placeholder_key_passes() {
  local cfg
  cfg="$(write_config short-key.json '{
    "memoryService": {"http": {"apiKey": "your-api-key-here"}}
  }')"
  check "$cfg" >/dev/null
}

test_missing_config_fails() {
  local out
  if out="$(check "$TMPDIR_LOCAL/does-not-exist.json" 2>&1)"; then return 1; fi
  printf '%s' "$out" | grep -q "not found"
}

test_unparseable_config_fails() {
  local cfg out
  cfg="$(write_config broken.json '{ this is not json')"
  if out="$(check "$cfg" 2>&1)"; then return 1; fi
  printf '%s' "$out" | grep -q "could not parse"
}

# The real shipped config must satisfy the gate.
test_repository_config_passes() {
  ( cd "$REPO_ROOT" && bash "$SCRIPT" ) >/dev/null
}

run_test "placeholder config passes"                     test_placeholder_config_passes
run_test "committed api key fails"                       test_real_api_key_fails
run_test "absolute posix path fails"                     test_local_path_fails
run_test "absolute windows path fails"                   test_windows_path_fails
run_test "nested token fails"                            test_nested_token_fails
run_test "jwt fails (dots are not in any allow-list)"    test_jwt_fails
run_test "punctuation-heavy secret fails"                test_punctuation_secret_fails
run_test "url under a secret-named key passes"           test_url_under_secret_named_key_passes
run_test "prose under a secret-named key passes"         test_prose_under_secret_named_key_passes
run_test "relative paths and urls pass"                  test_relative_paths_and_urls_pass
run_test "short placeholder key passes"                  test_short_placeholder_key_passes
run_test "missing config is reported"                    test_missing_config_fails
run_test "unparseable config is reported"                test_unparseable_config_fails
run_test "the repository's own config passes"            test_repository_config_passes

rm -rf "$TMPDIR_LOCAL"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
