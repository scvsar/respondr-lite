# PowerShell script to test webhook with GroupMe messages
param(
    [switch]$Sample,  # Use -Sample to send only sample messages
    [string]$Url = "http://localhost:8000/webhook"  # Default webhook URL
)

Write-Host "GroupMe Webhook Test Runner" -ForegroundColor Green
Write-Host "=========================="

# Check if we're in the right directory
if (-not (Test-Path "groupme_test_messages.json")) {
    Write-Host "Error: groupme_test_messages.json not found" -ForegroundColor Red
    Write-Host "Please run this script from the benchmark directory" -ForegroundColor Red
    exit 1
}

# Install dependencies if needed
try {
    pip show requests | Out-Null
} catch {
    Write-Host "Installing required dependencies..." -ForegroundColor Yellow
    pip install -r requirements.txt
}

# Choose which script to run
if ($Sample) {
    Write-Host "Running sample message test..." -ForegroundColor Cyan
    python send_sample_messages.py
} else {
    Write-Host "Running full message test..." -ForegroundColor Cyan
    Write-Host "This will send all test messages. Use -Sample for a quick test." -ForegroundColor Yellow
    python send_test_messages.py
}

Write-Host "`nTest completed!" -ForegroundColor Green