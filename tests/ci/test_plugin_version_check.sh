#!/usr/bin/env bash
# Test harness for scripts/ci/check_plugin_version.sh
# Plain bash, same shape as test_check_versions.sh (bats not available).
#
# Tests are self-contained: each one builds a throwaway git repo in $TMPDIR_LOCAL
# with a fake plugin manifest, hooks dir and _version.py, then runs the script
# inside it. Nothing depends on this repository's real history, so the tests do
# not rot when claude-hooks/ or the plugin version change.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/ci/check_plugin_version.sh"
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

# Build a fixture repo laid out like the real one:
#   claude-hooks/.claude-plugin/plugin.json   (plugin version)
#   claude-hooks/core/hook.js                (a hook file)
#   src/mcp_memory_service/_version.py       (service version)
# Returns the repo path on stdout. History:
#   c1  initial, plugin 1.0.0
#   c2  plugin author field changed (version line untouched)
# The caller adds whatever commits the scenario needs on top.
make_fixture_repo() {
  local repo="$TMPDIR_LOCAL/$1"
  mkdir -p "$repo/claude-hooks/.claude-plugin" "$repo/claude-hooks/core" \
           "$repo/src/mcp_memory_service"
  (
    cd "$repo"
    git init -q -b main
    git config user.email t@example.com
    git config user.name Test
    write_manifest "$repo" 1.0.0 '{"name": "doobidoo"}'
    echo "// hook" > claude-hooks/core/hook.js
    echo '__version__ = "11.0.0"' > src/mcp_memory_service/_version.py
    git add -A && git commit -q -m "initial"
    # Touches the manifest WITHOUT moving the version — must not count as a bump.
    write_manifest "$repo" 1.0.0 '{"name": "doobidoo", "url": "https://example.com"}'
    git add -A && git commit -q -m "fix(plugin): author field shape"
  )
  echo "$repo"
}

write_manifest() {
  local repo="$1" version="$2" author="$3"
  cat > "$repo/claude-hooks/.claude-plugin/plugin.json" <<EOF
{
  "name": "mcp-memory-service",
  "version": "$version",
  "author": $author,
  "hooks": "./.claude-plugin/hooks.json"
}
EOF
}

commit_hook_change() {
  local repo="$1" marker="$2"
  (
    cd "$repo"
    echo "// $marker" >> claude-hooks/core/hook.js
    git add -A && git commit -q -m "fix(hooks): $marker"
  )
}

commit_service_release() {
  local repo="$1" version="$2"
  (
    cd "$repo"
    echo "__version__ = \"$version\"" > src/mcp_memory_service/_version.py
    git add -A && git commit -q -m "chore: release v$version"
  )
}

# The base ref for the script is the commit the release branch started from,
# which for these fixtures is always "the commit before the release commit".
run_script() {
  local repo="$1" base="$2"
  (cd "$repo" && env MCS_PLUGIN_BASE_REF="$base" bash "$SCRIPT" 2>&1)
}

# --- Test: release PR with hook changes and no plugin bump fails ---
test_release_with_unbumped_hooks_fails() {
  local repo output status
  repo=$(make_fixture_repo unbumped)
  commit_hook_change "$repo" "send canonical memory types"
  commit_service_release "$repo" "11.6.0"
  output=$(run_script "$repo" "HEAD~2") && status=0 || status=$?
  [ "$status" -eq 1 ] \
    && echo "$output" | grep -q "send canonical memory types" \
    && echo "$output" | grep -q "1.0.0"
}

# --- Test: release PR that bumps the plugin manifest too passes ---
test_release_with_bumped_plugin_passes() {
  local repo output status
  repo=$(make_fixture_repo bumped)
  commit_hook_change "$repo" "send canonical memory types"
  write_manifest "$repo" 1.0.1 '{"name": "doobidoo", "url": "https://example.com"}'
  (cd "$repo" && git add -A && git commit -q -m "chore(plugin): bump to 1.0.1")
  commit_service_release "$repo" "11.6.0"
  output=$(run_script "$repo" "HEAD~3") && status=0 || status=$?
  [ "$status" -eq 0 ]
}

# --- Test: release PR with no hook changes at all passes ---
test_release_without_hook_changes_passes() {
  local repo output status
  repo=$(make_fixture_repo nohooks)
  commit_service_release "$repo" "11.6.0"
  output=$(run_script "$repo" "HEAD~1") && status=0 || status=$?
  [ "$status" -eq 0 ] && echo "$output" | grep -q "no claude-hooks/ changes"
}

# --- Test: a manifest touch that does not move the version is not a bump ---
# The fixture's second commit edits plugin.json's author field. A hook change
# BEFORE that commit must still be flagged: anchoring on "last commit that
# touched the file" would hide it (the v11.6.0 miss, issue #170).
test_manifest_touch_is_not_a_bump() {
  local repo output status
  repo=$(make_fixture_repo touchonly)
  # Rewrite history so the hook change lands between the two initial commits:
  # easier to just add another author-only touch after a hook change.
  commit_hook_change "$repo" "hook fix before an author-only edit"
  write_manifest "$repo" 1.0.0 '{"name": "doobidoo", "email": "x@example.com"}'
  (cd "$repo" && git add -A && git commit -q -m "chore(plugin): author email")
  commit_service_release "$repo" "11.6.0"
  output=$(run_script "$repo" "HEAD~3") && status=0 || status=$?
  [ "$status" -eq 1 ] && echo "$output" | grep -q "hook fix before an author-only edit"
}

# --- Test: non-release PR is skipped, and says so ---
test_non_release_pr_skips() {
  local repo output status
  repo=$(make_fixture_repo nonrelease)
  commit_hook_change "$repo" "hooks change on a feature branch"
  output=$(run_script "$repo" "HEAD~1") && status=0 || status=$?
  [ "$status" -eq 0 ] && echo "$output" | grep -qi "not a release"
}

# --- Test: shallow clone fails loudly instead of passing ---
test_shallow_clone_fails() {
  local repo shallow output status
  repo=$(make_fixture_repo shallowsrc)
  commit_hook_change "$repo" "hook fix"
  commit_service_release "$repo" "11.6.0"
  shallow="$TMPDIR_LOCAL/shallowclone"
  git clone -q --depth 1 "file://$repo" "$shallow"
  output=$(cd "$shallow" && env MCS_PLUGIN_BASE_REF="HEAD" bash "$SCRIPT" 2>&1) \
    && status=0 || status=$?
  [ "$status" -eq 1 ] && echo "$output" | grep -qi "shallow"
}

# --- Test: missing manifest is reported, not silently passed ---
test_missing_manifest_fails() {
  local repo output status
  repo=$(make_fixture_repo nomanifest)
  (
    cd "$repo"
    git rm -q -r claude-hooks/.claude-plugin
    git commit -q -m "chore: drop the manifest"
  )
  commit_service_release "$repo" "11.6.0"
  output=$(run_script "$repo" "HEAD~2") && status=0 || status=$?
  [ "$status" -eq 1 ] && echo "$output" | grep -qi "not found"
}

run_test "release PR with unbumped hook changes fails"        test_release_with_unbumped_hooks_fails
run_test "release PR that bumps the plugin passes"            test_release_with_bumped_plugin_passes
run_test "release PR without hook changes passes"             test_release_without_hook_changes_passes
run_test "manifest touch without a version move is no bump"   test_manifest_touch_is_not_a_bump
run_test "non-release PR is skipped explicitly"               test_non_release_pr_skips
run_test "shallow clone fails loudly"                         test_shallow_clone_fails
run_test "missing manifest is reported"                       test_missing_manifest_fails

rm -rf "$TMPDIR_LOCAL"

echo ""
echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
