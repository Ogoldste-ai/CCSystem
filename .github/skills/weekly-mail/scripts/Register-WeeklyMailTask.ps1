<#
.SYNOPSIS
    Register (or remove) the Wednesday scheduled task for the weekly mail draft.

.DESCRIPTION
    Creates a Task Scheduler entry that runs Invoke-WeeklyMailDraft.ps1 every
    Wednesday. The task is deliberately configured to run **only when the user
    is logged on**: Outlook exposes COM solely inside an interactive desktop
    session, so a task running in the background would produce a draft with
    empty mail and calendar sections.

    Nothing is sent by this task. It leaves a draft for review.

.PARAMETER Time
    Local time to run, 24h HH:mm. Defaults to 08:30.

.PARAMETER Unregister
    Remove the task instead of creating it.

.EXAMPLE
    .\Register-WeeklyMailTask.ps1 -Time 09:00

.EXAMPLE
    .\Register-WeeklyMailTask.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [string]$TaskName = 'Weekly Mail Draft',
    [string]$Time = '08:30',
    [switch]$Unregister
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
    return
}

$script = Join-Path $PSScriptRoot 'Invoke-WeeklyMailDraft.ps1'
if (-not (Test-Path $script)) {
    throw "Cannot find $script"
}

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory 'C:\CCSystem'

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Wednesday -At $Time

# Interactive token, not S4U or a stored password: Outlook COM needs the real
# desktop session. RunLevel stays Limited - this task has no reason to elevate.
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Drafts the weekly WW status mail in Outlook. Never sends; leaves a draft for review.' `
    -Force | Out-Null

Write-Host "Registered '$TaskName' for Wednesdays at $Time."
Write-Host "It runs only while you are logged on, because Outlook COM needs your desktop session."
Write-Host "Run it now with: Start-ScheduledTask -TaskName '$TaskName'"
