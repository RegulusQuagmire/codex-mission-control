# Building from source

Use a fresh checkout on Windows 10 version 2004+ / Windows 11, x64 Python 3.12+.
Source installation and tests:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[desktop,dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip wheel --no-deps . --wheel-dir dist
```

For a local frozen application only, install the pinned tools from
`packaging/requirements-build.txt`, then run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r packaging/requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm packaging/MissionControl.spec
```

`packaging/build.ps1` additionally invokes a separately installed Inno Setup compiler
and produces a local installer. Neither a frozen app nor an installer is published for
this alpha. Do not rename an older binary as 0.7.0. Verify embedded versions, dependency
notices, replaceable Qt DLLs, exact corresponding sources and clean-machine behavior
before distributing a binary. See [third-party notices](../THIRD_PARTY_NOTICES.md).

Builds on the developer's Windows host are not equivalent to clean Windows VM testing.
