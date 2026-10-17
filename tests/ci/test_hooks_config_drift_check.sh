#!/usr/bin/env bash
# Test harness for scripts/ci/check_hooks_config_drift.sh
# Plain bash, same shape as test_hooks_config_secrets_check.sh (bats not available).
#
# The gate shipped in #201 without tests, so the only evidence it worked was a
# manual run recorded in a PR comment. These are those six cases, in the repo.
#
# Tests are self-contained: each writes a throwaway template in $TMPDIR_LOCAL and
# points the script at it via MCS_HOOKS_CONFIG_TEMPLATE, comparing against the
# real claude-hooks/config.json. Nothing depends on the template's own contents,
# so the tests do not rot when a section is legitimately added to both files.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/ci/check_hooks_config_drift.sh"
CONFIG="$REPO_ROOT/claude-hooks/config.json"
TEMPLATE="$REPO_ROOT/claude-hooks/config.template.json"
TMPDIR_LOCAL="$(mktemp -d)"

PASS=0
FAIL=0

PY=""
for candidate in "$REPO_ROOT/.venv/bin/python" python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then
  echo "not ok - no python interpreter available to build fixtures"
  exit 1
fi

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

check() {
  ( cd "$REPO_ROOT" && MCS_HOOKS_CONFIG_TEMPLATE="$1" bash "$SCRIPT" )
}

# Derive a template fixture from the real one by running a snippet of python
# against it. $1 is the output name, $2 a python statement mutating `d`.
mutate_template() {
  local out="$TMPDIR_LOCAL/$1" stmt="$2"
  "$PY" -c "
import json
d = json.load(open('$TEMPLATE'))
$stmt
json.dump(d, open('$out', 'w'))
"
  echo "$out"
}

test_in_sync_passes() {
  check "$TEMPLATE" >/dev/null
}

# The failure this gate exists for: the template falls behind a whole section.
test_template_missing_section_fails() {
  local cfg out
  cfg="$(mutate_template t-missing.json "d.pop(sorted(d)[0])")"
  if out="$(check "$cfg" 2>&1)"; then return 1; fi
  printf '%s' "$out" | grep -q "diverged"
}

# Drift in the other direction must fail too - the check is bidirectional.
test_template_extra_nested_key_fails() {
  local cfg out
  cfg="$(mutate_template t-extra.json "d['memoryService']['bogusNewKey'] = 1")"
  if out="$(check "$cfg" 2>&1)"; then return 1; fi
  printf '%s' "$out" | grep -q "diverged"
}

test_config_extra_nested_key_fails() {
  local cfg tpl out
  cfg="$(mutate_template c-extra.json "d['memoryService']['onlyInConfig'] = 1")"
  # Swap the roles: the mutated file stands in for config.json this time.
  if out="$( cd "$REPO_ROOT" && MCS_HOOKS_CONFIG="$cfg" MCS_HOOKS_CONFIG_TEMPLATE="$TEMPLATE" bash "$SCRIPT" 2>&1 )"; then return 1; fi
  printf '%s' "$out" | grep -q "diverged"
}

# Values are expected to differ - that is the whole point of a template. Only
# keys are compared, so a placeholder endpoint must not trip the gate.
test_differing_values_pass() {
  local cfg
  cfg="$(mutate_template t-values.json "d['memoryService']['http']['endpoint'] = 'https://totally-different:9999'")"
  check "$cfg" >/dev/null
}

test_unparseable_template_fails() {
  local out
  printf '{ not json\n' > "$TMPDIR_LOCAL/t-broken.json"
  if out="$(check "$TMPDIR_LOCAL/t-broken.json" 2>&1)"; then return 1; fi
  printf '%s' "$out" | grep -q "could not parse"
}

test_missing_template_fails() {
  local out
  if out="$(check "$TMPDIR_LOCAL/does-not-exist.json" 2>&1)"; then return 1; fi
  printf '%s' "$out" | grep -q "not found"
}

run_test "the repository's own two configs are in sync"  test_in_sync_passes
run_test "template missing a top-level section fails"    test_template_missing_section_fails
run_test "extra nested key in the template fails"        test_template_extra_nested_key_fails
run_test "extra nested key in the config fails"          test_config_extra_nested_key_fails
run_test "differing values with identical keys pass"     test_differing_values_pass
run_test "unparseable template is reported"              test_unparseable_template_fails
run_test "missing template is reported"                  test_missing_template_fails

rm -rf "$TMPDIR_LOCAL"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
