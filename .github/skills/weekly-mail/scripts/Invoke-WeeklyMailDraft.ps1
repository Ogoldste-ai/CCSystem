<#
.SYNOPSIS
    Run the weekly-mail skill headlessly and leave a draft in Outlook.

.DESCRIPTION
    Intended for Task Scheduler on Wednesday mornings. Invokes Copilot CLI in
    non-interactive mode against the weekly-mail skill, which gathers the
    week's work and saves a reply-all draft.

    Nothing is ever sent: the skill is draft-only, and this wrapper adds no
    send capability. The user still reviews and clicks Send in Outlook.

    Output is logged, because a scheduled task that fails silently is worse
    than no scheduled task at all.

.PARAMETER WhatIfPrompt
    Print the prompt and exit without calling Copilot. Useful for checking the
    wiring before trusting it to a schedule.

.EXAMPLE
    .\Invoke-WeeklyMailDraft.ps1 -WhatIfPrompt

.EXAMPLE
    # Register it for 08:30 every Wednesday (see Register-WeeklyMailTask.ps1)
    .\Invoke-WeeklyMailDraft.ps1
#>
[CmdletBinding()]
param(
    [string]$WorkingDirectory = 'C:\CCSystem',
    [string]$LogDirectory = "$env:LOCALAPPDATA\weekly-mail\logs",
    [int]$KeepLogs = 12,
    [switch]$WhatIfPrompt
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$prompt = @'
Use the weekly-mail skill to prepare this week's status mail.

Gather the last 7 days from all available sources, derive the next WW number
from the previous weekly mail, and save a reply-all DRAFT in Outlook.

Do not send anything. If the previous weekly mail is more than 10 days old,
or the WW number is ambiguous, stop and write what you found to the output
instead of guessing.
'@

if ($WhatIfPrompt) {
    Write-Host $prompt
    return
}

if (-not (Test-Path $LogDirectory)) {
    New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
}
$log = Join-Path $LogDirectory ("weekly-mail-{0:yyyy-MM-dd-HHmm}.log" -f (Get-Date))

function Write-Log {
    param([string]$Message)
    $line = "[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $Message
    $line | Tee-Object -FilePath $log -Append | Write-Host
}

Write-Log "Starting weekly mail draft run."
Write-Log "Working directory: $WorkingDirectory"

$copilot = Get-Command copilot -ErrorAction SilentlyContinue
if (-not $copilot) {
    Write-Log "FAILED: 'copilot' is not on PATH for this account."
    exit 1
}

# Outlook COM is only reachable from the user's interactive session, and the
# skill silently loses its mail/calendar sources without it. Say so loudly
# rather than producing a draft with three empty sections.
$outlook = Get-Process -Name 'OUTLOOK' -ErrorAction SilentlyContinue
if (-not $outlook) {
    Write-Log "WARNING: Outlook is not running. COM will try to start it; if this task is running without an interactive desktop session it will fail."
}

$previousPreference = $ErrorActionPreference
Push-Location $WorkingDirectory
try {
    Write-Log "Invoking Copilot CLI..."
    # Once native stderr is redirected with 2>&1 it arrives as ErrorRecord
    # objects, which $ErrorActionPreference = 'Stop' turns into terminating
    # errors - failing the run even when the CLI finished fine. Relax the
    # preference for the call and judge success by the exit code instead.
    $ErrorActionPreference = 'Continue'
    & $copilot.Source `
        --prompt $prompt `
        --allow-all-tools `
        --add-dir $WorkingDirectory 2>&1 |
        ForEach-Object { $_.ToString() } |
        Tee-Object -FilePath $log -Append

    $code = $LASTEXITCODE
    $ErrorActionPreference = $previousPreference
    if ($code -eq 0) {
        Write-Log "Done. Check the Outlook Drafts folder and review before sending."
    }
    else {
        Write-Log "FAILED: copilot exited with code $code."
    }
}
catch {
    Write-Log "FAILED: $($_.Exception.Message)"
    $code = 1
}
finally {
    $ErrorActionPreference = $previousPreference
    Pop-Location
}

# Keep the log directory from growing without bound.
Get-ChildItem $LogDirectory -Filter 'weekly-mail-*.log' |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip $KeepLogs |
    Remove-Item -Force -ErrorAction SilentlyContinue

exit $code
