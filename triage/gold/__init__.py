"""Ground-truth tooling (owner: Member 1): load gold labels, and later `triage gold label`.

Besides `triage/eval/`, this is the ONLY package allowed to read the `gold:` block of
scenario.yaml or to connect as `triage_eval` (CLAUDE.md invariant 3). Pipeline packages must
never import from here.
"""
