---
description: Bring the latest origin/main into the current branch and resolve conflicts without losing anyone's work
disable-model-invocation: true
allowed-tools: Bash(git status:*), Bash(git fetch:*), Bash(git log:*), Bash(git diff:*), Bash(git branch:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git merge:*), Bash(git rebase:*), Bash(git pull --ff-only:*), Bash(git show:*), Bash(git add:*), Bash(make check:*), Bash(uv run ruff:*), Bash(uv run pytest:*)
---

Sync the current branch with the latest `origin/main`.

**Golden rule: every line a teammate wrote on `main` survives the sync.** When unsure, stop and ask rather than pick a side.

## 1. Guard

- Get the branch with `git branch --show-current`.
  - If it is `main`, run `git pull --ff-only origin main` and stop. If the fast-forward fails, explain why and do **not** reset.
- If `git status --porcelain` shows uncommitted changes, **stop** and ask which option to take:
  - (a) commit them first with `/ship`, or a local WIP commit (`git commit -m "chore: wip"`)
  - (b) stash them with `git stash push -u -m "sync wip"`, popping the stash after the sync
  - (c) cancel

## 2. See what's new

- Run `git fetch origin`.
- Run `git log --oneline HEAD..origin/main`. If it's empty, say "already up to date" and stop.
- Show the incoming commits, and flag any that touch the same files as this branch. Compare `git diff --name-only origin/main...HEAD` with `git diff --name-only HEAD...origin/main`.

## 3. Choose the strategy

Check whether the branch has been pushed: `git rev-parse --abbrev-ref @{u}`.

- **Never pushed** (no upstream): `git rebase origin/main`. This gives a clean history and needs no force-push later.
- **Already pushed**: `git merge --no-edit origin/main`. This rewrites no history, so no force-push is needed and teammates who pulled the branch aren't broken.

## 4. Resolve conflicts (if any)

For each conflicted file (`git diff --name-only --diff-filter=U`):

1. Show both sides, and explain what `main` changed and why: `git log --oneline origin/main -- <file>`, plus the relevant commit messages. Then explain what this branch changed.
2. Write a resolution that **keeps both intents**. Never resolve by taking one side for a whole file (`--ours` / `--theirs`), and never delete a teammate's code to make the conflict go away.
   - During a **rebase**, "ours" means `main` and "theirs" means *your* commit. That is the reverse of a merge, so don't use those flags blindly.
3. **Stop and ask the user** instead of guessing if:
   - the file is in a teammate's area,
   - the file is `triage/schemas.py`, or
   - you can't tell what one side intended.

   In those cases, suggest messaging the file's owner (see the ownership table in `CLAUDE.md`).
4. Special cases:
   - **`uv.lock`:** never hand-merge it. Run `git checkout origin/main -- uv.lock`, then `uv lock` to re-resolve with this branch's `pyproject.toml`, then stage it.
   - **Generated files** (`artifacts/`, `runs/`): they shouldn't be tracked; flag them.
5. Stage each resolved file by path (`git add <file>`), then `git rebase --continue` or `git merge --continue`.

You can bail out at any point with `git rebase --abort` or `git merge --abort`. This restores the branch exactly as it was; offer it if things get messy.

## 5. Verify

Run the checks: `make check`, or `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest -q` if there's no Makefile yet. If something now fails because of the combination of both sides, fix it in this branch and explain the fix.

## 6. Report (≤ 6 lines)

- Commits brought in (count and one-line gist), and the strategy used (rebase or merge).
- Conflicts: file → how resolved, or "none".
- Check result.
- Next step:
  - After a merge: a normal `git push`.
  - After a rebase of a never-pushed branch: a normal `git push -u origin <branch>` when ready.
  - If any new commits changed `pyproject.toml`/`uv.lock`, `.env.example` or `docker-compose.yml`: tell the user to run `uv sync`, update `.env`, or rebuild containers.
