---
description: Start a task on a fresh, correctly named branch cut from the latest main
argument-hint: <type> <short description>   e.g. feat evidence pack builder
disable-model-invocation: true
allowed-tools: Bash(git status:*), Bash(git branch:*), Bash(git switch:*), Bash(git fetch:*), Bash(git pull --ff-only:*), Bash(git rev-parse:*), Bash(git remote:*), Bash(git ls-remote:*), Bash(git log:*)
---

Start a new task for: **$ARGUMENTS**

Follow these steps in order. Stop and ask whenever a step says so. Never discard anyone's work.

1. **Work out the branch name.**
   - Format: `<type>/<short-name>`.
   - `type` is one of `feat` `fix` `chore` `docs` `test` `refactor` `style`. If `$ARGUMENTS` doesn't start with one, infer it from the description and say which one you picked.
   - `short-name` is kebab-case, lowercase ASCII, at most 4 words, and has no member names. Example: `feat evidence pack builder` → `feat/evidence-pack-builder`.
   - If `$ARGUMENTS` is empty, ask what the task is and stop.

2. **Check the repo state.**
   - Run `git rev-parse --is-inside-work-tree` and `git remote get-url origin`. If either fails, explain what's missing (`git init` / `git remote add origin …`) and stop.
   - Run `git status --porcelain`. If anything is listed (modified, staged or untracked files), **stop**: show the files and ask which option to take:
     - (a) ship them first with `/ship`
     - (b) stash them with `git stash push -u -m "<current-branch> wip"`
     - (c) cancel
   - Never run `git reset --hard`, `git checkout -- .`, or `git clean`.

3. **Update `main`.**
   - Run `git switch main`, then `git pull --ff-only origin main`.
   - If the fast-forward fails, local `main` has commits that aren't on GitHub. **Stop** and explain. Never reset `main` without explicit confirmation.

4. **Make sure the name is free.**
   - Check `git branch --list <name>` and `git ls-remote --heads origin <name>`.
   - If the name is taken, propose a variant (e.g. add `-v2` or a more specific word) and ask.

5. **Create the branch:** `git switch -c <name>`.

6. **Check ownership.** Using the ownership table in `CLAUDE.md`, name the area and paths this task will most likely touch.
   - If that's a teammate's area, `triage/schemas.py`, or another shared file, warn now. Suggest messaging the owner before editing, so two people don't change the same files.
   - If the area also looks out of scope for the person you're working with (from `CLAUDE.local.md`, or ask), say so.

7. **Report** in at most 4 lines:
   - the branch name
   - the base commit (`git log -1 --format='%h %s'`)
   - the files or area you expect to touch
   - a reminder: "Run `/sync` daily; `/ship` when done."

Do not start writing code in this command unless the user asked for that too.
