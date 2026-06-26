# Enforcement runbook — mounting the gate as a REQUIRED, non-bypassable check

The gate is only a gate when a red verdict **blocks the merge**. A reusable
workflow cannot assert this about itself: required-status-check and
admin-enforcement settings are **consumer-repo branch protection**, outside any
workflow's reach (DESIGN §4.8). This is the procedure that closes that leg —
the one that, left undone, let a sister repo merge red **five times** while its
gate ran and reported failures into the void.

Everything below is **observed**, not guessed: it is the exact sequence used to
enforce the gate on a real consumer. Read it before you touch branch protection
— a wrong check name or a careless full `PUT` can lock a repo's default branch.

---

## 0. The one fact that breaks everything if wrong: the check name

The caller stub (`templates/quality.caller.yml`) calls the reusable workflow as
`jobs.gate.uses: …/quality-gate.yml@<sha>`. GitHub names a reusable-workflow
status-check context **`<caller job> / <reusable job>`** — here the caller job
is `gate` and the reusable workflow's job is also `gate`, so the context is:

```
gate / gate
```

**This must be exact.** A required check whose name no run ever produces is
"Expected" forever — it never turns green, and it blocks **every** merge on the
branch (the failure mode is indistinguishable from a hung CI). Before you mount
anything, confirm the context name from a recent real run on the consumer:

```bash
# list every check-run name produced by a known-good commit on the branch
gh api repos/OWNER/REPO/commits/<sha>/check-runs \
  --jq '.check_runs[].name'
```

Use the SHA of a recent head commit on the default branch (or any commit that
ran the gate). Confirm `gate / gate` appears verbatim. If the caller job was
renamed in a given consumer, the context changes with it — trust the run, then
the docs.

---

## 1. `enforce_admins: true` — the difference between required and non-bypassable

A required check stops a normal merge. It does **not** stop an admin: by default
a repo admin can merge through a red required check. Non-bypassable means
`enforce_admins.enabled == true` — even admins are held to the gate.

- If `enforce_admins` is **already true** on the branch, adding `gate / gate` to
  the required contexts makes it non-bypassable **automatically** — no extra
  step.
- If it is not, you set it in the same protection write below.

There is no partial non-bypassable: it is a single branch-wide boolean.

---

## 2. The API trap: PATCH 404 on a branch with no required checks

The narrow endpoint —

```bash
gh api -X PATCH repos/OWNER/REPO/branches/main/protection/required_status_checks …
```

— returns **404 "Required status checks not enabled"** when the branch has no
`required_status_checks` block yet. You cannot PATCH a sub-resource into
existence. The first time you add a required check you MUST use the **full**
branch-protection write:

```bash
gh api -X PUT repos/OWNER/REPO/branches/main/protection …
```

### ⚠️ A full PUT REPLACES all protection — reproduce every field

`PUT …/branches/<branch>/protection` is not a merge; it **overwrites the entire
protection object**. Any field you omit is **dropped** — silently turning off
`enforce_admins`, review requirements, conversation-resolution, force-push and
deletion guards. **First GET the current protection, then reproduce every field
faithfully** and add only the required-checks block.

**Step 2a — capture current protection:**

```bash
gh api repos/OWNER/REPO/branches/main/protection > protection.current.json
```

Read it. Note every field that is set — typically at least:
`enforce_admins`, `required_pull_request_reviews`,
`required_conversation_resolution`, `allow_force_pushes`, `allow_deletions`,
`required_linear_history`, `block_creations`, `restrictions`.

**Step 2b — author the new protection body** (`protection.json`), reproducing
the captured settings and adding the required checks. A typical non-org
(user-owned) repo body — `restrictions` MUST be `null` for non-org repos
(push restrictions are an org-only feature; a non-null value 422s):

```json
{
  "required_status_checks": {
    "strict": false,
    "contexts": ["gate / gate"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "required_conversation_resolution": true,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
```

Substitute the values you captured in 2a — do not paste this verbatim if the
branch already required reviews or linear history. **Omission is deletion.**

**Step 2c — write it:**

```bash
gh api -X PUT repos/OWNER/REPO/branches/main/protection \
  --input protection.json
```

The response echoes the resulting protection — diff it against
`protection.current.json` plus your intended change to confirm nothing was lost.

Once the block exists, later edits to the contexts list MAY use the narrow
`PATCH …/required_status_checks` endpoint (it no longer 404s). The full-PUT
caution above applies only to the protection root, never to the narrow endpoint.

### `strict` — the up-to-date knob

- `"strict": false` (recommended default) — the gate must be green; the PR need
  not be rebuilt against the latest base. Low friction; the gate still ran on
  the merged code because `pull_request` re-runs the gate on the merge ref.
- `"strict": true` (stricter) — also requires the branch be up to date with base
  before merge, forcing a re-run on stale PRs. Use where base churn is high and
  you want every merge gated against the exact current base; it costs rebuilds.

---

## 3. The canary — does enforcement actually hold?

Mounting is procedure; a canary makes it **auditable**. The script below reports,
for a given `OWNER/REPO/branch`, whether the gate context is in the required set
and whether the gate is non-bypassable — a clear PASS/FAIL. It is dependency-free
(`gh api` + `jq`). The standalone copy is `templates/check-required-mount.sh`
(same logic); inline copy for quick use:

```bash
#!/usr/bin/env bash
# Audit whether the quality gate is a REQUIRED, non-bypassable check.
# Usage: check-required-mount.sh OWNER/REPO [branch] [context]
set -euo pipefail

repo="${1:?usage: OWNER/REPO [branch] [context]}"
branch="${2:-main}"
context="${3:-gate / gate}"

prot="$(gh api "repos/${repo}/branches/${branch}/protection")"

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
```

Standalone invocation:

```bash
bash templates/check-required-mount.sh OWNER/REPO main "gate / gate"
```

Run it after mounting (expect PASS), and on Constable cadence across the fleet
(any FAIL is a finding — a repo whose gate runs but does not block).

### The behavioral canary (proves a red verdict actually blocks)

The audit above reads settings; to prove the wiring end to end, run the
**deliberately-failing mount canary** once per newly-enforced repo: push a commit
that fails the gate on a throwaway PR, confirm the run goes red AND the PR is
**unmergeable** (the merge button blocked on `gate / gate`), record the run URL,
then delete the branch. Settings can be correct while the name is subtly wrong —
the behavioral canary is the only proof that a red verdict cannot land.

### The in-band self-verifying canary (mechanism, not just procedure)

The audit above is out-of-band (Constable cadence). The gate now **also verifies
its own mount from inside every run**: `quality-gate.yml` runs
`check-required-mount.sh` against the calling repo and **refuses to pass** when
the gate is not a required, non-bypassable check — a gate that cannot prove it is
the law is treated as unmounted. This is the Elegance Law's e2e on the gate
itself; it closes the in-band leg of what DESIGN §4.8 listed as PARTIAL.

It needs `administration: read`, so the caller stub grants it
(`permissions: { contents: read, administration: read }`). A token that cannot
read protection fails the canary with that remedy — never a silent pass.

**The bootstrap order matters:** mount the protection FIRST (an admin action,
out-of-band), then the gate goes green. The one-shot apply is:

```bash
bash templates/mount-required.sh OWNER/REPO          # full PUT + proves it via the audit
```

`mount-required.sh` always PUTs the complete protection object (the §2 trap:
PATCH 404s on an unprotected branch), sets `enforce_admins: true` and
`strict: true`, and then re-runs `check-required-mount.sh` to prove the mount.

---

## 4. Checklist

1. Confirm the context name from a recent run (`§0`) — `gate / gate` verbatim.
2. GET current protection; save it (`§2a`).
3. Author the full PUT body reproducing every captured field + the required
   checks block + `enforce_admins: true` (`§2b`); `restrictions: null` for
   non-org repos. (Or run `templates/mount-required.sh OWNER/REPO`.)
4. PUT it; diff the echo against the saved copy (`§2c`).
5. Run the canary audit — expect PASS (`§3`).
6. Run the behavioral canary once — red verdict must be unmergeable (`§3`).
7. Grant the caller `administration: read` so the in-band canary self-verifies
   the mount on every run (`§3`).
