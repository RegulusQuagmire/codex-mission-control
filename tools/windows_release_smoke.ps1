param([Parameter(Mandatory)][string]$Candidate,
      [Parameter(Mandatory)][string]$QaPython,
      [Parameter(Mandatory)][string]$BuildPython,
      [Parameter(Mandatory)][string]$Iscc,
      [Parameter(Mandatory)][string]$Output)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$candidateRoot=(Resolve-Path -LiteralPath $Candidate).Path
$qa=(Resolve-Path -LiteralPath $QaPython).Path
$builder=(Resolve-Path -LiteralPath $BuildPython).Path
$compiler=(Resolve-Path -LiteralPath $Iscc).Path
$out=[IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $out) { throw 'Smoke output must be fresh' }
$registration='HKCU:/Software/Microsoft/Windows/CurrentVersion/Uninstall/CodexMissionControlStage15QA_is1'
if (Test-Path $registration) { throw 'Existing QA registration; inspect before testing' }
New-Item -ItemType Directory -Path $out | Out-Null
$old=Join-Path $out 'old-source'
& $qa "$PSScriptRoot/export_upgrade_baseline.py" $old
if ($LASTEXITCODE -ne 0) { throw 'Pinned baseline export failed' }
$savedPath=$env:PATH;$savedPythonPath=$env:PYTHONPATH;$savedUtf8=$env:PYTHONUTF8
try {
    $env:PYTHONUTF8='1'
    $cases=@('basic','submitted','lost_ack','result_approval')
    $env:PYTHONPATH="$old/src"
    foreach ($case in $cases) {
        & $qa "$PSScriptRoot/upgrade_fixture.py" seed "$out/data/$case" --case $case
        if ($LASTEXITCODE -ne 0) { throw ('Old-writer fixture failed: '+$case) }
    }
    $env:PYTHONPATH=$null
    $base=(& $builder -c 'import sys;print(sys.base_prefix)').Trim()
    $env:PATH="$env:SystemRoot/System32;$env:SystemRoot;$base;$base/DLLs"
    # Exact old public source, locally rebuilt; never presented as a published old installer.
    & $builder -m PyInstaller --clean --noconfirm --distpath "$out/old-dist" --workpath "$out/old-build" "$old/packaging/MissionControl.spec" *> "$out/old-build.log"
    if ($LASTEXITCODE -ne 0) { throw 'Old source binary build failed' }
    $setup=Join-Path $out 'setup';New-Item -ItemType Directory -Path $setup | Out-Null
    foreach ($version in @('0.7.0','0.7.1')) {
        $payload=if ($version -eq '0.7.0') { "$out/old-dist/MissionControl" } else { "$candidateRoot/dist/MissionControl" }
        & $compiler ('/O'+$setup) ('/FQA-'+$version) /DQaInstall=1 ('/DAppVersion='+$version) ('/DPayloadDir='+$payload) "$root/packaging/installer.iss" *> "$out/compile-$version.log"
        if ($LASTEXITCODE -ne 0) { throw 'QA installer compile failed' }
    }
    $destination=Join-Path $out 'installed'
    if (-not [IO.Path]::GetFullPath($destination).StartsWith($out+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe install destination' }
    foreach ($version in @('0.7.0','0.7.1','0.7.1')) {
        $log=Join-Path $out ('install-'+$version+'-'+[guid]::NewGuid().ToString('N')+'.log')
        $process=Start-Process -FilePath "$setup/QA-$version.exe" -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/NOICONS',('/DIR="'+$destination+'"'),('/LOG="'+$log+'"')) -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw 'QA installation/upgrade/repair failed' }
        $installed=Get-ItemProperty -LiteralPath $registration
        if ($installed.DisplayVersion -ne $version) { throw 'Installed version mismatch' }
    }
    $manifest=Get-Content -LiteralPath "$candidateRoot/bundle-manifest.json" -Raw | ConvertFrom-Json
    foreach ($entry in $manifest.files) {
        $target=Join-Path $destination $entry.path
        if (-not (Test-Path -LiteralPath $target) -or (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $entry.sha256) { throw ('Installed payload mismatch: '+$entry.path) }
    }
    if (Test-Path -LiteralPath "$destination/_internal/PySide6/opengl32sw.dll") { throw 'Retired software renderer survived upgrade' }
    # Frozen startup must not depend on Python, Git, Codex or developer DLL paths.
    $env:PATH="$env:SystemRoot/System32;$env:SystemRoot"
    foreach ($case in $cases) {
        $report="$out/launch-$case.json"
        $process=Start-Process -FilePath "$destination/MissionControl.exe" -ArgumentList @('--queue',('"'+$out+'/data/'+$case+'/data.sqlite3"'),'--smoke-report',('"'+$report+'"')) -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw ('Installed frozen launch failed: '+$case) }
        $value=Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
        if ($value.errors.Count -ne 0 -or -not $value.frozen -or $value.qtPlatform -ne 'windows') { throw 'Frozen smoke errors' }
        $sqlite=Get-Content -LiteralPath "$root/packaging/sqlite-runtime.json" -Raw | ConvertFrom-Json
        if ($value.sqlite.version -ne $sqlite.version -or $value.sqlite.sourceId -ne $sqlite.sourceId -or $value.sqlite.loadedDllSha256 -ne $sqlite.dll.sha256 -or [IO.Path]::GetFullPath($value.sqlite.loadedDll) -ne [IO.Path]::GetFullPath("$destination/_internal/sqlite3.dll")) { throw 'Installed SQLite runtime identity mismatch' }
    }
    $process=Start-Process -FilePath "$destination/unins000.exe" -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/LOG="'+$out+'/uninstall.log"')) -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0 -or (Test-Path -LiteralPath "$destination/MissionControl.exe") -or (Test-Path $registration)) { throw 'QA uninstall failed' }
    $env:PYTHONPATH="$root/src"
    foreach ($case in $cases) {
        & $qa "$PSScriptRoot/upgrade_fixture.py" verify "$out/data/$case"
        if ($LASTEXITCODE -ne 0) { throw ('Upgrade/uninstall changed protected state: '+$case) }
    }
    @{oldSource='3959e3d4830e359b9c0f720d76bb7c58634591c5';fromVersion='0.7.0';toVersion='0.7.1';cases=$cases;upgrade=$true;repair=$true;uninstall=$true;dataRetained=$true;cleanWindows=$false;realInference=$false;oldInstallerLocallyRebuilt=$true} | ConvertTo-Json | Set-Content -Encoding utf8 "$out/result.json"
} finally {
    $env:PATH=$savedPath;$env:PYTHONPATH=$savedPythonPath;$env:PYTHONUTF8=$savedUtf8
}
