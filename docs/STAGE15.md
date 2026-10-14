# Stage 15 вЂ” local release hardening

Stage 14 is merged through PR #5. Stage 15 is local development, not a new public
version or approval to distribute an installer. Public alpha remains 0.7.0; the unpublished candidate is 0.7.1.
The execution path, SQL schema, Model/Credit Policy and Stage 11вЂ“14 approvals remain.

## Local candidate and evidence

Use [BUILDING.md](BUILDING.md). The builder verifies twelve exact wheels, installed
files against those wheels, the Inno toolchain and a stable source tree. Output is a
replaceable-DLL PyInstaller directory and a lowest-privilege Inno installer. It does
not install, publish, push, sign or execute generated mission code.

`build-receipt.json` contains relative source hashes and exact tool versions;
`bundle-manifest.json` lists every payload file/hash and archived Python module;
`artifacts.json` gives EXE/installer hashes. Account identifiers, limits, credentials
and developer absolute paths are excluded from receipts. Build logs remain private.
Do not equate matching payload hashes with a complete legal or security certification.

Hidden QA mode requires an explicit disposable queue, rejects the default user DB,
disables system integration/automatic queue launch and records errors. With
`--smoke-screenshots` it captures seven real Qt pages and onboarding in the requested
RU/EN, Dark/Light and size. A `windows` platform report is required for native QA;
offscreen unit rendering is separate. Qt scale factors do not prove changed OS DPI.
This mode does not request inference. Never pass a real user queue to QA.

Local reports and screenshots accompany the owner handoff outside the public Git
tree. They distinguish passing checks, unperformed checks and publication blockers.

## Installation lifecycle QA

Build a **separate QA installer** with `/DQaInstall=1` and the audited PayloadDir.
It uses a separate registration identity so it cannot replace a real installation.
Test in a new disposable directory, with `/NOICONS`, no postinstall launch and no
restart. Inspect the log and compare installed payload hashes to the manifest.
Seed only synthetic DPAPI-protected state and run the installed EXE with an explicit
QA queue. Reinstall the same version (repair), compare payload and preserved state,
restart the app, uninstall and verify program files removed while synthetic data
outside the installation directory remains. The cross-version harness additionally rebuilds immutable public 0.7.0 source
3959e3d4830e359b9c0f720d76bb7c58634591c5, installs it under the QA AppId, upgrades
to 0.7.1, repairs and uninstalls. This old installer is locally reconstructed, not
a previously published installer. Four old-writer fixtures cover settings/graph/
paused queue, known/unknown submission recovery and independent result approvals.
Stage 14 source fixtures separately cover checkpoint consent and project DAG state.
All use synthetic DPAPI/SQLite state; no generated commands execute. This is not a
clean-machine installation.

Before testing the production AppId, verify no real installation exists. Do not
override an existing application or rely on an unknown registry read. Standard
installer QA remains part of clean-machine testing below.

## Required clean Windows operator check

Use a disposable Windows 10 2004+ x64 / Windows 11 VM without Python, Qt, Git, Codex
or developer PATH entries. No credentials, production projects or host writable
folders may be shared. Copy the reviewed candidate and manifest into the VM.

1. Verify SHA256 before launch. Install as a standard user, RU and EN; ensure no UAC
   elevation, unexpected services, scheduled tasks, startup entries or network fetch.
2. Test normal first launch and wizard without Codex, then missing/authentication
   diagnostics with an explicitly authorized Codex installation. No inference.
3. Inspect RU/EN, Dark/Light, 800Г—600, 960Г—740 and 1920Г—1080, OS DPI 100/125/150/200%,
   keyboard navigation, reduced motion and long warnings. Save native screenshots.
4. Repeat repair and upgrade from a separately reviewed previous binary, preserving
   synthetic SQLite/DPAPI state, roots, independent approvals and checkpoint consent.
   Never downgrade active new-format state. Verify no automatic queue execution.
5. Uninstall via Windows; verify shortcuts/program files gone, projects/data retained.
   Snapshot/revert the VM; do not use real accounts or export protected user state.

Absence of an available VM/Sandbox is reported as **not tested**, never a pass.
Host smoke testing without developer PATH is useful but does not replace this matrix.

## License/distribution gate

The payload carries original MIT, dependency notices, CPython, PyInstaller exception,
Qt LGPL/GPL texts and exact-version OpenSSL/Inno license texts. Provenance hashes are
in `packaging/license-sources.json`. Installed wheel metadata alone is insufficient:
Qt wheels may include only commercial reference text, and embedded Qt, OpenSSL,
Rust and MSVC components require their own exact inventory/source obligations.

Exact upstream source archives, Qt attribution and cryptography Cargo crate notices
were acquired and hashed. Native provenance is gated against official Python and
locked wheels; developer PATH DLLs are rejected. Microsoft runtime conditions from
the actual CPython Windows license are presented separately in the installer.

Before public distribution provide the corresponding library sources and exact build
configuration through a compliant delivery method and verify compatible LGPL library
replacement. Retaining notices and upstream links alone does not complete delivery.

## Public installer release checklist

- [ ] Independent clean Windows without Python/developer tools: **NOT TESTED**. Owner
  has no disposable Windows system/VM or budget; no paid test service is proposed.
- [ ] Authenticode signature: **ABSENT**. SmartScreen/reputation warnings remain.
- [ ] Corresponding-source delivery/build configuration and modified-library
  replacement verified for the exact binary being distributed.
- [ ] Explicit owner authorization for public installer/Release distribution.

These gates block public installer release, not the source PR. The free standard
public Windows GitHub Actions runner adds install/upgrade/run/uninstall smoke but
contains development tools and is not an independent clean consumer Windows test.
The workflow uploads no installer artifacts and has read-only repository permissions.

New users: [Русский](FIRST_RUN.md), [English](FIRST_RUN.en.md).
