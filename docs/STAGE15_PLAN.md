# Stage 15 вЂ” Open-Source Release Hardening

## Scope and design

Goal: make the existing Windows packaging repeatable, inspectable and testable without
changing mission execution or publishing binaries. Extend PyInstaller one-directory
and Inno Setup, retain replaceable Qt DLLs and the existing per-user AppId. No second
installer framework, self-updater, telemetry or privileged service.

Base: Stage 14 merge `b394f4b1f23b8913d7def0ab6eaaa39cc96972b6`.
Branch: `stage15/release-hardening`. The owner authorized local development, offline
tests and independent review; no inference, credits, release or distribution.

## Implementation and verification

1. Lock all twelve build/runtime wheels for official portable CPython 3.14.8 Windows x64, with SHA256.
   Build in a separate environment using `--require-hashes`, never the user's Codex
   environment. Require the pinned compiler and fail on mismatches. Record relative
   source hashes, dependency versions and payload hashes without account data.
2. Extend `tools/release_audit.py`, `packaging/build.ps1` and the existing spec:
   fail closed on private files, linked payloads, unexpected executables and unreviewed
   Qt modules; preserve license paths. Compare two independently cleaned builds.
   Reproducible means measured identical hashes in the tested environment, not a
   promise about arbitrary machines or signed installers.
3. Harden hidden desktop smoke QA: explicit disposable SQLite queue required,
   default user database rejected; no automatic queue start or inference. Capture
   real Windows Qt pages and onboarding, RU/EN and Dark/Light at three window sizes
   and representative Qt scales. Normal startup semantics stay unchanged.
4. Localize installer tasks and launch text, show MIT and component-scoped Microsoft runtime terms, retain lowest
   privileges, stable AppId, no automatic restart and no user-data deletion.
   Audit installed files against the bundle manifest. Test first install, first
   launch, same-version reinstall/repair and uninstall in a guarded disposable
   destination. Abort if the real application is already registered.
5. Test protected SQLite/DPAPI state and approvals across restart and installation
   lifecycle, using synthetic fixtures only. Existing Stage 11вЂ“14 regression proves
   mission policies, exact-turn consent and unknown-outcome retry guards remain.
6. Document first launch, separate approvals, update/recovery and uninstall in RU/EN.
   Audit exact bundled dependencies and notices. Missing corresponding-source or
   clean-machine evidence remains an explicit publication blocker.
7. Run focused RED/GREEN tests, compile, dependency consistency, complete offline
   regression sequentially, secret scan and `git diff --check`. Independently review
   packaging/security and GUI; fix confirmed blockers, then export final diff/report.

## Acceptance boundaries

No SQL schema or execution-policy change. No installation into an existing user
installation, no real SQLite database, no credentials in artifacts. A host smoke test
does not count as a clean Windows test. If no disposable clean Windows VM/Sandbox is
available, supply a reproducible operator checklist and report that validation as
not performed. No fabricated success, Authenticode signature or license-compliance
guarantee. The owner subsequently authorized a correctly attributed commit, branch push and PR
after local verification. Stop before merge, Release or installer publication.


## Audit rulings

- Release build runtime moved to official portable Python 3.14.8: security-only
  3.12.14 has no official Windows installer, and developer runtime DLLs were not
  upstream-identical. Source compatibility and regression remain Python 3.12+.
- Sanitize native/module paths and verify each collected DLL provider; the earlier
  candidate with PATH-contaminated OpenSSL/API-set inputs is discarded as evidence.
- Exclude unused Mesa and image-codec plugins; retain SVG/Qt Widgets, then repeat
  native GUI QA because the actual binary runtime changed.
- Add old-source 0.7.0 → 0.7.1 synthetic upgrade and Windows CI lifecycle; a locally
  reconstructed old installer is explicitly labeled, never a published artifact.
- Independent clean Windows is unavailable by owner confirmation. Record it as a
  public-release blocker, without blocking source PR or proposing paid services.
