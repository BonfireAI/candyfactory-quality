#!/usr/bin/env bash
# Mount the quality gate as a REQUIRED, non-bypassable status check on a consumer
# repo's default branch — the apply-side companion to check-required-mount.sh
# (which audits) and to the in-band self-verifying canary in quality-gate.yml
# (which refuses to pass when this has not been done).
#
# The API trap (docs/enforcement-runbook.md): a PATCH 404s on an unprotected
# branch, so the FIRST mount must be a full PUT of the protection object. This
# script always PUTs the complete object, so it is idempotent — re-running it
# re-asserts the same required-check + enforce_admins state.
#
# Dependency-free: `gh api` only (needs a token with administration:write, e.g.
# an admin `gh auth login`). See check-required-mount.sh for the audit.
#
# Usage: mount-required.sh OWNER/REPO [branch] [context]
#   branch  defaults to: main
#   context defaults to: gate / gate
#
# Exit: 0 mounted (and verified) · 1 mount/verify failed · 2 usage error
set -euo pipefail

repo="${1:?usage: mount-required.sh OWNER/REPO [branch] [context]}"
branch="${2:-main}"
context="${3:-gate / gate}"

# strict:true also forces the PR to be up to date with base before merge, so the
# required run is always against the current base — belt-and-suspenders with the
# workflow's own merged-main projection.
gh api -X PUT "repos/${repo}/branches/${branch}/protection" \
  --input - <<JSON
{
  "required_status_checks": { "strict": true, "contexts": ["${context}"] },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON

echo "mounted '${context}' as a required, non-bypassable check on ${repo}@${branch}"
# Prove it took, with the same audit the in-band canary runs.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${here}/check-required-mount.sh" "$repo" "$branch" "$context"
