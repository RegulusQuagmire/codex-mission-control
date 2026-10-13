# Architecture

Published v0.7.0 contains Stage 10 and Concept C Evolution. The current
integration branch adds Stage 11 reviewed pause/continuation to the same execution path.

## Components

- `desktop/`: Qt Widgets UI, asynchronous bridge, settings, approvals and overlay.
- `rpc.py` and `adapter.py`: bounded stdio JSON-RPC, notifications, account/catalog/
  limit reads, thread lifecycle and configuration verification.
- `routing.py`, `model_policy.py`, `execution.py`: task assessment, model filters,
  reasoning caps, validated results and bounded escalation.
- `limits.py`, `credit_policy.py`, `managed.py`: quota applicability, fresh submission
  gates, waiting, reconciliation and durable managed runs.
- `queue.py`, `mission_run.py`: dependencies, worker leases, persisted dispatch state.
- `storage.py`, `secure_files.py`: SQLite/DPAPI and guarded file access.
- `safety.py`, `validator.py`, `checkpoints.py`: approval boundaries, isolated result
  validation and project checkpoints.
- `transfer.py`: password-encrypted information-only portable summaries. Imported
  data does not grant roots, restore execution permission or resume work automatically.
- `cli.py`, `managed_cli.py`, `queue_cli.py`, `routing_cli.py`: command-line entry points.

## Submission flow

Task → fresh catalog and quota snapshot → assessment → model/credit/security gates
→ new thread or exclusive idle resume → persist intent → `turn/start` → persist ACK
→ observe completion → verify configuration → validate result → record observation.

Quality failure can escalate effort and then a stronger known model within a fixed
attempt budget. Network/authentication errors, unknown outcomes and exhausted limits
do not justify blind retries or model escalation. Unknown model capacity is not invented.

## Persistence and concurrency

Persist before inference; reconcile acknowledged turns or uniquely identified new
turns after a lost ACK. Ambiguous history requires attention. Local OS leases coordinate
this application's own workers; external clients do not honor them. There is no atomic
server-side idle condition, so concurrent control of one thread is unsupported.

SQLite and DPAPI are Windows-specific. Project files, logs and external Codex state
are not all encrypted by this application. Approval and checkpoint mechanisms do not
provide OS isolation, transactional rollback of external effects, or financial guarantees.

## Reviewed turn continuation (local Stage 11 integration)

UI → DesktopService → QueueWorker → ManagedRunner/ProjectRunner → CodexAdapter → RPC.
`pause.py` targets one acknowledged turn, persists control intent before each RPC,
and never treats steer/interrupt ACK as terminal evidence. Confirmed terminal events
or reconciliation produce `paused_turn` / `waiting_resume`. Unknown sends are reconciled,
never blindly repeated. Bounded text checkpoints are context, not permissions or rollback.

ResultDialog requires checkpoint review and explicit consent for the exact saved turn.
Snapshot changes invalidate stale consent. Queue/run locks bind the acknowledgement;
remote turn IDs must match the saved baseline plus reviewed turn at both history reads.
Continuation preserves thread/mission identity and attempt budget, and rechecks current
catalog, model/credit/security policies and the final submission guard. Access approvals,
result execution review IDs and continuation turn IDs remain independent gates.

Storage uses existing version-1 document payloads and unchanged SQL schema. Older
Stage 10 records remain readable; downgrade of active Stage 11 journals is not promised.
No atomic server-side expected-idle guarantee exists after the final read. External
concurrent control of the same thread remains unsupported. No Stage 13, real inference,
publication, release or installer belongs to this integration.
