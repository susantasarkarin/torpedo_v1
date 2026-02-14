# ============================================================================
# AI Cold Outreach Platform - Health Check Script (v2.0)
# ============================================================================

param([switch]$Monitor, [int]$Interval = 10, [switch]$Verbose)

$ErrorActionPreference = "Continue"
$Script:ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script:BackendPort = 8000
$Script:FrontendPort = 5173
$Script:MongoDBPort = 27017
$Script:HealthStatus = @{}

$Colors = @{Success = 'Green'; Warning = 'Yellow'; Error = 'Red'; Info = 'Cyan'; Progress = 'Magenta'}

function Write-Log { param([string]$Message, [string]$Type = "Info")
    $timestamp = Get-Date -Format "HH:mm:ss"
    switch ($Type) {
        "Success" { Write-Host " $Message" -ForegroundColor $Colors.Success }
        "Warning" { Write-Host "  $Message" -ForegroundColor $Colors.Warning }
        "Error" { Write-Host " $Message" -ForegroundColor $Colors.Error }
        "Progress" { Write-Host " $Message" -ForegroundColor $Colors.Progress }
        "Step" { Write-Host "`n $Message" -ForegroundColor $Colors.Info }
        "Header" { Write-Host "`n $($Message.PadRight(76)) `n" -ForegroundColor Cyan }
        default { Write-Host "ℹ  $Message" -ForegroundColor $Colors.Info }
    }
}

function Test-PortInUse { param([int]$Port, [string]$Host = "127.0.0.1")
    try { $c = New-Object System.Net.Sockets.TcpClient($Host, $Port); $c.Close(); return $true }
    catch { return $false }
}

function Test-ServiceHealth { param([string]$ServiceName, [string]$Url, [int]$Port)
    Write-Log "Checking $ServiceName on port $Port..." "Progress"
    if (-not (Test-PortInUse -Port $Port)) {
        Write-Log "   $ServiceName: Down" "Error"
        $Script:HealthStatus[$ServiceName] = "Down"
        return $false
    }
    try {
        $response = Invoke-WebRequest -Uri "$Url/health" -TimeoutSec 5 -EA SilentlyContinue
        if ($response.StatusCode -eq 200) {
            Write-Log "   $ServiceName: Healthy" "Success"
            $Script:HealthStatus[$ServiceName] = " Healthy"
            return $true
        }
    }
    catch {
        Write-Log "    $ServiceName: Running (port open)" "Warning"
        $Script:HealthStatus[$ServiceName] = "  Running"
        return $true
    }
}

function Test-DatabaseHealth { param([string]$DatabaseType, [int]$Port, [string]$Host = "127.0.0.1")
    Write-Log "Checking $DatabaseType..." "Progress"
    if (-not (Test-PortInUse -Port $Port -Host $Host)) {
        Write-Log "   $DatabaseType: Down" "Error"
        $Script:HealthStatus[$DatabaseType] = "Down"
        return $false
    }
    Write-Log "   $DatabaseType: Running" "Success"
    $Script:HealthStatus[$DatabaseType] = " Running"
    return $true
}

function Show-HealthReport {
    Clear-Host
    Write-Log "Campaign Platform Health Status Report" "Header"
    Write-Log "Check Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" "Info"
    Write-Host "`n SERVICES" -ForegroundColor Cyan
    Write-Host "" -ForegroundColor Cyan
    
    foreach ($service in $Script:HealthStatus.GetEnumerator()) {
        Write-Host "  $($service.Key): $($service.Value)" -ForegroundColor Cyan
    }
    Write-Host ""
    
    if ($Monitor) {
        Write-Host "   Next refresh in $Interval seconds (Ctrl+C to stop)..." -ForegroundColor Yellow
        Write-Host ""
    }
}

try {
    Write-Log "Starting health check..." "Step"
    Test-ServiceHealth -ServiceName "Backend API" -Url "http://localhost:8000" -Port $Script:BackendPort | Out-Null
    Test-ServiceHealth -ServiceName "Frontend" -Url "http://localhost:5173" -Port $Script:FrontendPort | Out-Null
    Test-DatabaseHealth -DatabaseType "MongoDB" -Port $Script:MongoDBPort | Out-Null
    
    Show-HealthReport
    
    if ($Monitor) {
        $count = 1
        while ($true) {
            Start-Sleep -Seconds $Interval
            $Script:HealthStatus.Clear()
            Test-ServiceHealth -ServiceName "Backend API" -Url "http://localhost:8000" -Port $Script:BackendPort | Out-Null
            Test-ServiceHealth -ServiceName "Frontend" -Url "http://localhost:5173" -Port $Script:FrontendPort | Out-Null
            Test-DatabaseHealth -DatabaseType "MongoDB" -Port $Script:MongoDBPort | Out-Null
            Show-HealthReport
            $count++
        }
    }
    
    Write-Log "Health check completed" "Success"
    exit 0
}
catch { Write-Log "ERROR: $_" "Error"; exit 1 }
