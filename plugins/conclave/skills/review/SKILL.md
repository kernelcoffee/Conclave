---
name: review
description: Review the uncommitted diff (or the diff against a ref) with the Conclave reviewer lenses and refute every finding. Reports confirmed findings by severity with file and line; changes nothing. Use before committing, or on a branch before opening a PR.
argument-hint: "[base-ref] [--lenses correctness,security,stack,conventions,ux]"
user-invocable: true
---
Review the working tree with the Conclave lenses and the refuter. Write nothing.

Arguments: `$ARGUMENTS`.

## Steps

1. Read `.claude/conclave.json`. If it is missing, run the `conclave:init` skill first.
2. Parse the arguments: a bare token is the base ref (default `profile.base`); `--lenses a,b,c` replaces the default lens list. Default lenses: `correctness`, `security`, `stack`; add `conventions` when any touched component lists `conventions` or CLAUDE.md has a conventions section; add `ux` when a touched component has `ui: true`. (This is the lead's rule.)
3. Run `git diff --stat <base>` and `git status --short`. If both are empty, say there is nothing to review and stop. Map the changed files onto the profile's component `paths` to get `components`.
4. Say in one line what this spends: one opus agent per lens (`stack` counts once per distinct stack among the touched components) plus one refuter per finding. Then launch:

```
Workflow({ name: "conclave:review", args: { profile: <profile object>, exec: { base: <ref>, lenses: <list>, components: <names>, refute_votes_high: 1, plugin_root: "${CLAUDE_PLUGIN_ROOT}" } } })
```

If the name is not registered, launch with `scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/review.js"` and the same args.

5. Present the result:
   - Confirmed findings grouped `high`, `medium`, `low`; each as `file:line` then the summary, the failure scenario, and the suggested fix when there is one.
   - Refuted findings as one line each: `file:line summary — refuted: reason`.
   - The agent count actually used.
6. Do not fix anything. If the user wants fixes, point them at `/conclave <describe the fix>`.
