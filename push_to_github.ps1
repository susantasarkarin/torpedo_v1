# ============================================================================
# AI Cold Outreach Platform - GitHub Push Script
# ============================================================================
# Commit and push changes to GitHub
# Usage: .\push_to_github.ps1 -Message "Your commit message"
# ============================================================================

param(
    [string]$Message = "AI Cold Outreach Platform - Full deployment",
    [string]$Branch = "main",
    [switch]$Force,
    [switch]$DryRun,
    [switch]$CreateRelease,
    [string]$ReleaseTag = ""
)

$ErrorActionPreference = "Continue"
$Script:ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# Colors
$Colors = @{Success = 'Green'; Warning = 'Yellow'; Error = 'Red'; Info = 'Cyan'; Progress = 'Magenta'}

function Write-Log {
    param([string]$Message, [string]$Type = "Info")
    $timestamp = Get-Date -Format "HH:mm:ss"
    switch ($Type) {
        "Success" { Write-Host "✅ [$timestamp] $Message" -ForegroundColor $Colors.Success }
        "Warning" { Write-Host "⚠️  [$timestamp] $Message" -ForegroundColor $Colors.Warning }
        "Error" { Write-Host "❌ [$timestamp] $Message" -ForegroundColor $Colors.Error }
        "Progress" { Write-Host "🔄 [$timestamp] $Message" -ForegroundColor $Colors.Progress }
        "Step" { Write-Host "`n📋 [$timestamp] $Message" -ForegroundColor $Colors.Info }
        default { Write-Host "ℹ️  [$timestamp] $Message" -ForegroundColor $Colors.Info }
    }
}

function Check-GitStatus {
    Write-Log "Checking git status..." "Step"
    
    # Check if git is available
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Log "Git is not installed!" "Error"
        return $false
    }
    
    # Check if repo exists
    Push-Location $Script:ProjectRoot
    try {
        $gitStatus = git status 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Not a git repository" "Error"
            return $false
        }
        Write-Log "Git repository found" "Success"
        return $true
    } finally {
        Pop-Location
    }
}

function Show-ChangedFiles {
    Write-Log "Changed files:" "Step"
    
    Push-Location $Script:ProjectRoot
    try {
        # Show status
        $status = git status --short 2>&1
        if ($status) {
            $status | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
            
            # Count changes
            $added = ($status | Where-Object { $_ -match "^\?\?" }).Count
            $modified = ($status | Where-Object { $_ -match "^.M" }).Count
            $deleted = ($status | Where-Object { $_ -match "^.D" }).Count
            
            Write-Log "Summary: $added new, $modified modified, $deleted deleted" "Info"
        } else {
            Write-Log "No changes to commit" "Info"
        }
    } finally {
        Pop-Location
    }
}

function Clean-SensitiveFiles {
    Write-Log "Cleaning sensitive files from staging..." "Step"
    
    Push-Location $Script:ProjectRoot
    try {
        # Remove sensitive files from git tracking (if accidentally added)
        $sensitivePatterns = @(
            ".env",
            ".env.local",
            ".env.production",
            "*.pem",
            "*.key",
            ".git-credentials",
            "credentials.json",
            "token.json",
            "gmail_token*.json"
        )
        
        foreach ($pattern in $sensitivePatterns) {
            $files = git ls-files $pattern 2>&1
            if ($files -and $LASTEXITCODE -eq 0) {
                Write-Log "Removing from git: $pattern" "Warning"
                git rm --cached $pattern 2>&1 | Out-Null
            }
        }
        
        Write-Log "Sensitive files cleaned" "Success"
    } finally {
        Pop-Location
    }
}

function Stage-Changes {
    Write-Log "Staging changes..." "Step"
    
    if ($DryRun) {
        Write-Log "[DRY RUN] Would stage all changes" "Info"
        return $true
    }
    
    Push-Location $Script:ProjectRoot
    try {
        git add -A 2>&1 | Out-Null
        Write-Log "Changes staged" "Success"
        return $true
    } finally {
        Pop-Location
    }
}

function Commit-Changes {
    Write-Log "Committing changes..." "Step"
    
    if ($DryRun) {
        Write-Log "[DRY RUN] Would commit with message: $Message" "Info"
        return $true
    }
    
    Push-Location $Script:ProjectRoot
    try {
        $commitOutput = git commit -m "$Message" 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Log "Changes committed" "Success"
            $commitOutput | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
            return $true
        } else {
            if ($commitOutput -match "nothing to commit") {
                Write-Log "Nothing to commit" "Info"
                return $true
            }
            Write-Log "Commit failed: $commitOutput" "Error"
            return $false
        }
    } finally {
        Pop-Location
    }
}

function Push-ToGitHub {
    Write-Log "Pushing to GitHub ($Branch)..." "Step"
    
    if ($DryRun) {
        Write-Log "[DRY RUN] Would push to origin/$Branch" "Info"
        return $true
    }
    
    Push-Location $Script:ProjectRoot
    try {
        # Check remote
        $remote = git remote -v 2>&1
        if (-not ($remote -match "origin")) {
            Write-Log "No 'origin' remote configured" "Error"
            Write-Log "Add remote: git remote add origin https://github.com/user/repo.git" "Info"
            return $false
        }
        
        # Push
        $pushArgs = if ($Force) { @("push", "-u", "origin", $Branch, "--force") } else { @("push", "-u", "origin", $Branch) }
        $pushOutput = git @pushArgs 2>&1
        
        if ($LASTEXITCODE -eq 0) {
            Write-Log "Pushed to GitHub successfully" "Success"
            return $true
        } else {
            Write-Log "Push failed: $pushOutput" "Error"
            return $false
        }
    } finally {
        Pop-Location
    }
}

function Create-GitHubRelease {
    if (-not $CreateRelease) { return }
    
    Write-Log "Creating GitHub release..." "Step"
    
    $tag = if ($ReleaseTag) { $ReleaseTag } else { "v$(Get-Date -Format 'yyyy.MM.dd')" }
    
    if ($DryRun) {
        Write-Log "[DRY RUN] Would create release: $tag" "Info"
        return
    }
    
    Push-Location $Script:ProjectRoot
    try {
        # Create tag
        git tag -a $tag -m "Release $tag" 2>&1 | Out-Null
        git push origin $tag 2>&1 | Out-Null
        
        Write-Log "Tag created: $tag" "Success"
        Write-Log "Create release at: https://github.com/$(git remote get-url origin)/releases/new" "Info"
    } finally {
        Pop-Location
    }
}

function Show-Summary {
    Push-Location $Script:ProjectRoot
    try {
        $remote = git remote get-url origin 2>&1
        $branch = git branch --show-current 2>&1
        $lastCommit = git log -1 --oneline 2>&1
        
        Write-Host @"

╔════════════════════════════════════════════════════════════════════════════╗
║                        GITHUB PUSH COMPLETE                               ║
╚════════════════════════════════════════════════════════════════════════════╝

📦 Repository: $remote
🌿 Branch:     $branch
📝 Commit:     $lastCommit

🔗 GitHub Actions will run automatically (if configured)

📋 Next Steps:
   1. Verify push: https://github.com/$(($remote -replace 'https://github.com/', '') -replace '\.git', '')
   2. Check Actions: View CI/CD pipeline status
   3. Create Release: gh release create (if using GitHub CLI)

"@ -ForegroundColor Cyan
    } finally {
        Pop-Location
    }
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

function Main {
    Write-Host "`n╔════════════════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║                    GITHUB PUSH - AI Cold Outreach                         ║" -ForegroundColor Cyan
    Write-Host "╚════════════════════════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan
    
    if ($DryRun) {
        Write-Log "Running in DRY RUN mode - no changes will be made" "Warning"
    }
    
    if (-not (Check-GitStatus)) {
        exit 1
    }
    
    Show-ChangedFiles
    Clean-SensitiveFiles
    
    if (-not (Stage-Changes)) { exit 1 }
    if (-not (Commit-Changes)) { exit 1 }
    if (-not (Push-ToGitHub)) { exit 1 }
    
    Create-GitHubRelease
    Show-Summary
    
    Write-Log "GitHub push completed successfully!" "Success"
}

# Run
Main
