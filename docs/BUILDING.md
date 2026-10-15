# Building from source

Supported source runtime: Python 3.12+, Windows 10 2004+ / Windows 11 x64.
Install editable `.[desktop,dev]` in an isolated venv and run `python -m pytest -q`.
No real inference is needed for regression tests. Never use production SQLite data.

## Pinned candidate build (0.7.1)

The Windows frozen build uses official portable CPython **3.14.8** and twelve exact
Windows wheels with SHA256 in `packaging/requirements-build.txt`. Keep the checkout
at an immutable revision with full Git history (upgrade tests export old sources).
From PowerShell, choose fresh output directories outside the checkout:

```powershell
./tools/bootstrap_release.ps1 -Output ../release-tools
$tools = Get-Content ../release-tools/tools.json -Raw | ConvertFrom-Json
& $tools.python tools/build_release.py --output ../candidate-a --iscc $tools.iscc --wheelhouse $tools.wheelhouse --runtime-archive $tools.runtimeArchive --sqlite-archive $tools.sqliteArchive
& $tools.python tools/build_release.py --output ../candidate-b --iscc $tools.iscc --wheelhouse $tools.wheelhouse --runtime-archive $tools.runtimeArchive --sqlite-archive $tools.sqliteArchive
./tools/windows_release_smoke.ps1 -Candidate ../candidate-a -QaPython .venv/Scripts/python.exe -BuildPython $tools.python -Iscc $tools.iscc -Output ../lifecycle
```

Bootstrap downloads SHA256-pinned official Python ZIP and Inno Setup 6.7.3; verifies
Inno Authenticode publisher Pyrsys; extracts portable tools without registering or
replacing system Python/compiler; installs only hash-locked wheels. Download access
is needed for bootstrap, not for inference. No paid service is used. The builder
itself never downloads tools, installs the app, signs or publishes artifacts.

The builder compares actual installed runtime files with the verified official ZIP
and installed wheel files with exact downloaded wheels. PATH/Qt/Python module
injections are removed. Every native input must belong to a verified wheel, the
verified CPython runtime or the separately authenticated SQLite 3.54.0 archive.
The original Python runtime is unchanged; exactly one collected sqlite3.dll is
replaced in a fresh build directory. Frozen QA checks the actually loaded DLL,
version, source ID and SHA256. `native-inputs.json` preserves relative provenance.
`build-receipt.json` records source/tool hashes; `bundle-manifest.json` lists each
payload file and archived Python module; `artifacts.json` records final hashes.
Bytecode caches, work directories and output directories must be fresh. Fixed hash
seed, SOURCE_DATE_EPOCH and installer file timestamps reduce build variation.
Compare two new manifests/artifact hashes; repeatability is bounded to those inputs.

The directory bundle retains replaceable Qt DLLs. To test modified compatible Qt,
copy the entire bundle, replace matching ABI/version Core/Gui/Widgets/Network/Svg
DLLs/plugins with a licensed build from the exact source versions and run the
isolated smoke matrix. Do not alter a live installation or user data. Qt's upstream
Windows build/configuration guide is https://doc.qt.io/qt-6/windows-building.html .
Public distribution must supply corresponding sources/build configuration and
replacement instructions under an appropriate LGPL source-delivery method.

## Source distribution

```powershell
& $tools.python -c "import setuptools.build_meta as b; b.build_sdist('../source-package')"
& $tools.python tools/source_audit.py ../source-package/codex_mission_control-0.7.1.tar.gz ../source-manifest.json
```

The source package includes application/translations, docs, tests, build tools,
locked inputs and notices; no wheels, DLLs, credentials or SQLite data. Installing
this Python source package is separate from frozen release building. Full offline
upgrade regression requires a Git checkout with the pinned historical revisions;
the sdist does not pretend to contain repository history or vendor source archives.

Native logs/work files can contain developer paths and stay outside public artifacts.
EXE/installer remain unsigned. No installer is published by this workflow. See
[Stage 15 checklist](STAGE15.md) for limitations and distribution review.
An unavailable independent clean-Windows system is a disclosed limitation, not
an automatic release blocker. See [source delivery and replacement](LIBRARY_SOURCES.md).
