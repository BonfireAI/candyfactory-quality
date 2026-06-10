# SHA-pin doctrine

1. Every cross-repo workflow/action ref is pinned to a full commit SHA (40-hex) — never `@main`, never a tag (tags move; SHAs do not).
2. The caller stub pins `quality-gate.yml@<full SHA>`; the gate checks the kit out at `github.job_workflow_sha`, so gauge scripts and workflow are always the same commit.
3. Org Actions policy enforces full-SHA pinning, so an unpinned ref cannot even be merged.
4. Dependabot (`github-actions` ecosystem, weekly) owns pin freshness: it opens pin-bump PRs in every consumer repo, so the pinned gauge cannot rot.
5. A pin-bump PR is reviewed and merged by Anta like any change — the bump itself runs through the gate it bumps.
6. The kit's own action pins (`actions/checkout`, `actions/setup-python`) follow the same rule, with the human-readable tag kept in a trailing comment.
7. Constable's weekly sweep audits for unpinned (`@main`/`@branch`/tag) cross-repo refs estate-wide; any hit is a finding.
8. Emergency rollback = re-pin to the last good SHA — one-line PR, no force-push, history stays sacred.
