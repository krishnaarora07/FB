# Football Pipeline — Task Scheduler Setup
# Run this script ONCE as Administrator to register both daily runs.
#
# Right-click PowerShell → "Run as Administrator", then:
#   Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
#   C:\Users\krish\Documents\fb\setup_schedule.ps1

$ProjectDir = "C:\Users\krish\Documents\fb"
$BatchFile  = "$ProjectDir\run_pipeline.bat"
$Python     = "C:\Python314\python.exe"

# ── Verify prereqs ──────────────────────────────────────────────────────
if (-not (Test-Path $BatchFile)) {
    Write-Error "Batch file not found: $BatchFile"; exit 1
}
if (-not (Test-Path $Python)) {
    Write-Error "Python not found: $Python. Update the path in this script."; exit 1
}

Write-Host "Setting up Football Pipeline scheduled tasks..." -ForegroundColor Cyan

# ── Remove old tasks if they exist ──────────────────────────────────────
foreach ($name in @("FootballPipeline_Morning", "FootballPipeline_Evening")) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "  Removed existing task: $name" -ForegroundColor Yellow
    }
}

# ── Task action: run the batch launcher ─────────────────────────────────
$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$BatchFile`"" `
    -WorkingDirectory $ProjectDir

# Run as current user, only when logged on
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable `
    -WakeToRun:$false `
    -MultipleInstances IgnoreNew

# ── Morning: 9:00 AM IST every day ──────────────────────────────────────
$TriggerMorning = New-ScheduledTaskTrigger -Daily -At "09:00"
Register-ScheduledTask `
    -TaskName   "FootballPipeline_Morning" `
    -Action     $Action `
    -Trigger    $TriggerMorning `
    -Principal  $Principal `
    -Settings   $Settings `
    -Description "Football pipeline morning run — 9:00 AM IST (captures European overnight news)" `
    -Force | Out-Null
Write-Host "  Registered: FootballPipeline_Morning — daily at 9:00 AM" -ForegroundColor Green

# ── Evening: 8:00 PM IST every day ──────────────────────────────────────
$TriggerEvening = New-ScheduledTaskTrigger -Daily -At "20:00"
Register-ScheduledTask `
    -TaskName   "FootballPipeline_Evening" `
    -Action     $Action `
    -Trigger    $TriggerEvening `
    -Principal  $Principal `
    -Settings   $Settings `
    -Description "Football pipeline evening run — 8:00 PM IST (global peak viewing: UK afternoon, Americas morning)" `
    -Force | Out-Null
Write-Host "  Registered: FootballPipeline_Evening — daily at 8:00 PM" -ForegroundColor Green

# ── Verify ───────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Scheduled Tasks:" -ForegroundColor Cyan
Get-ScheduledTask | Where-Object { $_.TaskName -like "FootballPipeline*" } | ForEach-Object {
    $info = $_ | Get-ScheduledTaskInfo
    Write-Host ("  [{0}]  Next run: {1}" -f $_.TaskName, $info.NextRunTime) -ForegroundColor White
}

Write-Host ""
Write-Host "Done! The pipeline will now run automatically twice a day." -ForegroundColor Green
Write-Host "Logs saved to: $ProjectDir\logs\" -ForegroundColor Gray
