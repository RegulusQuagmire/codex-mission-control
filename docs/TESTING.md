# Testing

Stage 13 adds synthetic task/route/history invariants, read-only service inspection,
stale UI reply/expiry/language checks, and Stage 11 resume compatibility. Run serially.
See [Stage 13 QA](STAGE13.md) for native Router captures and pinned before/after comparison;
neither tool performs inference or uses the user's SQLite queue.

Install `.[desktop,dev]`, then run `python -m pytest -q` in the repository root.
Tests use explicitly synthetic adapters and local subprocess servers; no account,
network inference or API token is required. Windows is required for DPAPI behavior.
The symlink safety test may skip when Windows does not grant symlink privileges;
do not disable the remaining safety checks to work around this.

Compile/import checks: `python -m compileall -q src tests`.
Native GUI smoke with isolated state and no Codex connection:

```powershell
.\.venv\Scripts\python.exe -m mission_control.desktop.app --queue .local/qa/missions.sqlite3 --smoke-report .local/qa/smoke.json
```

The report file must be new. Do not pass `--check-codex` for offline QA. The public
screenshots are produced by `tools/capture_public_demo.py`; it uses offline fixtures
and never approves execution or calls a real Codex server.

CI compiles code, installs the declared dependencies, runs the offline suite, checks
installed dependency consistency/vulnerabilities and scans tracked files for secrets.
It has read-only repository permissions, no account secrets and no publication step.
## Local Stage 11 + Evolution QA

Run the entire offline suite serially after integration, including `test_stage11_ui.py`
and `test_stage11_backend_service.py`. Do not substitute historical branch results.
Native Windows screenshot procedure: [Stage 11 integration](STAGE11_INTEGRATION.md#offline-qa).
