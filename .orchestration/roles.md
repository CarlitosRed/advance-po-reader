# Roles and tiers -- pointer, not a copy

Source of truth: `ROLES.md` at this repo's root. Read it there directly.

Not duplicated here on purpose: `ROLES.md` is itself one of this project's
`protected_paths` (see `.orchestration/gate.json` and `tools/gate/gate.json`)
-- any change to it is already Tier 3 and already goes through the heaviest
review this project has. A second copy in `.orchestration/roles.md` would be
an un-protected shadow of a protected file: it could drift silently (anyone
touching `.orchestration/roles.md` would not trip the Tier-3 rule that
`ROLES.md` itself triggers), which is a worse outcome than one extra click to
the real file.

Quick orientation only (not a substitute for reading `ROLES.md`):
- **The Program Owner** -- Technical Owner (human). Vetoes with `hold`. Approves Tier 3
  himself, in his own comment, never an agent.
- **Claudio / Claude** (Anthropic, branch prefix `claude/`) and **Codex / Chat**
  (OpenAI, branch prefixes `codex/`, `chat/`) fill the PM, reviewer and builder
  roles. One chat, one job; the author never reviews its own work.
- Four tiers: 1 (docs/README, no go, no approval), 2 (code/tests/config, plan
  go + one cross-vendor approval), 3 (protected paths -- money and trust --
  same as 2 plus the Program Owner's own typed approval), 4 (billing, spend, credentials,
  production, deletion -- humans only, never a pull request).
- Launch limits / usage ceilings for Claude helpers: not written down as a
  fixed number anywhere in `ROLES.md` itself at this retrofit's date; the
  working ceiling has moved by the Program Owner's verbal say-so several times this month
  (see `project-notes\advance-po-reader\decisions.md`, rows for 2026-10-08 and
  2026-10-13). **UNKNOWN: no single current-ceiling fact to point to** -- this
  is a real gap, not a guess avoided for form's sake. Whoever needs the current
  number should check the latest decisions.md row and `get_usage`, not this
  file.
