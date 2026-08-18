# Install shared git hooks (blocks direct push to main).
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot
git config core.hooksPath .githooks
Write-Host "Git hooks installed. core.hooksPath = .githooks"
Write-Host "Direct pushes to 'main' are blocked locally. Use branch 'dev' for integration."
