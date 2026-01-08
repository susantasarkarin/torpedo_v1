# Test Cint Integration Endpoints

$BASE_URL = "http://localhost:8000"
$API_BASE = "$BASE_URL/api/cint"

Write-Host "=== Testing Cint Integration Endpoints ===" -ForegroundColor Cyan
Write-Host ""

# Test 1: Health check
Write-Host "1. Testing /api/cint/health" -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$API_BASE/health" -ErrorAction SilentlyContinue
    Write-Host "✅ Status: $($response.StatusCode)"
    $response.Content | ConvertFrom-Json | ConvertTo-Json | Write-Host
} catch {
    Write-Host "❌ FAILED: $_" -ForegroundColor Red
}
Write-Host ""

# Test 2: List opportunities  
Write-Host "2. Testing /api/cint/opportunities" -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$API_BASE/opportunities?limit=5" -ErrorAction SilentlyContinue
    Write-Host "✅ Status: $($response.StatusCode)"
    $response.Content | ConvertFrom-Json | ConvertTo-Json | Write-Host
} catch {
    Write-Host "❌ FAILED: $_" -ForegroundColor Red
}
Write-Host ""

# Test 3: Test webhook callback
Write-Host "3. Testing /api/cint/webhooks/opportunities" -ForegroundColor Yellow
try {
    $body = @{
        survey_id = 123456
        survey_name = "Test Survey"
        country_language = "eng_us"
        bid_length_of_interview = 15
        revenue_per_interview = @{ value = 1.50; currency_code = "USD" }
        total_remaining = 100
        is_live = $true
        message_reason = "new"
    } | ConvertTo-Json
    
    $response = Invoke-WebRequest -Uri "$API_BASE/webhooks/opportunities" `
        -Method POST `
        -ContentType "application/json" `
        -Body $body `
        -ErrorAction SilentlyContinue
    Write-Host "✅ Status: $($response.StatusCode)"
    $response.Content | ConvertFrom-Json | ConvertTo-Json | Write-Host
} catch {
    Write-Host "❌ FAILED: $_" -ForegroundColor Red
}
Write-Host ""

# Test 4: Build entry link URL
Write-Host "4. Testing /api/cint/build-entry-link/123456" -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$API_BASE/build-entry-link/123456?respondent_id=RESP123&country_code=us" `
        -Method POST `
        -ErrorAction SilentlyContinue
    Write-Host "✅ Status: $($response.StatusCode)"
    $response.Content | ConvertFrom-Json | ConvertTo-Json | Write-Host
} catch {
    Write-Host "❌ FAILED: $_" -ForegroundColor Red
}
Write-Host ""

Write-Host "=== Tests Complete ===" -ForegroundColor Cyan
