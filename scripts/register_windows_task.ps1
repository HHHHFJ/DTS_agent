param(
    [string]$TaskName = "DTS Guardian Sync",
    [string]$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path,
    [string]$Python = "python",
    [string]$FetchScript = "",
    [int]$IntervalMinutes = 60
)

$ErrorActionPreference = "Stop"

if ($FetchScript -eq "") {
    $FetchScript = Join-Path $ProjectRoot "dts_agent\dts_tools\dts_data_fetch.py"
}

$argumentParts = @(
    "-m", "dts_agent",
    "--root", "`"$ProjectRoot`"",
    "sync",
    "--mode", "scheduled",
    "--fetch-script", "`"$FetchScript`""
)
$arguments = $argumentParts -join " "

$action = New-ScheduledTaskAction -Execute $Python -Argument $arguments -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Sync DTS Excel data into the local DTS Guardian SQLite knowledge base." `
    -Force | Out-Null

Write-Host "Registered task '$TaskName'."
Write-Host "ProjectRoot: $ProjectRoot"
Write-Host "FetchScript: $FetchScript"
Write-Host "IntervalMinutes: $IntervalMinutes"
