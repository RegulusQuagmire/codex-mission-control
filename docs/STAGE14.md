# Stage 14 — Project Orchestration (local source)

Stage 14 adds reviewed project plans to Concept C Evolution. It uses the existing
MissionQueue, QueueWorker, Router and ManagedRunner, including Stage 11 checkpoint
consent, Model Policy, Credit Policy and independent execution approvals.

## User workflow / Сценарий

1. Missions → Projects / Миссии → Проекты. Create a project with a goal, an existing
   folder and explicitly selected context files. Creation saves metadata only.
2. Request a Codex draft. This creates one **planning** mission in the shared queue.
   Review its read-only context via Permissions, then explicitly start the queue.
   It uses the current model/credit gates; no commands or project edits are executed
   by plan validation. Development and QA use a synthetic adapter, not real Codex.
3. Inspect stages, mission descriptions and dependencies. Files/access boundaries
   and proposed command argv/timeouts have separate mandatory review sections.
   Plan JSON can be edited or supplied offline. Model output cannot contain approvals.
4. Confirm the exact plan revision and every proposed path/command. This atomically
   creates normal project missions, without starting a worker, expanding allowed
   roots or granting access/execution approval. Repeated/stale confirmation fails.
5. Use existing mission access review and queue controls. Every generated result
   still needs its own exact-result approval before checks execute with local user
   rights. Plan approval is not execution approval. Unknown outcomes are reconciled,
   never blindly resent; interrupted turns require exact-turn Stage 11 consent.
6. Projects shows actual completed/total, dependencies, queue pause, missing access
   consent and stored blocking reasons. A queue pause does not conceal checkpoint
   review. Restart reads the same queue and project IDs without regenerating plans.

Русский язык включён по умолчанию. Язык можно переключать при открытом просмотре;
ID, пути, JSON, пользовательская цель, checkpoint и ответы модели не переводятся.

## Authority and persistence

The owner chose option B: Codex may propose per-mission files and commands only as
untrusted draft data. Strict bounded JSON rejects unknown/duplicate keys, runtime
state, model-owned approval flags, unsafe paths, cycles and missing dependencies.
Planning reads only owner-selected guarded UTF-8 files, with existing secret and
size checks, into a protected context document; its isolated cwd contains no code.
Its schema result is `plan_structure`, excluded from model quality observations.

The review digest binds the project goal, workspace, defaults, revision, draft and
source turn. Confirmation requires an explicit acknowledgement and current digest.
An existing protected `projects` document and queue are written in one SQLite
transaction. There is no SQL schema migration. Generated members have a project
marker included in access fingerprints and an owner-confirmed authority hash.
Missing project evidence/membership or changed scope fails closed before dispatch.

An undispatched graph can be edited: previous members and access approvals are
removed atomically and the new draft requires fresh scope confirmation. Any member
with current or historical dispatch evidence, retry generation or archives makes
the graph immutable. External dependencies also prevent replacement. History,
attempt budgets and completed artifacts are never deleted to re-plan dispatched work.

Verified dependency deltas use the existing workspace overlay path. A new required
input may come from a verified ancestor; if neither source nor verified dependency
provides it, preparation fails. No proposed files overwrite the source project.

## Deliberate limits

- One selected local workspace per project; no repository discovery, hosting,
  deployment, scaffolding or cross-root permission escalation.
- Up to 32 missions, 128 files per input/write list and 16 checks per mission;
  existing UTF-8 context and command timeout limits still apply.
- Draft correction currently uses a JSON editor alongside the readable plan and
  scope review. Dispatched projects require a new explicitly reviewed project.
- One planning request per project. Existing retry/continuation and cumulative
  budgets apply; an unresolved planner cannot be replaced with another request.
- An existing owner draft is reviewed/edited in place; it cannot queue a new
  planning request whose output would be hidden. Use a new project for a new plan.
- Access approvals remain per mission. Existing result and checkpoint review use
  the Missions/Approvals screens. No new auto-start or automatic result approval.
- Commands run with local user rights after result approval; this is not an OS
  sandbox or a rollback guarantee. RPC ACK does not prove processes stopped.
- Project graph metadata is local protected state; portable archives remain
  information-only summaries and do not restore executable graphs or permissions.
- Stage 14 is developed in a separate branch, not merged into main or versioned as
  a release, and has not been exercised with real inference. Source publication
  and PR preparation require owner authorization. Merge, Stage 15, credits,
  real inference, release and installer require separate authorization.

## Verification

New tests cover inert drafts, exact/stale/repeated consent, unsafe paths, injected
permissions, DAG order, atomic failure, access revocation, immutable retry history,
restart, unknown ACK reconciliation, missing evidence, current Model Policy,
Stage 11 checkpoint continuation and the real Service → Queue → Runner path with
two separately approved results and a newly created dependency input. Qt tests
cover mandatory scope sections, duplicate presses, language changes and selection.
A fork-conflict runtime test verifies two approved parent deltas cannot silently
merge conflicting file contents or submit the downstream turn. Planning/generated
missions use project-plan editing, never the incompatible single-mission editor.

The native Windows capture harness `tools/capture_stage14_projects.py` uses safe
OFFLINE DEMO snapshots, no account and no backend requests. It covers RU/EN,
Dark/Light, 800×600, 960×740, 1920×1080 and Qt scales 1/1.25/1.5/2. OS DPI is not
changed. Final run results and independent review evidence are supplied with the
local delivery report; historical Stage 13 results are not Stage 14 validation.
