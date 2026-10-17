#!/usr/bin/env bash
# Test harness for .claude/hooks/worktree_guard.sh
# Uses plain bash (bats not available; install via: brew install bats-core)
# Each test is a function; run_test tracks pass/fail counts.
#
# Tests are self-contained: each one builds a throwaway git repo with a fake
# "origin" in $TMPDIR_LOCAL and runs the hook inside it. Nothing touches the
# real repository, so a failing test can never delete a real branch.
#
# The subject under test deletes branches, so the cases that matter most are
# the ones asserting what gc must NOT remove.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$REPO_ROOT/.claude/hooks/worktree_guard.sh"
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

# Build a repo with an origin remote and one commit on main.
# Echoes the path of the working clone.
make_repo() {
  local name="$1"
  local origin="$TMPDIR_LOCAL/$name-origin"
  local work="$TMPDIR_LOCAL/$name"
  git init -q --bare "$origin"
  git init -q -b main "$work"
  git -C "$work" config user.email t@example.com
  git -C "$work" config user.name Test
  git -C "$work" config commit.gpgsign false
  echo seed > "$work/seed.txt"
  git -C "$work" add seed.txt
  git -C "$work" commit -qm seed
  git -C "$work" remote add origin "$origin"
  git -C "$work" push -q origin main
  echo "$work"
}

# --- Test: gc removes a wt/* branch that is merged and backs no worktree ---
test_gc_removes_orphan_merged_branch() {
  local work; work="$(make_repo gc-orphan)"
  git -C "$work" branch wt/990101-000000 main
  ( cd "$work" && bash "$SCRIPT" gc >/dev/null 2>&1 )
  ! git -C "$work" rev-parse --verify --quiet wt/990101-000000 >/dev/null
}

# --- Test: gc keeps a wt/* branch that is NOT merged ---
test_gc_keeps_unmerged_branch() {
  local work; work="$(make_repo gc-unmerged)"
  git -C "$work" checkout -q -b wt/990101-111111
  echo extra > "$work/extra.txt"
  git -C "$work" add extra.txt
  git -C "$work" commit -qm extra
  git -C "$work" checkout -q main
  ( cd "$work" && bash "$SCRIPT" gc >/dev/null 2>&1 )
  git -C "$work" rev-parse --verify --quiet wt/990101-111111 >/dev/null
}

# --- Test: gc keeps a merged wt/* branch that still backs a worktree ---
test_gc_keeps_branch_backing_live_worktree() {
  local work; work="$(make_repo gc-live)"
  git -C "$work" worktree add -q -b wt/990101-222222 "$TMPDIR_LOCAL/gc-live-wt" main
  ( cd "$work" && bash "$SCRIPT" gc >/dev/null 2>&1 )
  git -C "$work" rev-parse --verify --quiet wt/990101-222222 >/dev/null
}

# --- Test: gc never touches branches outside the wt/* namespace ---
test_gc_ignores_non_wt_branches() {
  local work; work="$(make_repo gc-nonwt)"
  git -C "$work" branch feature/keep-me main
  git -C "$work" branch release/v1.0.0 main
  ( cd "$work" && bash "$SCRIPT" gc >/dev/null 2>&1 )
  git -C "$work" rev-parse --verify --quiet feature/keep-me >/dev/null \
    && git -C "$work" rev-parse --verify --quiet release/v1.0.0 >/dev/null
}

# --- Test: gc is a no-op when origin/main is missing (no remote refs) ---
test_gc_survives_missing_base_ref() {
  local work="$TMPDIR_LOCAL/gc-nobase"
  git init -q -b main "$work"
  git -C "$work" config user.email t@example.com
  git -C "$work" config user.name Test
  git -C "$work" config commit.gpgsign false
  echo seed > "$work/seed.txt"
  git -C "$work" add seed.txt
  git -C "$work" commit -qm seed
  git -C "$work" branch wt/990101-333333 main
  local status
  ( cd "$work" && bash "$SCRIPT" gc >/dev/null 2>&1 ) && status=0 || status=$?
  # Must exit cleanly AND must not delete anything it cannot prove is merged.
  [ "$status" -eq 0 ] \
    && git -C "$work" rev-parse --verify --quiet wt/990101-333333 >/dev/null
}

# --- Test: prepare reuses an unused worktree instead of minting a new one ---
# This is the actual leak fix: three calls must yield one worktree, not three.
test_prepare_reuses_unused_worktree() {
  local work; work="$(make_repo prep-reuse)"
  local d1 d2 d3
  d1="$( cd "$work" && bash "$SCRIPT" prepare 2>/dev/null )"
  d2="$( cd "$work" && bash "$SCRIPT" prepare 2>/dev/null )"
  d3="$( cd "$work" && bash "$SCRIPT" prepare 2>/dev/null )"
  local n
  n="$(git -C "$work" for-each-ref --format='%(refname:short)' refs/heads/ | grep -c '^wt/' || true)"
  [ -n "$d1" ] && [ "$d1" = "$d2" ] && [ "$d2" = "$d3" ] && [ "$n" -eq 1 ]
}

# --- Test: prepare does NOT reuse a worktree that has uncommitted work ---
test_prepare_skips_dirty_worktree() {
  local work; work="$(make_repo prep-dirty)"
  local d1 d2
  d1="$( cd "$work" && bash "$SCRIPT" prepare 2>/dev/null )"
  echo "work in progress" > "$d1/seed.txt"
  d2="$( cd "$work" && bash "$SCRIPT" prepare 2>/dev/null )"
  [ -n "$d2" ] && [ "$d1" != "$d2" ]
}

# --- Test: gc is idempotent — a second run changes nothing ---
test_gc_is_idempotent() {
  local work; work="$(make_repo gc-idem)"
  git -C "$work" branch wt/990101-444444 main
  ( cd "$work" && bash "$SCRIPT" gc >/dev/null 2>&1 )
  local a b
  a="$(git -C "$work" for-each-ref refs/heads/ | wc -l | tr -d ' ')"
  ( cd "$work" && bash "$SCRIPT" gc >/dev/null 2>&1 )
  b="$(git -C "$work" for-each-ref refs/heads/ | wc -l | tr -d ' ')"
  [ "$a" = "$b" ]
}

echo "Testing $SCRIPT"
echo

run_test "gc removes an orphaned merged wt/* branch"        test_gc_removes_orphan_merged_branch
run_test "gc keeps an unmerged wt/* branch"                 test_gc_keeps_unmerged_branch
run_test "gc keeps a branch backing a live worktree"        test_gc_keeps_branch_backing_live_worktree
run_test "gc ignores branches outside wt/*"                 test_gc_ignores_non_wt_branches
run_test "gc survives a missing base ref"                   test_gc_survives_missing_base_ref
run_test "prepare reuses an unused worktree"                test_prepare_reuses_unused_worktree
run_test "prepare skips a dirty worktree"                   test_prepare_skips_dirty_worktree
run_test "gc is idempotent"                                 test_gc_is_idempotent

echo
echo "passed: $PASS  failed: $FAIL"
rm -rf "$TMPDIR_LOCAL"
[ "$FAIL" -eq 0 ]
