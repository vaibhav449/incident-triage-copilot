---
description: Run checks, review the diff for stray files and secrets, commit, push the branch, and print a PR description
argument-hint: [optional note about what this change is for]
disable-model-invocation: true
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git branch:*), Bash(git rev-parse:*), Bash(git remote:*), Bash(git fetch:*), Bash(git rev-list:*), Bash(git add:*), Bash(git commit:*), Bash(make check:*), Bash(uv run ruff:*), Bash(uv run pytest:*), Bash(docker compose build:*)
---

Ship the current branch. Extra context from the user: $ARGUMENTS

Stop at any red flag and ask. It is fine to ship nothing.

## 1. Guard

- Get the branch with `git branch --show-current`.
  - If it is `main`, or HEAD is detached: **stop**. Tell the user to move their work onto a branch with `git switch -c <type>/<short-name>`. Uncommitted changes carry over to the new branch.
- If the name doesn't match `<type>/<short-name>` (see `CLAUDE.md`), point it out. Continue only if the user agrees.

## 2. Checks (must pass)

- If the `Makefile` has a `check` target, run `make check`. Otherwise, if `pyproject.toml` exists, run:
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run pytest -q`
- If the branch changes a `Dockerfile` or `docker-compose.yml`, also run `docker compose build`.
- If none of this exists yet, say "no checks configured yet" and continue.
- If a check fails:
  - Fix it only if the failure is in a file this branch changed.
  - If it is in a file the branch didn't touch, report it and **stop**. Never reformat or refactor unrelated files to make checks pass.
- Re-run until green, or stop and report.

## 3. Review the change

- Run `git fetch origin`, then look at:
  - `git status --porcelain`
  - `git diff --stat origin/main...HEAD`
  - `git diff` and `git diff --staged` for uncommitted work
- Read the actual diff, not just file names. List every changed file with a one-line reason. **Stop and ask** before staging if you find any of these:
  - **Unrelated files:** files that don't belong to this task, including formatting-only or whitespace-only changes.
  - **Secrets:**
    - `.env` or any `.env.*` other than `.env.example`
    - private keys (`-----BEGIN`)
    - tokens or API keys (long random strings next to `key`, `token`, `secret`, `password`)
    - real credentials in config, tests or notebooks
  - **Generated or large files:**
    - anything under `artifacts/` or `runs/` (unless the user deliberately force-added a run)
    - scenario logs, `*.log.zst`, `*.faiss`, model weights
    - files over ~1 MB
  - **Lockfile changes:** `uv.lock` changed while `pyproject.toml` dependencies didn't. Ask whether a dependency was intentionally added; if not, restore it with `git checkout origin/main -- uv.lock`.
  - **Contract changes:** a change to `triage/schemas.py` is a contract change. It needs the `contract-change` PR label, approval from all three members, and a bump to `SCHEMA_VERSION`. Confirm the user knows.
  - **Ownership:** files in a teammate's area (see the ownership table in `CLAUDE.md`). Flag them so the PR description mentions them.
  - **Leftovers:** debug prints, commented-out blocks, notebook outputs, TODOs added by this change.
- If `origin/main` has commits the branch doesn't (`git rev-list --count HEAD..origin/main` > 0), recommend running `/sync` before pushing, and ask whether to continue.

## 4. Stage and commit

- Stage **by explicit path only**: `git add path/one path/two`. Never `git add -A` or `git add .`.
- Commit with a Conventional Commit message:
  - Subject: `<type>(<optional scope>): <imperative summary>`, at most 72 chars, lowercase type. The scope is the module folder when obvious, e.g. `feat(reduce): add early-onset score`.
  - Optional body (wrapped at 72 chars): *why* the change was made, plus any follow-ups.
- One commit is fine. Don't amend or rewrite commits that are already pushed.

## 5. Push

- Run `git push -u origin <branch>`. The user will see a permission prompt; that is the confirmation step.
- **Never** push to `main`. **Never** use `--force`.
- If the push is rejected because the remote branch moved, run `/sync` instead of forcing. After a `/sync` that rebased an already-pushed branch, `git push --force-with-lease` is allowed **only** on this feature branch, and only with explicit confirmation.

## 6. Output a PR description

Print this, ready to paste, and nothing else long:

```
Title: <conventional commit subject>

## What
- <1–3 bullets>

## Why
<1–2 sentences; link the gate / handoff (e.g. H6) from docs/02 if relevant>

## How tested
- `make check` → <pass/fail summary>
- <any manual check>

## Notes for reviewer
- Area: <owner area>; touches teammate files: <none | list>
- Contract change (schemas.py): <no | yes — needs all 3 approvals>
- New deps / env vars: <none | list — teammates run `uv sync` / update .env>
- Suggested reviewer: <from CLAUDE.md ownership table>
```

Then give the compare link `https://github.com/<owner>/<repo>/compare/main...<branch>?expand=1`, built from `git remote get-url origin`. If `gh` is installed, also print the `gh pr create --base main --title "…" --body-file -` command. Don't run it unless the user asks.
