param([string]$Python = "$PSScriptRoot\..\.build-venv\Scripts\python.exe",
      [Parameter(Mandatory=$true)][string]$Iscc,
      [Parameter(Mandatory=$true)][string]$Wheelhouse,
      [Parameter(Mandatory=$true)][string]$RuntimeArchive,
      [Parameter(Mandatory=$true)][string]$SqliteArchive,
      [string]$Output = "$PSScriptRoot\..\dist\release-candidate")
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path "$PSScriptRoot\..").Path
Push-Location -LiteralPath $taskRoot
try {
    & $Python tools/build_release.py --output $Output --iscc $Iscc --wheelhouse $Wheelhouse --runtime-archive $RuntimeArchive --sqlite-archive $SqliteArchive
    if ($LASTEXITCODE -ne 0) { throw 'Release candidate build or audit failed; do not publish' }
} finally { Pop-Location }
