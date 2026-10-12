param([string]$Python = "$PSScriptRoot\..\.venv\Scripts\python.exe", [string]$Iscc = 'ISCC.exe')
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path "$PSScriptRoot\..").Path
Push-Location -LiteralPath $taskRoot
try {
    & $Python -m PyInstaller --noconfirm packaging/MissionControl.spec
    if ($LASTEXITCODE -ne 0) { throw 'Сборка приложения не завершена' }
    & $Iscc packaging/installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Сборка установщика не завершена' }
    Get-ChildItem -LiteralPath "$taskRoot\dist" -Filter '*.exe' | Get-FileHash -Algorithm SHA256 |
        Format-Table -AutoSize
} finally { Pop-Location }
