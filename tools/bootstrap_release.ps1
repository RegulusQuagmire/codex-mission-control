param([Parameter(Mandatory)][string]$Output)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$out=[IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $out) { throw 'Bootstrap output must be fresh' }
New-Item -ItemType Directory -Path $out | Out-Null
function Download-Verified([string]$Url,[string]$File,[string]$Hash) {
    Invoke-WebRequest -Uri $Url -OutFile $File
    if ((Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash -ne $Hash) { throw 'Tool archive checksum mismatch' }
}
$runtime=Get-Content -LiteralPath "$root/packaging/python-runtime.json" -Raw | ConvertFrom-Json
$archive=Join-Path $out 'python-runtime.zip'
Download-Verified $runtime.url $archive $runtime.sha256
$sqlite=Get-Content -LiteralPath "$root/packaging/sqlite-runtime.json" -Raw | ConvertFrom-Json
$sqliteArchive=Join-Path $out $sqlite.archive.file
Download-Verified $sqlite.archive.url $sqliteArchive $sqlite.archive.sha256
$pythonRoot=Join-Path $out 'python'
Expand-Archive -LiteralPath $archive -DestinationPath $pythonRoot
$python=Join-Path $pythonRoot 'python.exe'
$env:PYTHONUTF8='1';$env:PYTHONNOUSERSITE='1'
& $python -m venv (Join-Path $out 'venv')
if ($LASTEXITCODE -ne 0) { throw 'Release venv creation failed' }
$builder=Join-Path $out 'venv/Scripts/python.exe'
$wheels=Join-Path $out 'wheels'
& $builder -m pip download --only-binary=:all: --require-hashes -r "$root/packaging/requirements-build.txt" -d $wheels
if ($LASTEXITCODE -ne 0) { throw 'Pinned wheel acquisition failed' }
& $builder -m pip install --no-index --find-links $wheels --require-hashes -r "$root/packaging/requirements-build.txt"
if ($LASTEXITCODE -ne 0) { throw 'Pinned build dependency installation failed' }
$innoArchive=Join-Path $out 'inno-portable.exe'
Download-Verified 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe' $innoArchive '9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732'
$signature=Get-AuthenticodeSignature -LiteralPath $innoArchive
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Pyrsys') { throw 'Unexpected Inno publisher signature' }
$inno=Join-Path $out 'inno'
$process=Start-Process -FilePath $innoArchive -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/PORTABLE=1','/CURRENTUSER','/NOICONS',('/DIR="'+$inno+'"')) -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath "$inno/ISCC.exe")) { throw 'Portable compiler extraction failed' }
@{python=$builder;runtimeArchive=$archive;sqliteArchive=$sqliteArchive;wheelhouse=$wheels;iscc="$inno/ISCC.exe"} | ConvertTo-Json | Set-Content -Encoding utf8 "$out/tools.json"
