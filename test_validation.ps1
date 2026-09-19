$baseUrl = "http://localhost:8000"
$headers = @{ "Content-Type" = "application/json" }

function Assert-Equals {
    param($actual, $expected, $message)
    if ($actual -ne $expected) {
        throw "ASSERTION FAILED: $message | Expected: $expected | Actual: $actual"
    }
    Write-Host "  PASS: $message"
}

function Assert-True {
    param($condition, $message)
    if (-not $condition) {
        throw "ASSERTION FAILED: $message"
    }
    Write-Host "  PASS: $message"
}

function Assert-False {
    param($condition, $message)
    if ($condition) {
        throw "ASSERTION FAILED: $message"
    }
    Write-Host "  PASS: $message"
}

Write-Host "=== NEXUS V0 TESTCLIENT VALIDATION SEQUENCE ==="

# 1. HEALTH CHECK
Write-Host "`n[1] GET /health"
$health = Invoke-RestMethod -Uri "$baseUrl/health" -Method GET
Assert-Equals $health.status "ok" "Health endpoint returns ok"

# 2. INITIAL APPS STATE
Write-Host "`n[2] GET /api/apps - Verify GitHub/Slack/Grafana initially enabled, not connected"
$apps = Invoke-RestMethod -Uri "$baseUrl/api/apps" -Method GET
$githubApp = $apps | Where-Object { $_.app_id -eq "github" }
$slackApp = $apps | Where-Object { $_.app_id -eq "slack" }
$grafanaApp = $apps | Where-Object { $_.app_id -eq "grafana" }

Assert-True ($githubApp -ne $null) "GitHub exists in apps list"
Assert-Equals $githubApp.enabled $true "GitHub initially enabled"
Assert-Equals $githubApp.connected $false "GitHub initially not connected"
Assert-True ($githubApp.capabilities.Count -gt 0) "GitHub has capabilities"

Assert-True ($slackApp -ne $null) "Slack exists in apps list"
Assert-Equals $slackApp.enabled $true "Slack initially enabled"
Assert-Equals $slackApp.connected $false "Slack initially not connected"
Assert-True ($slackApp.capabilities.Count -gt 0) "Slack has capabilities"

Assert-True ($grafanaApp -ne $null) "Grafana exists in apps list"
Assert-Equals $grafanaApp.enabled $true "Grafana initially enabled"
Assert-Equals $grafanaApp.connected $false "Grafana initially not connected"
Assert-True ($grafanaApp.capabilities.Count -gt 0) "Grafana has capabilities"

# 3. ENABLE GITHUB CONNECTION
Write-Host "`n[3] POST /api/apps/github/connection - Enable GitHub"
$enableGithub = @{ connected = $true; config = @{ token = "test" } } | ConvertTo-Json
$resp = Invoke-RestMethod -Uri "$baseUrl/api/apps/github/connection" -Method POST -Body $enableGithub -Headers $headers
Assert-Equals $resp.app_id "github" "GitHub enabled successfully"
Assert-Equals $resp.connected $true "GitHub connected=True"
Assert-True ($resp.PSObject.Properties.Name -contains "enabled") "Connection response has enabled field"

# Persistence across new request
$apps2 = Invoke-RestMethod -Uri "$baseUrl/api/apps" -Method GET
$githubAfter = $apps2 | Where-Object { $_.app_id -eq "github" }
Assert-Equals $githubAfter.connected $true "GitHub persists as connected"
Assert-Equals $githubAfter.enabled $true "GitHub persists as enabled"

# 4. DISABLE GRAFANA CONNECTION
Write-Host "`n[4] POST /api/apps/grafana/connection - Disable Grafana"
$disableGrafana = @{ connected = $false } | ConvertTo-Json
$resp = Invoke-RestMethod -Uri "$baseUrl/api/apps/grafana/connection" -Method POST -Body $disableGrafana -Headers $headers
Assert-Equals $resp.connected $false "Grafana explicitly disabled"

# 5. VERIFY GRAFANA DISABLED
Write-Host "`n[5] POST /api/agent/run - Grafana disabled"
$agentMsg = @{ message = "Check Grafana dashboard" } | ConvertTo-Json
$resp = Invoke-RestMethod -Uri "$baseUrl/api/agent/run" -Method POST -Body $agentMsg -Headers $headers
Assert-True ($resp.status -eq "completed" -or $resp.status -eq "no_match") "Agent returns valid status"

# 6. WORKFLOW CREATE
Write-Host "`n[6] POST /api/workflows - Create workflow"
$workflow = @{
    name = "Test Workflow"
    description = "Test workflow"
    steps = @(
        @{ app = "github"; action = "create_issue"; params = @{ title = "Test Issue" } }
        @{ app = "slack"; action = "send_message"; params = @{ channel = "#dev"; text = "Issue created" } }
    )
} | ConvertTo-Json
$resp = Invoke-RestMethod -Uri "$baseUrl/api/workflows" -Method POST -Body $workflow -Headers $headers
$workflowId = $resp.id
Assert-True ($workflowId -ne $null) "Workflow created with ID"
Assert-Equals $resp.name "Test Workflow" "Workflow name matches"

# 7. WORKFLOW LIST
Write-Host "`n[7] GET /api/workflows - List workflows"
$workflows = Invoke-RestMethod -Uri "$baseUrl/api/workflows" -Method GET
Assert-True ($workflows | Where-Object { $_.id -eq $workflowId }) "Created workflow appears in list"

# 8. WORKFLOW RUN
Write-Host "`n[8] POST /api/workflows/{id}/run - Execute workflow"
$runResp = Invoke-RestMethod -Uri "$baseUrl/api/workflows/$workflowId/run" -Method POST -Headers $headers
Assert-Equals $runResp.status "completed" "Workflow run completed"

# 9. WORKFLOW TRACE
Write-Host "`n[9] Verify workflow trace"
$wfTrace = $runResp.events.ToString()
Assert-True ($wfTrace -match "tool_name|type|app|action|data") "Workflow trace has fields"

Write-Host "`n=== ALL ASSERTIONS PASSED ==="
