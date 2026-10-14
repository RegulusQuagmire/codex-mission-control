# Architecture

Published v0.7.0 contains Stage 10 and Concept C Evolution. The current
integration branch adds Stage 11 reviewed pause/continuation to the same execution path.

## Components

Stage 13 extends `routing` with bounded `task_analysis` and provenance-aware
`History.qualityRecords`. `route_inspection` is read-only and shares the existing
selector; DesktopService exposes it through the Bridge allowlist. It neither owns
an adapter nor submits inference. Preview fingerprints invalidate changed inputs.
No SQL schema changes. See [Stage 13](docs/STAGE13.md).

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

## Reviewed project orchestration (local Stage 14)

`orchestration.py` stores protected project drafts and materializes owner-confirmed
DAGs into MissionQueue atomically. PlanRunner is a ManagedRunner validation strategy,
dispatched by the same QueueWorker and adapter. It reads only selected context and
validates inert structured proposals; it neither executes commands nor grants rights.
Generated member fingerprints bind the project marker and confirmed scope. Missing
project state, stale reviews and changed authority fail closed. Separate access,
exact-result execution and exact-turn continuation approvals remain mandatory.

Project progress derives from queue/run evidence, never a second scheduler. Verified
ancestor deltas reuse validator.prepare; newly created required inputs must exist in
the source or a verified dependency. Draft corrections revoke old scope/access; any
current or historical dispatch evidence prevents graph replacement. Version-1
protected documents reuse the existing SQL schema. See docs/STAGE14.md.
