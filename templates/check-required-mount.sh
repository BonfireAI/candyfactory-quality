#!/usr/bin/env bash
# Audit whether the quality gate is a REQUIRED, non-bypassable status check on a
# consumer repo's default branch. Reports whether a RED verdict can still merge.
#
# Dependency-free: `gh api` + `jq` only. See docs/enforcement-runbook.md for the
# mount procedure this script audits, and for why the context name is exactly
# `gate / gate` (caller job `gate` over the reusable workflow's `gate` job).
#
# Usage: check-required-mount.sh OWNER/REPO [branch] [context]
#   branch  defaults to: main
#   context defaults to: gate / gate
#
# Exit: 0 PASS (required AND non-bypassable) · 1 FAIL · 2 usage/lookup error
set -euo pipefail

repo="${1:?usage: check-required-mount.sh OWNER/REPO [branch] [context]}"
branch="${2:-main}"
context="${3:-gate / gate}"

# A branch with NO protection at all returns 404 here — that is itself a FAIL
# (an unprotected default branch cannot require any check).
if ! prot="$(gh api "repos/${repo}/branches/${branch}/protection" 2>/dev/null)"; then
  echo "FAIL: no branch protection on ${repo}@${branch} (or no access) —" \
       "the gate cannot be required" >&2
  exit 1
fi

has_check="$(jq --arg c "$context" \
  '[.required_status_checks.contexts[]? | select(. == $c)] | length > 0' \
  <<<"$prot")"
admins="$(jq '.enforce_admins.enabled // false' <<<"$prot")"
strict="$(jq '.required_status_checks.strict // false' <<<"$prot")"

echo "repo:            ${repo}"
echo "branch:          ${branch}"
echo "context:         ${context}"
echo "required check:  ${has_check}"
echo "enforce_admins:  ${admins}   (non-bypassable)"
echo "strict:          ${strict}"

if [ "$has_check" = "true" ] && [ "$admins" = "true" ]; then
  echo "PASS: '${context}' is required AND non-bypassable on ${repo}@${branch}"
  exit 0
fi

echo "FAIL: a red verdict can still merge on ${repo}@${branch}" \
     "(required=${has_check}, enforce_admins=${admins})"
exit 1
