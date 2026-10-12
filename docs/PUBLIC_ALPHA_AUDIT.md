# v0.7.0 Public Alpha publication checks

Audit date: 2026-10-12. Scope: source-only publication of completed stages 1–10.

## Source and history

The public tree is an independent snapshot of the completed stage-10 code. Private
history and unfinished stage-11 work are preserved separately and are not ancestors
of the new public history. No history rewrite, reset or force push is used.
Only the owner’s confirmed Git identity is used for public commits. Runtime state,
private development reports, session identifiers, personal paths and old builds are excluded.

## Security checks

Gitleaks 8.30.1 found no rule matches across the original 17 reachable commits or
the initial exported stage-10 tree. Additional inspection found private local paths
and real session IDs in internal reports; those reports are excluded from this tree.
The exact public files and clean public history are checked again before push.
Pattern-based scanning cannot prove that no undiscovered secret or vulnerability exists.

The old cryptography constraint admitted vulnerable versions. Public requirements now
use `cryptography>=50.0.2,<51`, with 50.0.2 pinned for frozen builds. Advisory checks of
both resolved runtime dependencies and the isolated installed environment reported no
known vulnerabilities after updating the environment’s pip. Audit tools are not app dependencies.

CI uses read-only repository permissions, pinned action revisions, no persisted checkout
credentials, offline synthetic tests, dependency advisory checks and a checksum-verified
secret scanner. No account secrets, inference or release publication are configured.

## License checks

The owner confirmed rights to license their original code under MIT. Seventeen runtime,
desktop, test and build components have an exact-version [license inventory](DEPENDENCIES.md).
Original third-party license texts remain separate. No conflict was identified for source
distribution. Qt LGPL and other binary obligations still require a separate bundled audit
before any installer is distributed. No third-party font or image pack is redistributed.

## Verification

- Stage-10 baseline: **441 passed, 1 skipped** in 257.06 seconds.
- Public source with cryptography 50.0.2: **441 passed, 1 skipped** in 255.06 seconds.
- The existing skip concerns Windows symlink privileges; safety tests are retained.
- Python source/test compilation and dependency consistency checks passed.
- Isolated source installation and wheel/sdist builds passed.
- Local PyInstaller application build passed, with embedded file/product version 0.7.0.
- Native source GUI smoke: version 0.7.0, seven pages, no errors, no Codex connection.
- Frozen GUI smoke: version 0.7.0, seven pages, no errors, no Codex connection.
- Eight real native Qt screenshots use labelled synthetic data; zero backend requests
  and zero real inference calls. See [SCREENSHOTS.md](SCREENSHOTS.md).

These checks ran on one Windows developer host, not a clean Windows VM. Live inference
and stage-11 interruption were deliberately not tested. GitHub-hosted CI results must
be checked separately after publication; local results are not presented as hosted results.

The first hosted run exposed a test-fixture collision: a runner database password
(`root`) appeared in a pytest directory derived from the test name. The existing
secret guard conservatively rejected it. The transaction test now uses a neutral
temporary directory and explicitly verifies that the synthetic credential is still
rejected. Production filtering and all transaction/rollback assertions are unchanged.

## Before a binary release

Obtain separate owner authorization, complete the exact native dependency/SBOM and
corresponding-source audit, verify Qt library replacement, build the installer with matching
metadata, calculate hashes and test on clean Windows machines. No installer, release tag
or GitHub Release accompanies this source alpha.
