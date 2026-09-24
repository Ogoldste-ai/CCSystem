<#
.SYNOPSIS
    Collect this week's git activity for the weekly status mail.

.DESCRIPTION
    Runs `git log` over the work repository and its submodules, filtered to the
    current user, and emits compact JSON grouped by work area.

    The "module" field is the point of this script. Raw commit subjects like
    "update builder" are useless in a status mail; knowing that five such
    commits all landed in EC/Modules/I3C is what makes the mail write itself.

.PARAMETER RepoPath
    Repository to scan. Defaults to the ec_accurev_git work repo.

.PARAMETER Days
    How far back to look. Defaults to 7.

.PARAMETER Author
    Author match passed to `git log --author` (a regex, so alternation works).
    Defaults to the identities configured in git plus the local account name,
    because this user commits under both ogoldste@ and oren.goldstein@.

.PARAMETER IncludeMerges
    Keep merge commits. Off by default: "Merge branch 'x' into 'master'" is
    noise in a status report.

.EXAMPLE
    .\Get-WeeklyActivity.ps1 -Days 7 | ConvertFrom-Json
#>
[CmdletBinding()]
param(
    [string]$RepoPath = 'C:\CCSystem\ec_accurev_git',
    [int]$Days = 7,
    [string]$Author = '',
    [switch]$IncludeMerges,
    [switch]$IncludeSubmodules
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Protect-Regex {
    <#
        Escape only what actually matters to git's POSIX extended regex.
        [regex]::Escape() is wrong here: it escapes spaces as '\ ', which
        git does not accept, so "IS10 Oren Goldstein" silently matched nothing.
    #>
    param([string]$Value)
    return ($Value -replace '([.\[\]()*+?^$\\|{}])', '\$1')
}

function Get-AuthorPattern {
    param([string]$Repo)

    if ($Author) { return $Author }

    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($key in @('user.email', 'user.name')) {
        $value = & git -C $Repo config $key 2>$null
        if ($LASTEXITCODE -eq 0 -and $value) { $parts.Add((Protect-Regex $value.Trim())) }
    }
    # The local account name catches the short-form committer identity
    # (ogoldste) that does not appear in user.email verbatim.
    if ($env:USERNAME) { $parts.Add((Protect-Regex $env:USERNAME)) }

    if ($parts.Count -eq 0) {
        throw 'Could not determine a git author. Pass -Author explicitly.'
    }
    return ($parts | Select-Object -Unique) -join '|'
}

function Get-ModuleName {
    <#
        Map a changed file path to the work area a human would name in a
        status mail. Ordered most-specific first.
    #>
    param([string]$Path)

    $p = $Path -replace '\\', '/'
    $rules = @(
        @{ Pattern = '^(EC|BMC|TPM)/Modules/([^/]+)';        Format = '{1}/{2}' },
        @{ Pattern = '^(EC|BMC|TPM)/SWQA/([^/]+)';           Format = '{1} SWQA/{2}' },
        @{ Pattern = '^(EC|BMC|TPM)/Patterns/([^/]+)';       Format = '{1} Patterns/{2}' },
        @{ Pattern = '^SharedModules/([^/]+)';               Format = 'SharedModules/{1}' },
        @{ Pattern = '^ValidationCommon/([^/]+)';            Format = 'ValidationCommon/{1}' },
        @{ Pattern = '^Objects/([^/]+)/([^/]+)';             Format = 'Objects/{1}/{2}' },
        @{ Pattern = '^(EC|BMC|TPM)/Common/([^/]+)';         Format = '{1} Common/{2}' },
        @{ Pattern = '^(EC|BMC|TPM)/([^/]+)';                Format = '{1}/{2}' }
    )

    foreach ($rule in $rules) {
        $m = [regex]::Match($p, $rule.Pattern)
        if ($m.Success) {
            $out = $rule.Format
            for ($i = 1; $i -lt $m.Groups.Count; $i++) {
                $out = $out.Replace("{$i}", $m.Groups[$i].Value)
            }
            return $out
        }
    }

    $segments = $p.Split('/')
    if ($segments.Count -gt 1) { return $segments[0] }
    return '(root)'
}

function Get-RepoActivity {
    param([string]$Repo, [string]$Label, [string]$Pattern)

    if (-not (Test-Path $Repo)) { return @() }

    $args = @(
        '-C', $Repo, '--no-pager', 'log',
        # Alternation in the author pattern needs extended regex; without -E
        # git treats '|' literally and matches nothing.
        '-E',
        "--author=$Pattern",
        "--since=$Days days ago",
        '--date=iso-strict',
        # Trailing %x02 after the body matters: --name-only appends the file
        # list straight after %b, so without a closing delimiter a multi-line
        # commit message is parsed as if each of its lines were a file path.
        '--format=%x01%H%x02%h%x02%an%x02%ae%x02%ad%x02%s%x02%b%x02',
        '--name-only'
    )
    if (-not $IncludeMerges) { $args += '--no-merges' }

    $raw = & git @args 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $raw) { return @() }

    $text = ($raw -join "`n")
    $commits = New-Object System.Collections.Generic.List[object]

    # \x01 starts a record, \x02 separates the header fields; everything after
    # the last separator is the file list. Using control characters rather than
    # a printable delimiter keeps commit subjects containing '|' from splitting
    # the record.
    foreach ($chunk in $text.Split([char]1)) {
        if (-not $chunk.Trim()) { continue }
        $fields = $chunk.Split([char]2)
        if ($fields.Count -lt 6) { continue }

        $files = @()
        if ($fields.Count -ge 8) {
            $files = @($fields[7].Split("`n") |
                ForEach-Object { $_.Trim() } |
                Where-Object { $_ -and $_ -notmatch '^\s*$' })
        }

        $modules = @($files | ForEach-Object { Get-ModuleName $_ } | Select-Object -Unique)

        $commits.Add([pscustomobject]@{
            repo          = $Label
            sha           = $fields[1]
            author        = $fields[2]
            email         = $fields[3]
            date          = $fields[4]
            subject       = $fields[5].Trim()
            files_changed = $files.Count
            files         = @($files | Select-Object -First 20)
            modules       = $modules
        })
    }
    return $commits.ToArray()
}

$pattern = Get-AuthorPattern -Repo $RepoPath
$all = New-Object System.Collections.Generic.List[object]

foreach ($c in Get-RepoActivity -Repo $RepoPath -Label (Split-Path $RepoPath -Leaf) -Pattern $pattern) {
    $all.Add($c)
}

if ($IncludeSubmodules) {
    $subs = & git -C $RepoPath config --file .gitmodules --get-regexp path 2>$null
    if ($LASTEXITCODE -eq 0 -and $subs) {
        foreach ($line in $subs) {
            $rel = ($line -split '\s+', 2)[1]
            if (-not $rel) { continue }
            $full = Join-Path $RepoPath $rel
            foreach ($c in Get-RepoActivity -Repo $full -Label $rel -Pattern $pattern) {
                $all.Add($c)
            }
        }
    }
}

$commits = $all.ToArray()

# Group by work area so the mail can be written per topic rather than as a
# flat list of shas nobody will read.
$byModule = @{}
foreach ($c in $commits) {
    $mods = @($c.modules)
    if ($mods.Count -eq 0) { $mods = @('(no files)') }
    foreach ($m in $mods) {
        if (-not $byModule.ContainsKey($m)) {
            $byModule[$m] = New-Object System.Collections.Generic.List[object]
        }
        $byModule[$m].Add(@{ sha = $c.sha; subject = $c.subject; date = $c.date })
    }
}

$modulesOut = $byModule.GetEnumerator() |
    Sort-Object { $_.Value.Count } -Descending |
    ForEach-Object {
        [pscustomobject]@{
            module       = $_.Key
            commit_count = $_.Value.Count
            commits      = $_.Value.ToArray()
        }
    }

[pscustomobject]@{
    generated_at   = (Get-Date).ToString('o')
    repo           = $RepoPath
    days           = $Days
    author_pattern = $pattern
    commit_count   = $commits.Count
    modules        = @($modulesOut)
    commits        = $commits
} | ConvertTo-Json -Depth 6
