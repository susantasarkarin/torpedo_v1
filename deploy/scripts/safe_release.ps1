param(
    [Parameter(Mandatory = $true)]
    [string]$Message,

    [Parameter(Mandatory = $true)]
    [string[]]$Include,

    [string]$ProjectRoot,
    [string]$Branch = "main",
    [switch]$Push,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $ProjectRoot -or $ProjectRoot.Trim() -eq "") {
    $ProjectRoot = Resolve-Path (Join-Path $scriptRoot "..\..")
}

Set-Location $ProjectRoot

function Write-Info([string]$Text) {
    Write-Host "[INFO] $Text" -ForegroundColor Cyan
}

function Write-Warn([string]$Text) {
    Write-Host "[WARN] $Text" -ForegroundColor Yellow
}

function Write-Err([string]$Text) {
    Write-Host "[ERROR] $Text" -ForegroundColor Red
}

function Run-Git([string[]]$GitArgs) {
    $output = & git @GitArgs 2>&1
    $exitCode = $LASTEXITCODE
    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = $output
    }
}

function Normalize-PathValue([string]$PathValue) {
    return $PathValue.Replace('\\', '/').Trim()
}

function Is-AllowedStagedFile([string]$StagedFile, [string[]]$Allowlist) {
    $normalizedStaged = Normalize-PathValue $StagedFile

    foreach ($entry in $Allowlist) {
        $normalizedEntry = Normalize-PathValue $entry

        if ($normalizedStaged -eq $normalizedEntry) {
            return $true
        }

        if ($normalizedStaged.StartsWith("$normalizedEntry/", [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }

    return $false
}

$insideRepo = Run-Git -GitArgs @('rev-parse', '--is-inside-work-tree')
if ($insideRepo.ExitCode -ne 0 -or ($insideRepo.Output -join "`n").Trim() -ne 'true') {
    Write-Err "Current directory is not inside a git repository."
    exit 1
}

$currentBranch = Run-Git -GitArgs @('branch', '--show-current')
if ($currentBranch.ExitCode -ne 0) {
    Write-Err "Unable to determine current git branch."
    exit 1
}
$currentBranchName = ($currentBranch.Output -join "`n").Trim()
Write-Info "Current branch: $currentBranchName"

if ($currentBranchName -ne $Branch) {
    Write-Warn "You are on '$currentBranchName' while target branch is '$Branch'."
}

$alreadyStaged = Run-Git -GitArgs @('diff', '--cached', '--name-only')
if ($alreadyStaged.ExitCode -ne 0) {
    Write-Err "Unable to inspect staged files."
    exit 1
}
$alreadyStagedFiles = @($alreadyStaged.Output | Where-Object { $_ -and $_.Trim() -ne '' })
if ($alreadyStagedFiles.Count -gt 0) {
    Write-Err "There are already staged files. Unstage or commit them before running this script."
    $alreadyStagedFiles | ForEach-Object { Write-Host "  - $_" }
    exit 1
}

Write-Info "Staging allowlist paths only..."
$addResult = Run-Git -GitArgs (@('add', '--') + $Include)
if ($addResult.ExitCode -ne 0) {
    Write-Err "Failed to stage include list."
    Write-Host ($addResult.Output -join "`n")
    exit 1
}

$stagedNow = Run-Git -GitArgs @('diff', '--cached', '--name-only')
if ($stagedNow.ExitCode -ne 0) {
    Write-Err "Unable to inspect staged files after staging."
    exit 1
}
$stagedFiles = @($stagedNow.Output | Where-Object { $_ -and $_.Trim() -ne '' })

if ($stagedFiles.Count -eq 0) {
    Write-Err "No files were staged. Check your -Include paths."
    exit 1
}

$outsideAllowlist = @()
foreach ($file in $stagedFiles) {
    if (-not (Is-AllowedStagedFile -StagedFile $file -Allowlist $Include)) {
        $outsideAllowlist += $file
    }
}

if ($outsideAllowlist.Count -gt 0) {
    Write-Err "Safety check failed: staged files outside allowlist were detected."
    $outsideAllowlist | ForEach-Object { Write-Host "  - $_" }
    Write-Host "Rolling back staged state to keep working tree safe..."
    & git reset --quiet
    exit 1
}

Write-Info "Staged files:"
$stagedFiles | ForEach-Object { Write-Host "  - $_" }

if ($DryRun) {
    & git reset --quiet
    Write-Info "Dry run enabled. Commit and push were skipped."
    exit 0
}

$commitResult = Run-Git -GitArgs @('commit', '-m', $Message)
if ($commitResult.ExitCode -ne 0) {
    Write-Err "Commit failed."
    Write-Host ($commitResult.Output -join "`n")
    exit 1
}
Write-Info (($commitResult.Output -join "`n").Trim())

if ($Push) {
    Write-Info "Pushing to origin/$currentBranchName ..."
    $pushResult = Run-Git -GitArgs @('push', 'origin', $currentBranchName)
    if ($pushResult.ExitCode -ne 0) {
        Write-Err "Push failed."
        Write-Host ($pushResult.Output -join "`n")
        exit 1
    }
    Write-Info (($pushResult.Output -join "`n").Trim())
}

Write-Info "Safe release workflow completed successfully."
