# Applies GitHub branch protection on main and sets default branch to dev.
# Requires GITHUB_TOKEN with repo admin permissions.
#
# Usage (PowerShell):
#   $env:GITHUB_TOKEN = "ghp_your_token"
#   .\scripts\setup-github-branch-protection.ps1

$ErrorActionPreference = "Stop"

$token = $env:GITHUB_TOKEN
if (-not $token) {
    Write-Host "GITHUB_TOKEN is not set."
    Write-Host "Create a classic PAT with 'repo' scope (admin) and run:"
    Write-Host '  $env:GITHUB_TOKEN = "ghp_..."'
    Write-Host "  .\scripts\setup-github-branch-protection.ps1"
    exit 1
}

$owner = "iamJagruthi"
$repo = "browser-metrics"
$baseUrl = "https://api.github.com/repos/$owner/$repo"
$headers = @{
    Authorization = "Bearer $token"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

Write-Host "Setting default branch to dev..."
$defaultBody = @{ default_branch = "dev" } | ConvertTo-Json
Invoke-RestMethod -Method Patch -Uri $baseUrl -Headers $headers -Body $defaultBody -ContentType "application/json"
Write-Host "Default branch set to dev."

Write-Host "Protecting main (PR required, no force push, enforce admins)..."
$protectionBody = @{
    required_status_checks = $null
    enforce_admins = $true
    required_pull_request_reviews = @{
        dismiss_stale_reviews = $false
        require_code_owner_reviews = $false
        required_approving_review_count = 0
    }
    restrictions = $null
    allow_force_pushes = $false
    allow_deletions = $false
    block_creations = $false
    required_conversation_resolution = $false
    lock_branch = $false
    allow_fork_syncing = $false
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Put -Uri "$baseUrl/branches/main/protection" -Headers $headers -Body $protectionBody -ContentType "application/json"
Write-Host "Branch protection applied to main."

Write-Host ""
Write-Host "Done. Teammates should:"
Write-Host "  git checkout dev"
Write-Host "  git push origin dev"
Write-Host "See docs/GITHUB_BRANCH_POLICY.md for manual UI steps if anything failed."
