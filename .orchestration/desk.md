# Desk and environment facts -- pointer, not a copy

Source of truth: `project-notes\tasks\desk-environment.md` in the sibling private
ops-log repo `CarlitosRed/project-notes` (not this repo). Read it there directly.

Not duplicated here on purpose: that file is live and actively edited every
session (interpreter paths, PostgreSQL binary location, port conventions,
known flakes, shell gotchas), and a second copy here would drift the first
time either one changed without the other. A pointer stays correct forever;
a copy goes stale the next edit.

This is a structural gap in the adapter spec worth flagging to the Framework
Orchestrator: `adapters/README.md` assumes a project's `.orchestration/` folder
and its ops log live in the same repo. This project's ops log (decisions,
leaks, desk facts, task queue, audits, drafts) has lived in a separate private
repo since before the framework existed, by the Program Owner's own design (see
`project-notes\CONTEXT-RULES.md` and `agent-orchestration\docs\framework-map.md`
row 1, "Existing private project-notes repo stays as the PM's operations
log"). Retrofitting doesn't change that design decision; it just means this
file is a cross-repo pointer instead of an in-repo one.
