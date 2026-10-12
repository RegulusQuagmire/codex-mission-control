# Architecture

Codex Mission Control v0.7.0 contains the stage-10 implementation.

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

## Excluded work

Stage-11 steer/interrupt, reviewed continuation and reset-driven pause/resume are absent.
The stage-10 submission gate does not interrupt a running turn.
