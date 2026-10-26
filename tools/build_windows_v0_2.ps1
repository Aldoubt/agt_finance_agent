param(
    [string]$Python = "python",
    [switch]$SkipInstall,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$PackageName = "AGTFinanceAgent-v0.2.0-preview.1"
$ReleaseRoot = Join-Path $RepoRoot "release"
$WorkRoot = Join-Path $RepoRoot ".pyinstaller-v0.2"
$DistRoot = Join-Path $WorkRoot "dist"
$PackageRoot = Join-Path $ReleaseRoot $PackageName

function Assert-LastExitCode([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE" }
}

New-Item -ItemType Directory -Force -Path $ReleaseRoot, $WorkRoot | Out-Null
if (-not $SkipInstall) {
    Write-Host "[1/5] Installing desktop, OCR and build dependencies..."
    & $Python -m pip install -e ".[ocr,build,test]"
    Assert-LastExitCode "Dependency installation"
}
if (-not $SkipTests) {
    Write-Host "[2/5] Running tests..."
    & $Python -m pytest -q tests
    Assert-LastExitCode "Tests"
}

Write-Host "[3/5] Building the Windows desktop application..."
& $Python -m PyInstaller `
    --noconfirm --clean --windowed --onedir `
    --name "AGTFinanceAgent" `
    --distpath $DistRoot --workpath (Join-Path $WorkRoot "build") --specpath $WorkRoot `
    --collect-all rapidocr_onnxruntime --collect-all onnxruntime --collect-all pymupdf `
    --hidden-import tkinter --hidden-import tkinter.ttk `
    --hidden-import agt_finance_agent.workbench_gui `
    --hidden-import core.workbench.demo `
    --exclude-module pytest `
    --paths $RepoRoot (Join-Path $RepoRoot "agt_finance_agent\app.py")
Assert-LastExitCode "PyInstaller build"

# The complete onedir bundle is required; the EXE must remain beside _internal.
if (Test-Path $PackageRoot) { Remove-Item $PackageRoot -Recurse -Force }
Move-Item (Join-Path $DistRoot "AGTFinanceAgent") $PackageRoot
$InternalRoot = Join-Path $PackageRoot "_internal"
foreach ($runtime in @("msvcp140.dll", "MSVCP140_1.dll", "vcruntime140.dll", "vcruntime140_1.dll")) {
    $systemRuntime = Join-Path (Join-Path $env:SystemRoot "System32") $runtime
    if (Test-Path $systemRuntime) { Copy-Item $systemRuntime (Join-Path $InternalRoot $runtime) -Force }
}
Copy-Item (Join-Path $RepoRoot "docs\WINDOWS_QUICKSTART.txt") (Join-Path $PackageRoot "先看这里.txt")
Copy-Item (Join-Path $RepoRoot "docs\V0.2_使用说明.md") (Join-Path $PackageRoot "使用说明.md")
$Launcher = "@echo off`r`nstart `"`" `"%~dp0AGTFinanceAgent.exe`"`r`n"
Set-Content -Path (Join-Path $PackageRoot "开始整理.bat") -Encoding ascii -Value $Launcher

Write-Host "[4/5] Testing the packaged EXE and bundled OCR models..."
$SmokeRoot = Join-Path $WorkRoot ("smoke-" + [guid]::NewGuid().ToString("N"))
$reportFile = Join-Path $SmokeRoot "self_test_report.json"
$arguments = "--self-test --check-ocr --workspace-root `"$SmokeRoot`""
$process = Start-Process -FilePath (Join-Path $PackageRoot "AGTFinanceAgent.exe") -ArgumentList $arguments -PassThru
if (-not $process.WaitForExit(180000)) {
    if (Test-Path $reportFile) { Get-Content $reportFile -Raw -Encoding utf8 | Write-Host }
    & $Python -c "from PIL import ImageGrab; ImageGrab.grab().save(r'.pyinstaller-v0.2/packaged-timeout.png')"
    $process.Kill()
    throw "Packaged application smoke test exceeded 180 seconds."
}
if (-not (Test-Path $reportFile)) { throw "Packaged application did not write a self-test report." }
$report = Get-Content $reportFile -Raw -Encoding utf8 | ConvertFrom-Json
if ($process.ExitCode -ne 0 -or -not $report.success -or -not $report.ocr_checked) {
    Get-Content $reportFile -Raw -Encoding utf8 | Write-Host
    throw "Packaged application or bundled OCR self-test failed."
}
Copy-Item $reportFile (Join-Path $ReleaseRoot "windows-build-verification.json") -Force

Write-Host "[5/5] Creating download package..."
$ZipPath = Join-Path $ReleaseRoot "$PackageName-win64.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path $PackageRoot -DestinationPath $ZipPath -CompressionLevel Optimal
$ZipHash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -Path "$ZipPath.sha256.txt" -Encoding ascii -Value "$ZipHash  $PackageName-win64.zip"
Write-Host $ZipPath
