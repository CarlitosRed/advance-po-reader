# Leak log -- pointer, not a copy

Source of truth: `project-notes\tasks\process-leaks.md` in the sibling private
ops-log repo `CarlitosRed/project-notes` (not this repo). Read and append there.

Not moved here on purpose: it is the project's single active leak log (L1
through L55 and counting as of this retrofit, 2026-10-15), cross-referenced by
exact path from `project-notes\CONTEXT-RULES.md` rule 15, from every audit
report in `project-notes\audits\`, and from this Orchestrator's own standing
sweep habit. Moving it would break every one of those references at once for
no benefit; a pointer costs nothing and breaks nothing.

Same cross-repo structural note as `desk.md` in this folder: the adapter spec
assumes one repo per project, this project splits product code (here) from
its ops log (`project-notes`) by the Program Owner's own long-standing design.
