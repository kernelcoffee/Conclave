---
name: release
description: Prepare a release with the Conclave devops role. Bumps the version files the profile lists together, drafts the changelog entry from git history, checks the CI config, runs every component's checks, then proposes the release commit and tag. Never commits or tags without approval.
argument-hint: <version>
user-invocable: true
---
Prepare release `$ARGUMENTS` (a version such as `1.4.0`; if empty, ask for it in one line and stop).

## Steps

1. Read `.claude/conclave.json`. If it is missing, run the `conclave:init` skill first. If `devops.release` is empty, say which files you think hold the version and stop so the user can add them to the profile.
2. Find the previous tag with `git describe --tags --abbrev=0` (if none, use the first commit). Run `git status --short`; a dirty tree is a reason to stop and say so, unless the user says to continue.
3. Say in one line that this spends one opus agent (devops). Spawn `conclave:devops` as a subagent with:
   - the project name, base ref and the `devops` block from the profile as JSON;
   - the version and the previous tag;
   - the instruction: bump the version in every file under `devops.release` together, keeping each file's own format; draft the changelog entry (in `CHANGELOG.md` if it exists, else return the text) from `git log <previous-tag>..HEAD --no-merges` grouped by conventional-commit type, in the file's existing voice; check the CI definition at `devops.ci` still references the pinned toolchain versions consistently with the container files; run every component's `checks` from the profile and report the tail of any failure; never commit, tag or push.
4. Show the devops report, then `git diff --stat` and the changelog entry.
5. Propose the release commit message per `profile.git` (conventional: `chore(release): v<version>`), the tag `v<version>`, and the exact `git commit` and `git tag` commands. Wait for approval; run them only when the user says so, and never push.
