#!/bin/bash
#
# Claude Code Plugin Manifest Bump Check
#
# The Claude Code plugin in claude-hooks/ carries its own version in
# claude-hooks/.claude-plugin/plugin.json, decoupled from the service version.
# The Marketplace caches each plugin under a version-keyed directory, so an
# already-installed user only re-fetches the hooks when that version changes.
# A merged hook fix that ships without a manifest bump never reaches them.
#
# This gate runs on release PRs only (detected by src/mcp_memory_service/
# _version.py changing against the base ref) and fails when claude-hooks/ has
# changed since the last commit that moved the manifest version, unless the
# release also bumps the manifest.
#
# Background: v11.6.0 shipped the claim "no claude-hooks/ changes since its last
# bump" while commit 5d40d8e4 (fix(hooks): send memory types the server ontology
# accepts) sat inside the range. The manual check documented for the release
# workflow would have caught it; it was not run. Reported by @tecnobrat in #170.
#
# Env overrides (for tests):
#   MCS_PLUGIN_BASE_REF   base ref to compare against (default: origin/main)
#   MCS_PLUGIN_MANIFEST   manifest path
#   MCS_PLUGIN_HOOKS_DIR  hooks directory
#   MCS_VERSION_FILE      canonical service version file
#
# Exit codes:
#   0 - no bump needed, bump present, or not a release PR
#   1 - bump missing, or the check could not run reliably

set -uo pipefail

MANIFEST="${MCS_PLUGIN_MANIFEST:-claude-hooks/.claude-plugin/plugin.json}"
HOOKS_DIR="${MCS_PLUGIN_HOOKS_DIR:-claude-hooks}"
VERSION_FILE="${MCS_VERSION_FILE:-src/mcp_memory_service/_version.py}"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "FAIL: not a git repository - the plugin bump check needs history"
  exit 1
fi

# A shallow checkout cannot answer "changed since the last bump". Fail loudly
# rather than reporting a pass the history does not support.
if [ "$(git rev-parse --is-shallow-repository 2>/dev/null)" = "true" ]; then
  echo "FAIL: shallow clone - this check needs full history"
  echo "Fix: set 'fetch-depth: 0' on the checkout step for this job."
  exit 1
fi

if [ ! -f "$MANIFEST" ]; then
  echo "FAIL: plugin manifest not found: $MANIFEST"
  echo "If the Claude Code plugin was removed on purpose, drop this gate in the same change."
  exit 1
fi

# Resolve the base ref. On a Forgejo pull_request event GITHUB_BASE_REF holds the
# target branch name; locally and on push, origin/main is the sensible default.
resolve_ref() {
  for candidate in "$@"; do
    [ -n "$candidate" ] || continue
    if git rev-parse --verify --quiet "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

BASE_REF="${MCS_PLUGIN_BASE_REF:-}"
if [ -z "$BASE_REF" ]; then
  BASE_REF=$(resolve_ref "origin/${GITHUB_BASE_REF:-}" "${GITHUB_BASE_REF:-}" "origin/main" "main")
fi
if [ -z "$BASE_REF" ] || ! git rev-parse --verify --quiet "$BASE_REF" >/dev/null 2>&1; then
  echo "FAIL: could not resolve a base ref to compare against (tried origin/${GITHUB_BASE_REF:-}, origin/main)"
  echo "Fix: fetch the base branch, or set MCS_PLUGIN_BASE_REF."
  exit 1
fi

MERGE_BASE=$(git merge-base "$BASE_REF" HEAD 2>/dev/null)
if [ -z "$MERGE_BASE" ]; then
  echo "FAIL: no common ancestor between HEAD and $BASE_REF"
  exit 1
fi

# Release PRs are the enforcement point: hook fixes land in their own PRs
# throughout a cycle and are bumped once, together, when the release is cut.
if git diff --quiet "$MERGE_BASE" HEAD -- "$VERSION_FILE"; then
  echo "SKIP: not a release change ($VERSION_FILE unchanged vs $BASE_REF) - plugin bump not enforced here"
  exit 0
fi

# Window start: the last commit that moved the manifest's version LINE. Using
# "last commit that touched the file" is wrong - a commit that edits only the
# author or homepage field would move the window forward and hide every hook
# change before it.
LAST_BUMP=$(git log -1 --format=%H -G'"version"[[:space:]]*:' -- "$MANIFEST" 2>/dev/null)
if [ -z "$LAST_BUMP" ]; then
  echo "FAIL: could not find any commit that set the version in $MANIFEST"
  exit 1
fi

CURRENT_VERSION=$(grep -E '"version"[[:space:]]*:' "$MANIFEST" \
  | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')

# Verdict comes from the tree diff, not from git log: history simplification can
# omit commits from a log listing, but the diff between two trees cannot lie.
# The manifest itself is excluded - a metadata-only edit to it is not a hook
# change and does not need a version bump.
if git diff --quiet "$LAST_BUMP" HEAD -- "$HOOKS_DIR" ":(exclude)$MANIFEST"; then
  echo "PASS: no claude-hooks/ changes since the last plugin version bump (plugin $CURRENT_VERSION)"
  echo "      window: $(git log -1 --format='%h %s' "$LAST_BUMP")"
  exit 0
fi

echo "FAIL: claude-hooks/ changed since the last plugin version bump, but plugin.json still says $CURRENT_VERSION"
echo ""
echo "Last version bump: $(git log -1 --format='%h %s' "$LAST_BUMP")"
echo "Hook changes since then:"
git log "$LAST_BUMP"..HEAD --oneline -- "$HOOKS_DIR" ":(exclude)$MANIFEST" | sed 's/^/   /'
echo ""
echo "Files changed:"
git diff --name-only "$LAST_BUMP" HEAD -- "$HOOKS_DIR" ":(exclude)$MANIFEST" | sed 's/^/   /'
echo ""
echo "Fix: bump \"version\" in $MANIFEST (PATCH for hook fixes, MINOR for new hook"
echo "features) in this release commit. The Marketplace cache is version-keyed, so"
echo "without the bump installed users keep running the old hooks."
exit 1
