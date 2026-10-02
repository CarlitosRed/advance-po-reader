# Project context

Read `PROJECT_GOAL.md` before changing this project. It is the working goal and reflects the October 1, 2026 user instruction. The attached research framework is retained under `docs/research/`.

Current phase: self-hosted pretrained VLM extraction, catalog candidate infrastructure, selective LLM adjudication, PDF evaluation and human-review collection. Training and fine-tuning are deferred because there is insufficient approved data. Never promote unreviewed predictions to ground truth or claim unavailable model services were tested.

Preserve raw source strings separately from canonical catalog decisions. Preserve provided PDFs, existing labels and unrelated work. Keep private source data, model weights, run outputs and review corrections out of Git. Treat the current sample-derived catalog as provisional. Follow `PROJECT_GOAL.md` when older design documents describe a different architecture.

Read docs/agent-handoff.md for the saved baseline and next steps. Assign each concurrent writer a separate worktree/branch; do not share writable sessions, dataset directories or review releases. Run the unittest suite after meaningful Python changes. A clean checkout intentionally lacks private integration fixtures; report skips explicitly. Preserve the original local legacy branch; publish changes from the clean main history only, never push legacy refs or use push --all/--mirror.
