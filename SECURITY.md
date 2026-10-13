# Security

## Reporting

Only the current alpha source is maintained; there is no security support SLA. Use
GitHub's **Report a vulnerability** option if it is available on the repository. If no
private reporting channel is configured, open an issue asking for a private contact
without disclosing exploit details, credentials or personal data.

## Boundaries

The app runs with the current Windows user's permissions. It has no OS sandbox.
Approvals and root restrictions reduce accidental execution; they do not make untrusted
code safe. Review commands and generated changes before approving them. DPAPI does
not protect against an attacker already running as the same user. Portable exports
contain summaries, not transferable execution permission.

Codex owns authentication. Keep its auth files, runtime databases, journals, session
history, prompts, test artifacts and builds out of source control. `.gitignore` does
not remove files already tracked. Rotate any exposed credentials with their provider.

Quota gates depend on server metadata and block new submissions conservatively;
they cannot provide an absolute spending guarantee. Stage 11 cooperative steer/interrupt
control is separate: an RPC ACK does not prove termination or undo external effects.
Never run privileged CI with untrusted pull requests or provide live account secrets to tests.

See [implementation boundaries](docs/SECURITY_HARDENING.md).
