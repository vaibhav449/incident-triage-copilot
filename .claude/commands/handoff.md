---
description: Generate a 5-line status update for the team group chat
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git branch:*), Bash(git rev-parse:*), Bash(git fetch:*), Bash(git config user.name), Bash(gh pr view:*)
---

Write a short handoff for the team group chat about the current branch. Extra context from the user: $ARGUMENTS

## Gather (read-only — change nothing)

- Branch: `git branch --show-current`. Author: `git config user.name`.
- Run `git fetch origin`, then:
  - `git log --oneline origin/main..HEAD` (commits on this branch)
  - `git diff --stat origin/main...HEAD` (files changed)
  - `git status --porcelain` (uncommitted work — mention it if present)
- PR link: `gh pr view --json url -q .url` if `gh` is installed; otherwise "PR not opened yet".
- Setup impact. Check whether the branch diff touches:
  - `pyproject.toml` / `uv.lock` → teammates run `uv sync`; name the added packages
  - `.env.example` → list the new or renamed variable names (never values)
  - `docker-compose.yml` / a `Dockerfile` → `docker compose up -d --build`
  - DB schema or migrations → say what to rerun
  - `triage/schemas.py` → **contract change**, needs all 3 approvals
  - files in a teammate's area (ownership table in `CLAUDE.md`) → name the owner

## Output

Exactly 5 lines in one plain-text code block, with no markdown inside so it pastes cleanly into WhatsApp or Discord. Keep each line under ~120 characters:

```
[<branch>] <author> · <n> commits · <PR link | PR not opened yet>
Changed: <one-sentence summary of what now works or what was fixed>
Files: <up to 5 key paths, then "+N more">
Setup: <"uv sync (added X)" / "new env: A, B" / "rebuild containers" — or "nothing to do">
Heads-up: <contract change / touches X's area / blocked on Y / needs review from Z — or "none">
```

Print only the code block, with nothing before or after it.
