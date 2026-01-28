# ============================================================================
# AI Cold Outreach Platform - Service Startup Script (v2.0)
# ============================================================================

param([switch]$NoFrontend, [switch]$NoCelery, [switch]$OpenBrowser, [switch]$Verbose)

$ErrorActionPreference = "Continue"
$Script:ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script:BackendDir = Join-Path $ProjectRoot "backend"
$Script:FrontendDir = Join-Path $ProjectRoot "Campaign_platform"
$Script:BackendPort = 8000
$Script:FrontendPort = 5173
$Script:ProcessIds = @{}
$Script:ServiceStatus = @{}

$Colors = @{Success = 'Green'; Warning = 'Yellow'; Error = 'Red'; Info = 'Cyan'; Progress = 'Magenta'}

function Write-Log { param([string]$Message, [string]$Type = "Info")
    $timestamp = Get-Date -Format "HH:mm:ss"
    switch ($Type) {
        "Success" { Write-Host " [$timestamp] $Message" -ForegroundColor $Colors.Success }
        "Warning" { Write-Host "  [$timestamp] $Message" -ForegroundColor $Colors.Warning }
        "Error" { Write-Host " [$timestamp] $Message" -ForegroundColor $Colors.Error }
        "Progress" { Write-Host " [$timestamp] $Message" -ForegroundColor $Colors.Progress }
        "Step" { Write-Host "`n [$timestamp] $Message" -ForegroundColor $Colors.Info }
        default { Write-Host "ℹ  [$timestamp] $Message" -ForegroundColor $Colors.Info }
    }
}

function Test-PortInUse { param([int]$Port)
    try { $c = New-Object System.Net.Sockets.TcpClient("127.0.0.1", $Port); $c.Close(); return $true }
    catch { return $false }
}

function Wait-ForPort { param([int]$Port, [int]$TimeoutSeconds = 30, [string]$ServiceName = "Service")
    $elapsed = 0
    Write-Log "Waiting for $ServiceName on port $Port..." "Progress"
    while ($elapsed -lt $TimeoutSeconds) {
        if (Test-PortInUse -Port $Port) { Write-Log "$ServiceName ready" "Success"; return $true }
        Start-Sleep -Seconds 1; $elapsed += 1
    }
    Write-Log "$ServiceName timeout" "Error"; return $false
}

function Get-PythonExe {
    $venv = Join-Path $Script:BackendDir "venv\Scripts\python.exe"
    if (Test-Path $venv) { return $venv }
    return "python"
}

function Start-BackendService {
    Write-Log "Starting Backend API..." "Step"
    if (-not (Test-Path (Join-Path $Script:BackendDir "main.py"))) { Write-Log "main.py not found" "Error"; return $false }
    
    $logFile = Join-Path $Script:ProjectRoot "logs\services\backend.log"
    $process = Start-Process -FilePath (Get-PythonExe) -ArgumentList @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", $Script:BackendPort, "--reload") -WorkingDirectory $Script:BackendDir -RedirectStandardOutput $logFile -RedirectStandardError $logFile -NoNewWindow -PassThru
    
    if ($process -and $process.Id) {
        $Script:ProcessIds["backend"] = $process.Id
        if (Wait-ForPort -Port $Script:BackendPort -ServiceName "Backend") {
            $Script:ServiceStatus["Backend"] = " Running (http://localhost:$($Script:BackendPort))"
            return $true
        }
    }
    $Script:ServiceStatus["Backend"] = " Failed"
    return $false
}

function Start-FrontendService {
    if ($NoFrontend) { return $true }
    Write-Log "Starting Frontend..." "Step"
    if (-not (Test-Path (Join-Path $Script:FrontendDir "package.json"))) { return $true }
    
    $logFile = Join-Path $Script:ProjectRoot "logs\services\frontend.log"
    $process = Start-Process -FilePath "npm" -ArgumentList @("run", "dev") -WorkingDirectory $Script:FrontendDir -RedirectStandardOutput $logFile -RedirectStandardError $logFile -NoNewWindow -PassThru
    
    if ($process -and $process.Id) {
        $Script:ProcessIds["frontend"] = $process.Id
        if (Wait-ForPort -Port $Script:FrontendPort -ServiceName "Frontend") {
            $Script:ServiceStatus["Frontend"] = " Running (http://localhost:$($Script:FrontendPort))"
            return $true
        }
    }
    $Script:ServiceStatus["Frontend"] = "  Check logs"
    return $true
}

function Start-CeleryService {
    if ($NoCelery) { return $true }
    Write-Log "Starting Celery worker..." "Step"
    
    $logFile = Join-Path $Script:ProjectRoot "logs\services\celery.log"
    $process = Start-Process -FilePath (Get-PythonExe) -ArgumentList @("-m", "celery", "-A", "celery_app", "worker", "--loglevel=info") -WorkingDirectory $Script:BackendDir -RedirectStandardOutput $logFile -RedirectStandardError $logFile -NoNewWindow -PassThru
    
    if ($process -and $process.Id) {
        $Script:ProcessIds["celery"] = $process.Id
        Start-Sleep -Seconds 2
        $Script:ServiceStatus["Celery"] = " Running"
        Write-Log "Celery worker started" "Success"
        return $true
    }
    return $true
}

$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { foreach ($pid in $Script:ProcessIds.Values) { Stop-Process -Id $pid -Force -EA SilentlyContinue } }

try {
    Write-Host "`n Starting Campaign Platform Services`n" -ForegroundColor Cyan
    if (-not (Test-Path (Join-Path $Script:ProjectRoot "logs\services"))) { New-Item -ItemType Directory -Path (Join-Path $Script:ProjectRoot "logs\services") -Force | Out-Null }
    
    $b = Start-BackendService; Start-Sleep -Seconds 1
    $f = Start-FrontendService
    $c = Start-CeleryService
    
    Write-Host "`n" -ForegroundColor Cyan
    Write-Host "                        SERVICES RUNNING                                    " -ForegroundColor Cyan
    Write-Host "`n" -ForegroundColor Cyan
    
    foreach ($status in $Script:ServiceStatus.GetEnumerator()) {
        Write-Host "  $($status.Key): $($status.Value)" -ForegroundColor Cyan
    }
    
    Write-Host "`n  Run '.\stop_services.ps1' to stop all services`n" -ForegroundColor Yellow
    if (-not $b) { exit 1 }
    
    while ($true) { Start-Sleep -Seconds 30 }
}
catch { Write-Log "ERROR: $_" "Error"; exit 1 }
