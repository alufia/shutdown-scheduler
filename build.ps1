$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Virtual environment was not found. Create .venv first."
}

Remove-Item (Join-Path $root "build") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $root "dist") -Recurse -Force -ErrorAction SilentlyContinue

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name "ShutdownScheduler" `
    --icon ".\assets\shutdown_scheduler.ico" `
    --add-data ".\assets\shutdown_scheduler.ico;assets" `
    shutdown_scheduler.py

Write-Host ""
Write-Host "Build complete:"
Write-Host (Join-Path $root "dist\ShutdownScheduler\ShutdownScheduler.exe")
