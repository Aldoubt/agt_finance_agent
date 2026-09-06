param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot
$ReleaseRoot = Join-Path $RepoRoot "release"
$WorkRoot = Join-Path $RepoRoot ".pyinstaller"

function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

Remove-Item $ReleaseRoot -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $WorkRoot -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "[1/4] Installing V0.1 runtime/build dependencies..."
& $Python -m pip install -e ".[ocr,build]"
Assert-LastExitCode "Dependency installation"

Write-Host "[2/4] Running automated tests..."
& $Python -m pytest -q tests
Assert-LastExitCode "Automated tests"

Write-Host "[3/4] Building Windows onedir package..."
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name "AGTFinanceAgent-v0.1.0" `
    --distpath $ReleaseRoot `
    --workpath $WorkRoot `
    --specpath $WorkRoot `
    --collect-all rapidocr_onnxruntime `
    --collect-all onnxruntime `
    --hidden-import tkinter `
    --hidden-import tkinter.ttk `
    --paths $RepoRoot `
    (Join-Path $RepoRoot "agt_finance_agent\app.py")
Assert-LastExitCode "PyInstaller build"

# Windows 11 25H2 ships a newer VC runtime than the one PyInstaller may copy
# from the base Python installation. ONNX Runtime 1.29 can fail with WinError
# 1114 when the stale app-local runtime shadows the newer system runtime.
$InternalRoot = Join-Path $ReleaseRoot "AGTFinanceAgent-v0.1.0\_internal"
$System32 = Join-Path $env:SystemRoot "System32"
foreach ($runtime in @("msvcp140.dll", "MSVCP140_1.dll", "vcruntime140.dll", "vcruntime140_1.dll")) {
    $systemRuntime = Join-Path $System32 $runtime
    if (Test-Path $systemRuntime) {
        Copy-Item $systemRuntime (Join-Path $InternalRoot $runtime) -Force
    }
}

$PackageRoot = Join-Path $ReleaseRoot "AGTFinanceAgent-v0.1.0"
$GuidePath = Get-ChildItem -Path (Join-Path $RepoRoot "docs") -Filter "V0.1*.md" -File |
    Select-Object -First 1
if ($null -eq $GuidePath) {
    throw "V0.1 guide was not found under docs/."
}
Copy-Item $GuidePath.FullName (Join-Path $PackageRoot "README-V0.1.md") -Force
$ZipPath = Join-Path $ReleaseRoot "AGTFinanceAgent-v0.1.0-win64.zip"
Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue
Compress-Archive -Path $PackageRoot -DestinationPath $ZipPath -CompressionLevel Optimal
$ChecksumPath = "$ZipPath.sha256.txt"
$ZipHash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -Path $ChecksumPath -Encoding ascii -Value "$ZipHash  AGTFinanceAgent-v0.1.0-win64.zip"

Write-Host "[4/4] Build complete."
Write-Host (Join-Path $ReleaseRoot "AGTFinanceAgent-v0.1.0\AGTFinanceAgent-v0.1.0.exe")
Write-Host $ZipPath
Write-Host $ChecksumPath
