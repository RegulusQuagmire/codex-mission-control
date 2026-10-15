# First launch on Windows

The public alpha is distributed as source. Local Stage 15 builds are not a published
release. Do not use renamed old executables.

1. Install into your user directory; administrator access is unnecessary. Codex,
   authentication and Git are separate prerequisites, obtained from official sources.
   Mission Control does not ask you to paste a token into its settings.
2. Launch the application. Russian is the default; settings offer English and
   Dark/Light themes. In the setup wizard select Codex and your working folder.
   The connection check reads authentication, models and limits without inference.
   If Codex is missing, finish its installation/authentication and check again.
3. Create a mission or project and review paths, commands and dependencies. A draft
   grants no authority. Plan confirmation, folder access, exact-result execution and
   exact-turn continuation are independent approvals. Approved code runs with your
   Windows user's rights; there is no OS sandbox.
4. Start the queue deliberately: inference consumes account limits. Review Model
   Policy, Credit Policy and fresh limits. Unknown limits are not unlimited, and an
   operation with an unknown outcome must not be blindly repeated.
5. After interruption, review the checkpoint and possible prior side effects. An
   empty checkpoint does not prove that nothing happened. A stop RPC acknowledgement
   does not prove process termination or reversal of file actions.

## Data, updates and uninstall

Default database: `%LOCALAPPDATA%\CodexMissionControl\missions.sqlite3`.
Protected SQLite documents use Windows DPAPI and are tied to the Windows user.
Copying the database to another account does not provide automatic recovery.
Portable exports are information-only; they do not restore permissions or executable
project graphs.

Before updating, pause the queue, wait for a confirmed terminal status and preserve
the checkpoint. Reconcile unknown outcomes first. Close the application and back up
its entire data directory securely under the same Windows account, including any
remaining SQLite sidecars. Never publish backups. Compare the installer SHA256 to
a trusted published manifest. Unsigned local builds do not establish publisher identity
and may trigger SmartScreen warnings.

Reinstallation replaces program files without clearing queue state, approvals,
checkpoints or projects. There is no automatic updater. Do not downgrade active
state to older stages; downgrade compatibility is not promised.

Windows uninstall removes program files and shortcuts while preserving user data and
projects. Delete data manually only after preserving needed history and checking for
unfinished missions. For startup problems report Windows/application versions and a
redacted error; do not attach tokens, databases or private code.
