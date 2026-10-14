# Stage 14 — Project Orchestration: design and implementation plan

Base: `7801ac9c22ab3c6683ff88dfc8022c9214100f31`, merged Stage 13, post-merge
Windows CI: 599 passed. Local branch: `stage14/project-orchestration`.

## Goal and boundaries

Manage a project goal as a reviewed set of related Codex missions, with stages,
dependencies, observable progress, plan edits and restart recovery. Build on
MissionQueue; do not add a second scheduler, worker, retry loop or inference path.

Stage 14 implementation and validation are offline: no real inference, paid credits
or auto-top-up. Source publication and PR preparation require owner authorization;
merge, release, installer and Stage 15 remain outside this implementation scope.
Public version is unchanged.
Model Policy, Credit Policy, Stage 11, exact-turn consent and result execution
approvals remain mandatory. The 10% working-mission quota reserve is independent
from the owner's >50% five-hour gate for autonomous stage transitions.

The transition gate was freshly checked before creating this branch and met the
owner's quota requirements. Account-specific readings are not published. No credit
purchase or reset was attempted. This check is not a lasting execution grant.

## Existing behavior to reuse

- MissionQueue validates IDs, task settings, budgets, dependencies and cycles;
  chooses pending missions by dependency completion, priority and stable sequence.
- QueueWorker is the only execution dispatcher; it persists dispatch before
  running, reserves unresolved work and recovers through ManagedRunner.
- `_dependencies()` collects completed project ancestors; ProjectRunner and
  validator.prepare already overlay verified deltas into isolated workspaces.
  Conflicting edits fail closed. No new file-merge engine is needed.
- ProjectRunner extends ManagedRunner and retains checkpoints, pause/resume,
  history, current model/credit gates and the existing Adapter.
- Access approvals bind an exact mission fingerprint. Generated result commands
  require a separate exact-result execution approval. Planner data grants neither.
- JournalStore already supports protected versioned documents and transactions;
  project metadata can use these without changing the SQL schema.
- Concept C provides existing panels, banners, dialogs, tables, localization,
  themes, motion settings and mission/result editors.

## Owner-selected design — option B

The owner explicitly selected the broader planner: Codex may propose files,
commands, checks and dependencies ONLY as an inert draft. Every path and command
must be independently inspectable. Exact revision-bound owner confirmation is
required before materializing executable mission definitions. Allowed roots are
never expanded by a plan. Separate access and exact-result execution approvals
remain mandatory. Any scope change invalidates prior plan and access consent.
Implementation is authorized locally, including offline tests and independent
security/GUI review; stop before publication or PR.

A fresh continuation check also met the owner's quota requirements. Private account
telemetry is omitted. This does not override the separate 10% working-mission reserve.

## Common architecture

### Project record

A versioned protected project document stores project ID, title, goal, workspace,
owner-selected mission defaults/scope, revision, planning mission reference,
reviewed plan and member mission IDs. Runtime status/progress is derived from the
actual queue/run journals; no independent execution status is allowed to drift.

Initial scope targets a selected local workspace supported by the existing queue.
Repository hosting, deployment, arbitrary project scaffolding and background
execution of planner-proposed commands are outside this stage's initial scope.

### Planning through the existing queue

A dedicated planning mission/validation hook uses the same QueueWorker →
ManagedRunner → Adapter path. It runs only after an explicit user action and
existing access approval, never as a background side effect of project creation.
Development uses a synthetic remote only.

The planner returns bounded structured data. Parse strict JSON with duplicate-key
rejection; bound text, node count and dependency depth. Validate unique local node
IDs, known parents and an acyclic graph. No eval, arbitrary imports, shell commands
or file application occurs when parsing. Invalid/unknown outcomes are not replayed.
Structural plan validity is not model-quality success or task completion evidence.

Planning context uses only the selected guarded files and bounded context. The
thread remains read-only with the existing approval policy. A plan review ticket
binds the exact project revision, output turn and canonical plan hash; changes or
new output invalidate review. Stage 11 consent for a paused planning turn is still
an independent exact-turn acknowledgement.

### Plan acceptance and mission graph

Acceptance validates the entire graph, resolves project-local node IDs into stable
mission IDs and materializes normal missions atomically with project references.
Use one queue lock and an existing JournalStore transaction; an error must not
leave half a graph, stale project references or duplicate missions.

No plan acceptance starts a worker or grants access/result approval. Offer a
separate access review of exact generated definitions; batch approval, if exposed,
must bind all fingerprints and the project revision. All existing backend guards
remain active for every turn. Existing dependencies/overlays carry validated output.

### Progress, errors and plan edits

Show actual completed/total missions and stage counts, with explicit failed,
blocked, waiting_limit/credit/network/model/approval/resume and unknown outcomes.
Do not invent weighted quality, cost, token savings or percentage confidence.
General queue pause must not hide required checkpoint/result review.

Reuse normal mission controls and result review. Correction of a plan may change
only undispatched pending definitions/dependencies. Dispatched definitions, active
turns, completed artifacts, history and attempt budgets are immutable. Any changed
definition invalidates previous access approval. Revalidate the entire graph and
reject cycles, dangling references and incompatible edits atomically.

Restart loads project metadata and existing mission/run IDs; it does not recreate
missions, rerequest a plan, auto-approve or infer idle after missing/corrupt state.
Absent/modified completed artifacts use the existing needs_attention behavior.

## Implementation tasks and test gates

### 1. Strict plan and project data

Files: new `src/mission_control/orchestration.py`; new
`tests/test_orchestration.py`.

- Define the selected A/B schema and document model-owned versus owner-owned fields.
- Write RED tests for valid staged DAGs, duplicate IDs/JSON keys, unknown references,
  cycles, unsafe paths, excessive size/depth, injected approval fields and secrets.
- Implement pure validation, canonical plan hashes and deterministic topological
  order. Plan data never invokes adapters, processes or file edits.
- Test optional absence of project documents for older Stage 10–13 databases.

### 2. Durable records and atomic graph materialization

Files: orchestration.py, focused MissionQueue batch helper if needed;
`tests/test_orchestration_storage.py`.

- Reuse protected JournalStore documents, queue locking and transactions.
- RED tests for revision conflicts, duplicate acceptance, invalid definitions,
  missing context, graph rollback, repeated click and restart identity preservation.
- Preserve all existing single-mission add/read/control behavior.
- Never accept planner-supplied status, generation, result, runPath or approvals.
- Test stale access/plan tickets after edits and immutable dispatched definitions.

### 3. Planning mission through ManagedRunner

Files: focused planning runner/validator, queue dispatch type support, safety
fingerprint/access formatting where required; `tests/test_orchestration_planning.py`.

- Add only a validation strategy, not an executor. Use existing adapter and runner.
- RED tests with mock Codex: valid/invalid planning JSON; fresh policy/credit gates;
  Manual/budgets; failure categorization; no quality-history claim for schema-only
  validation; submitted unknown outcome without replay; Stage 11 pause/recovery.
- Guard selected context through secure_files/safe_path and existing size limits.
- Planner proposals remain inert until current explicit review and acceptance.

### 4. Service/Bridge and existing controls

Files: desktop/service.py, desktop/bridge.py, orchestration.py;
`tests/test_orchestration_service.py`.

- Explicit APIs for create/list project, request plan, review/accept plan, edit
  pending plan and project access review; add only explicit Bridge allowlist entries.
- Include revision/fingerprint validation in mutating calls, not only UI checks.
- Project creation/inspection cannot start inference; no hidden auto-start path.
- Drive actual Service → Queue → ManagedRunner with a synthetic adapter in tests.
- Reuse per-mission limits, controls, access approvals and exact result review.

### 5. Concept C project UI

Files: new desktop project dialog/page component, focused Missions integration,
translations.json; `tests/test_orchestration_ui.py`.

- Entry from the existing Missions workflow, preserving search/filter/selection.
- Create from a goal and selected scope; inspect stages, dependencies and real
  progress; review inert plan; edit pending work; open existing review/result flows.
- Display separate plan acceptance, access, execution and continuation permissions.
- Disable duplicate actions and stale dialogs after revision/turn/scope changes.
- RU/EN developer strings; opaque goals, model text, paths, IDs and JSON preserved.
- Reuse themes, native controls, scroll areas, keyboard and reduced-motion behavior.

### 6. Final verification and independent audit

- Run meaningful targeted tests serially, then full sequential offline regression
  on the combined Stage 11–14 tree; never use a real user SQLite database.
- Verify compileall, dependency consistency, git diff --check and secret/scope scan.
- Independent security audit of plan injection, authority boundaries, transaction
  recovery, stale review, dependencies, unknown outcomes and approval separation.
- Fix confirmed P1/P2 findings and repeat only the relevant checks, then final suite
  if implementation changed. Do not claim schema checks establish semantic quality.
- Native Windows GUI QA on safe demo data: RU/EN, Dark/Light, 800×600/960×740/
  1920×1080, Qt scaling, keyboard, reduced motion, long plans and warning states.
- Provide exact files/diff, tests, screenshots, audit disposition and limitations.
  Do not publish Stage 14 or advance to Stage 15.

## Current checkpoint

Stage 13 is merged and verified. The owner selected option B and Stage 14 is
implemented in its separate branch. Validation is consolidated in
`tests/test_orchestration.py` and `tests/test_orchestration_gui.py`, alongside the
existing regression suite. Local offline validation passed 628 tests with one
Windows symlink-privilege skip; independent reviews have no open confirmed P1/P2.
No SQL schema migration or real inference was performed. Source publication is a
separate owner-authorized step; this plan does not authorize merge or a release.
