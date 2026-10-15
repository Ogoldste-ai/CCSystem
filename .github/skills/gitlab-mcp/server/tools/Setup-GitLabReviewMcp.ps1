[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$serverRoot = Split-Path -Parent $PSScriptRoot

function Get-UserEnvironmentValue {
    param([Parameter(Mandatory)][string]$Name)

    return [Environment]::GetEnvironmentVariable($Name, "User")
}

function Set-UserEnvironmentValue {
    param(
        [Parameter(Mandatory)][string]$Name,
        [AllowEmptyString()][string]$Value
    )

    [Environment]::SetEnvironmentVariable($Name, $Value, "User")
    Set-Item -Path "Env:$Name" -Value $Value
}

function Read-OptionalValue {
    param(
        [Parameter(Mandatory)][string]$Prompt,
        [string]$CurrentValue = ""
    )

    if ($CurrentValue) {
        $value = Read-Host "$Prompt [$CurrentValue]"
        if ($value) {
            return $value.Trim()
        }
        return $CurrentValue
    }
    return (Read-Host $Prompt).Trim()
}

function Read-Token {
    $secureToken = Read-Host "GitLab token (input hidden; leave blank to keep the current token)" -AsSecureString
    if ($secureToken.Length -eq 0) {
        return ""
    }

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Configure-GitLab {
    Write-Host "`nStep 1 of 4: GitLab connection settings" -ForegroundColor Cyan
    $baseUrl = Read-OptionalValue -Prompt "GitLab API URL" -CurrentValue (Get-UserEnvironmentValue "GITLAB_BASE_URL")
    if (-not $baseUrl) {
        throw "GitLab API URL is required, for example https://gitlab.example.com/api/v4."
    }
    $baseUrl = $baseUrl.TrimEnd("/")
    if (-not $baseUrl.EndsWith("/api/v4")) {
        $baseUrl = "$baseUrl/api/v4"
    }

    $token = Read-Token
    if ($token) {
        Set-UserEnvironmentValue -Name "GITLAB_TOKEN" -Value $token
    }
    elseif (-not (Get-UserEnvironmentValue "GITLAB_TOKEN")) {
        throw "A GitLab token is required. Create one with the api scope, then run this step again."
    }

    $defaultProject = Read-OptionalValue -Prompt "Default project (optional, group/project)" `
        -CurrentValue (Get-UserEnvironmentValue "GITLAB_DEFAULT_PROJECT")
    $enableWrites = Read-Host "Enable write tools (create, edit, delete, or resolve GitLab items)? [y/N]"

    Set-UserEnvironmentValue -Name "GITLAB_BASE_URL" -Value $baseUrl
    Set-UserEnvironmentValue -Name "GITLAB_DEFAULT_PROJECT" -Value $defaultProject
    if ($enableWrites -match "^(?i:y|yes)$") {
        Set-UserEnvironmentValue -Name "GITLAB_ALLOW_WRITE" -Value "1"
    }
    else {
        Set-UserEnvironmentValue -Name "GITLAB_ALLOW_WRITE" -Value ""
    }

    Write-Host "Saved user-scoped GitLab settings. The token was not displayed or written to an MCP config file." `
        -ForegroundColor Green
}

function Install-Server {
    Write-Host "`nStep 2 of 4: Installing the local GitLab MCP package" -ForegroundColor Cyan
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "Python 3.12 or newer is required but 'python' was not found on PATH."
    }
    & python -m pip install -e $serverRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Package installation failed."
    }
    Write-Host "Installed gitlab-review-mcp in editable mode." -ForegroundColor Green
}

function Test-Connection {
    Write-Host "`nStep 3 of 4: Verifying GitLab access" -ForegroundColor Cyan
    $script = @'
from gitlab_mcp.client import GitLabClient, GitLabConfig

client = GitLabClient(GitLabConfig.from_env())
try:
    health = client.health()
    print(f"Connected as {health['user']['username']}; write_enabled={health['write_enabled']}")
finally:
    client.close()
'@
    $script | & python -
    if ($LASTEXITCODE -ne 0) {
        throw "Connection verification failed. Check the API URL, token scope, VPN, and certificate trust."
    }
}

function Show-ClientSteps {
    Write-Host "`nStep 4 of 4: Register the installed server with your clients" -ForegroundColor Cyan
    $launcher = (Get-Command gitlab-review-mcp -ErrorAction Stop).Source

    Write-Host "`nCopilot CLI" -ForegroundColor Yellow
    Write-Host "1. Start Copilot CLI and run /mcp."
    Write-Host "2. Add a local server named gitlab-review using this command:"
    Write-Host "   $launcher"
    Write-Host "3. Reload it with /mcp reload, then call health()."

    Write-Host "`nVS Code" -ForegroundColor Yellow
    Write-Host "1. Open the Command Palette and choose 'MCP: Add Server'."
    Write-Host "2. Choose stdio, name it gitlab-review, and use this command:"
    Write-Host "   $launcher"
    Write-Host "3. Restart or reload VS Code, then call health()."

    Write-Host "`nThe server inherits GITLAB_BASE_URL, GITLAB_DEFAULT_PROJECT, and GITLAB_TOKEN from your user environment." `
        -ForegroundColor DarkGray
}

while ($true) {
    Write-Host "`nGitLab Review MCP setup" -ForegroundColor Cyan
    Write-Host "1. Configure GitLab settings"
    Write-Host "2. Install/update the MCP package"
    Write-Host "3. Test the GitLab connection"
    Write-Host "4. Show Copilot CLI and VS Code registration steps"
    Write-Host "5. Run the full setup"
    Write-Host "0. Exit"

    switch (Read-Host "Choose an option") {
        "1" { Configure-GitLab }
        "2" { Install-Server }
        "3" { Test-Connection }
        "4" { Show-ClientSteps }
        "5" {
            Configure-GitLab
            Install-Server
            Test-Connection
            Show-ClientSteps
        }
        "0" { break }
        default { Write-Warning "Choose 0 through 5." }
    }
}
