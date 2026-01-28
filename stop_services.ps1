# ============================================================================
# AI Cold Outreach Platform - Service Shutdown Script
# ============================================================================
# This script gracefully stops all running services for the campaign platform.
#
# Usage: .\stop_services.ps1 [-Force] [-Verbose]
#
# Features:
#   - Graceful shutdown with timeout
#   - Force termination if needed
#   - Process status verification
#   - Log file cleanup options
#   - Exit code reporting
#
# Author: Campaign Platform Team
# Version: 1.0
# ============================================================================

param(
    [switch]$Force,
    [switch]$Verbose,
    [switch]$CleanLogs
)

# Set error handling
$ErrorActionPreference = "Continue"
$VerbosePreference = if ($Verbose) { "Continue" } else { "SilentlyContinue" }

# ============================================================================
# GLOBAL CONFIGURATION
# ============================================================================

$Script:ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script:LogDir = Join-Path $ProjectRoot "logs"
$Script:LogFile = Join-Path $LogDir "shutdown_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss').log"

$Script:GracefulTimeoutSeconds = 10
$Script:ProcessPatterns = @(
    @{ Name = "Backend"; Pattern = "uvicorn" },
    @{ Name = "Frontend"; Pattern = "npm"; PartialMatch = "dev" },
    @{ Name = "Celery"; Pattern = "celery" }
)

# Color definitions
$Script:Colors = @{
    Success = 'Green'
    Warning = 'Yellow'
    Error = 'Red'
    Info = 'Cyan'
    Progress = 'Magenta'
    Debug = 'DarkGray'
}

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

function Initialize-Logging {
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
    
    Write-Log "Service shutdown started at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" "Info"
}

function Write-Log {
    param(
        [string]$Message,
        [string]$Type = "Info"
    )
    
    $timestamp = Get-Date -Format "HH:mm:ss"
    
    switch ($Type) {
        "Success" { Write-Host "✅ [$timestamp] $Message" -ForegroundColor $Colors.Success }
        "Warning" { Write-Host "⚠️  [$timestamp] $Message" -ForegroundColor $Colors.Warning }
        "Error" { Write-Host "❌ [$timestamp] $Message" -ForegroundColor $Colors.Error }
        "Progress" { Write-Host "🔄 [$timestamp] $Message" -ForegroundColor $Colors.Progress }
        "Step" { Write-Host "`n📋 [$timestamp] $Message" -ForegroundColor $Colors.Info }
        "Debug" { Write-Verbose "🔍 [$timestamp] $Message" }
        default { Write-Host "ℹ️  [$timestamp] $Message" -ForegroundColor $Colors.Info }
    }
    
    Add-Content -Path $LogFile -Value "[$timestamp] [$Type] $Message"
}

function Find-ProcessByPattern {
    param(
        [string]$Pattern,
        [string]$PartialMatch = ""
    )
    
    $processes = Get-Process -Name * -ErrorAction SilentlyContinue | Where-Object {
        $processName = $_.ProcessName -or $_.Name
        
        if ($processName -like "*$Pattern*") {
            if ([string]::IsNullOrEmpty($PartialMatch)) {
                return $true
            } else {
                try {
                    $commandLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine
                    return $commandLine -like "*$PartialMatch*"
                }
                catch {
                    return $true
                }
            }
        }
        
        return $false
    }
    
    return $processes
}

function Stop-Process-Gracefully {
    param(
        [System.Diagnostics.Process]$Process,
        [string]$ServiceName,
        [int]$TimeoutSeconds = 10
    )
    
    if (-not $Process -or -not $Process.Id) {
        return $false
    }
    
    try {
        Write-Log "Stopping $ServiceName (PID: $($Process.Id))..." "Progress"
        
        if ($Force) {
            Write-Log "Force terminating $ServiceName..." "Progress"
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
            Write-Log "$ServiceName force terminated" "Success"
            return $true
        }
        
        # Attempt graceful shutdown by sending Ctrl+C
        Write-Log "Attempting graceful shutdown of $ServiceName..." "Progress"
        
        try {
            [System.Diagnostics.Process]::GetProcessById($Process.Id).CloseMainWindow() | Out-Null
        }
        catch {
            Write-Log "Could not close main window, using Stop-Process" "Debug"
            Stop-Process -Id $Process.Id -ErrorAction SilentlyContinue
        }
        
        $elapsed = 0
        $interval = 1
        
        while ($elapsed -lt $TimeoutSeconds) {
            $stillRunning = Get-Process -Id $Process.Id -ErrorAction SilentlyContinue
            
            if (-not $stillRunning) {
                Write-Log "$ServiceName stopped gracefully" "Success"
                return $true
            }
            
            Start-Sleep -Seconds $interval
            $elapsed += $interval
        }
        
        # If still running, force terminate
        Write-Log "Graceful shutdown timeout, force terminating $ServiceName..." "Warning"
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        
        $stillRunning = Get-Process -Id $Process.Id -ErrorAction SilentlyContinue
        if (-not $stillRunning) {
            Write-Log "$ServiceName force terminated" "Success"
            return $true
        } else {
            Write-Log "$ServiceName could not be terminated" "Error"
            return $false
        }
    }
    catch {
        Write-Log "Error stopping $ServiceName : $_" "Error"
        return $false
    }
}

# ============================================================================
# SERVICE SHUTDOWN
# ============================================================================

function Stop-AllServices {
    Write-Log "Looking for running services..." "Step"
    
    $servicesFound = 0
    $servicesStopped = 0
    $stopResults = @()
    
    foreach ($pattern in $Script:ProcessPatterns) {
        $serviceName = $pattern.Name
        $processPattern = $pattern.Pattern
        $partialMatch = $pattern.PartialMatch
        
        Write-Log "Searching for $serviceName processes..." "Progress"
        
        $processes = Find-ProcessByPattern -Pattern $processPattern -PartialMatch $partialMatch
        
        if ($processes) {
            $servicesFound += $processes.Count
            
            foreach ($process in $processes) {
                Write-Log "Found $serviceName (PID: $($process.Id), Name: $($process.ProcessName))" "Debug"
                
                if (Stop-Process-Gracefully -Process $process -ServiceName $serviceName -TimeoutSeconds $Script:GracefulTimeoutSeconds) {
                    $servicesStopped++
                    $stopResults += @{ Service = $serviceName; Status = "Stopped"; PID = $process.Id }
                } else {
                    $stopResults += @{ Service = $serviceName; Status = "Failed"; PID = $process.Id }
                }
            }
        } else {
            Write-Log "$serviceName is not running" "Info"
        }
    }
    
    return @{ Found = $servicesFound; Stopped = $servicesStopped; Results = $stopResults }
}

function Clean-LogFiles {
    if (-not $CleanLogs) {
        return
    }
    
    Write-Log "Cleaning old log files..." "Step"
    
    try {
        $serviceLogDir = Join-Path $LogDir "services"
        
        if (Test-Path $serviceLogDir) {
            # Keep only last 10 log files
            $logFiles = Get-ChildItem $serviceLogDir -Filter "*.log" | Sort-Object CreationTime -Descending | Select-Object -Skip 10
            
            foreach ($file in $logFiles) {
                Remove-Item $file.FullName -Force
                Write-Log "Deleted old log: $($file.Name)" "Debug"
            }
            
            Write-Log "Log cleanup completed" "Success"
        }
    }
    catch {
        Write-Log "Warning: Could not clean log files: $_" "Warning"
    }
}

function Show-Summary {
    param(
        [hashtable]$Results
    )
    
    Write-Host "`n╔════════════════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║                        SHUTDOWN SUMMARY                                   ║" -ForegroundColor Cyan
    Write-Host "╚════════════════════════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan
    
    Write-Log "════════════════════════════════════════════" "Info"
    
    if ($Results.Found -eq 0) {
        Write-Log "No services were running" "Info"
        Write-Host "  No services found running" -ForegroundColor Yellow
    } else {
        Write-Log "Services found: $($Results.Found)" "Info"
        Write-Log "Services stopped: $($Results.Stopped)/$($Results.Found)" "Info"
        
        Write-Host "  Services found: $($Results.Found)" -ForegroundColor Cyan
        Write-Host "  Services stopped: $($Results.Stopped)" -ForegroundColor $(if ($Results.Stopped -eq $Results.Found) { 'Green' } else { 'Yellow' })
        
        if ($Results.Results) {
            Write-Host "`n  Details:" -ForegroundColor Cyan
            foreach ($result in $Results.Results) {
                $statusColor = if ($result.Status -eq "Stopped") { 'Green' } else { 'Red' }
                Write-Host "    - $($result.Service): $($result.Status) (PID: $($result.PID))" -ForegroundColor $statusColor
            }
        }
    }
    
    Write-Log "════════════════════════════════════════════" "Info"
    
    Write-Host "`n📝 Shutdown log: $LogFile`n" -ForegroundColor Cyan
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

function Main {
    try {
        Write-Host "`n╔════════════════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
        Write-Host "║              Stopping Campaign Platform Services                          ║" -ForegroundColor Cyan
        Write-Host "╚════════════════════════════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan
        
        Initialize-Logging
        
        # Stop services
        $results = Stop-AllServices
        
        # Clean logs if requested
        Clean-LogFiles
        
        # Show summary
        Show-Summary -Results $results
        
        # Determine exit code
        if ($results.Found -eq 0) {
            Write-Log "No services to stop" "Info"
            exit 0
        }
        
        if ($results.Stopped -eq $results.Found) {
            Write-Log "All services stopped successfully" "Success"
            exit 0
        } else {
            Write-Log "Some services could not be stopped" "Warning"
            exit 1
        }
    }
    catch {
        Write-Log "FATAL ERROR: $_" "Error"
        Write-Log "Stack trace: $($_.ScriptStackTrace)" "Debug"
        exit 1
    }
}

# Run main
Main
