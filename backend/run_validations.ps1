# Nexus V0 — TestClient Validation Sequence (PowerShell Orchestrator)
# Run from: D:\Tech\Nexus\backend
# Prerequisites: Python 3.9+, backend running on http://localhost:8000, requests installed
#
# Usage:
#   cd D:\Tech\Nexus\backend
#   .venv\Scripts\Activate.ps1
#   python test_client_validation.py
#
# Or via PowerShell directly:
#   cd D:\Tech\Nexus\backend
#   python -c "import requests" 2>$null; if ($LASTEXITCODE -ne 0) { pip install requests }
#   python test_client_validation.py
#   $EXIT_CODE = $LASTEXITCODE
#   if ($EXIT_CODE -eq 0) { Write-Host "ALL VALIDATIONS PASSED" -ForegroundColor Green } else { Write-Host "VALIDATIONS FAILED" -ForegroundColor Red; exit $EXIT_CODE }

# ── Pre-flight checks ──────────────────────────────────────────────
$ErrorActionPreference = "Stop"
$BackendUrl = "http://localhost:8000"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "NEXUS V0 — TestClient Validation Sequence (PowerShell)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# Check backend is reachable
try {
    $health = Invoke-RestMethod -Uri "$BackendUrl/health" -Method GET -TimeoutSec 10 -ErrorAction Stop
    Write-Host "[PASS] Backend reachable at $BackendUrl" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] Backend NOT reachable at $BackendUrl — $_" -ForegroundColor Red
    exit 1
}

# Ensure requests is available for Python
python -c "import requests" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[INFO] Installing requests package..." -ForegroundColor Yellow
    pip install requests | Out-Null
}

# ── Execute Python validation ──────────────────────────────────────
Write-Host ""
Write-Host "Running Python validation suite..." -ForegroundColor Yellow
python test_client_validation.py
$EXIT_CODE = $LASTEXITCODE

if ($EXIT_CODE -eq 0) {
    Write-Host ""
    Write-Host "ALL VALIDATIONS PASSED" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "VALIDATIONS FAILED (exit code: $EXIT_CODE)" -ForegroundColor Red
}

exit $EXIT_CODE
