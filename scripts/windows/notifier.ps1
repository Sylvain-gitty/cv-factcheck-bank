<#
Job engine desktop notifier. Shows a Windows notification when a pipeline run has
recorded a digest, and when the engine cannot be reached. Nothing leaves this machine:
it only talks to the local factbank-api on 127.0.0.1:8000.

    powershell -File scripts\windows\notifier.ps1            # loop (what the logon task runs)
    powershell -File scripts\windows\notifier.ps1 -Once      # check once, then exit
    powershell -File scripts\windows\notifier.ps1 -Test      # show a test notification

Clicking a notification opens http://localhost:8000/ (the digest page).
Started at sign-in by the scheduled task from install-notifier.ps1.
#>
param(
    [switch]$Once,
    [switch]$Test,
    [int]$IntervalSeconds = 120,
    [int]$UnreachableAfter = 3,          # consecutive failed checks before warning (~6 min)
    [string]$ApiBase = "http://127.0.0.1:8000",
    [string]$PageUrl = "http://localhost:8000/"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
# The AppUserModelID of Windows PowerShell: lets an unpackaged script show toasts.
$AppId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'

[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]

function Get-Token {
    $line = Get-Content (Join-Path $Root ".env") | Where-Object { $_ -match '^API_TOKEN=' } | Select-Object -First 1
    if (-not $line) { throw "API_TOKEN not found in $Root\.env" }
    return $line.Substring("API_TOKEN=".Length).Trim()
}

function Esc([string]$s) { return [System.Security.SecurityElement]::Escape($s) }

function Show-Toast([string]$Title, [string[]]$Lines, [string]$Tag) {
    $body = ($Lines | Where-Object { $_ } | Select-Object -First 3 | ForEach-Object { "<text>$(Esc $_)</text>" }) -join ""
    $xml = @"
<toast activationType="protocol" launch="$(Esc $PageUrl)">
  <visual><binding template="ToastGeneric"><text>$(Esc $Title)</text>$body</binding></visual>
  <actions><action content="Open digest" activationType="protocol" arguments="$(Esc $PageUrl)"/></actions>
</toast>
"@
    $doc = New-Object Windows.Data.Xml.Dom.XmlDocument
    $doc.LoadXml($xml)
    $toast = New-Object Windows.UI.Notifications.ToastNotification $doc
    $toast.Tag = $Tag
    $toast.Group = "job-engine"
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($AppId).Show($toast)
}

function Invoke-Api([string]$Method, [string]$Path, $Body = $null) {
    $h = @{ Authorization = "Bearer $script:Token" }
    if ($Body) {
        return Invoke-RestMethod -Method $Method -Uri "$ApiBase$Path" -Headers $h -TimeoutSec 15 `
            -ContentType "application/json" -Body ($Body | ConvertTo-Json -Compress)
    }
    return Invoke-RestMethod -Method $Method -Uri "$ApiBase$Path" -Headers $h -TimeoutSec 15
}

function Check {
    $pending = @((Invoke-Api GET "/digests/pending").digests)
    if ($pending.Count -eq 0) { return }
    $failed = @($pending | Where-Object { $_.status -eq "failed" })
    $ok = @($pending | Where-Object { $_.status -eq "ok" })

    if ($failed.Count -gt 0) {
        $f = $failed[-1]
        Show-Toast "Job engine run FAILED" @(
            "$($f.workflow) - node: $($f.failed_node)",
            ([string]$f.error).Substring(0, [Math]::Min(180, ([string]$f.error).Length))
        ) "failed"
    }
    # Several runs since the last check (e.g. a restart loop): one notification, summed.
    $new = ($ok | Measure-Object -Property new_count -Sum).Sum
    if ($new -gt 0) {
        $last = $ok[-1]
        $top = @($last.top | Select-Object -First 2 | ForEach-Object { "$($_.company): $($_.title)" })
        Show-Toast "$new new job(s), $($last.inbox_size) waiting" $top "digest"
    }
    $maxId = ($pending | Measure-Object -Property id -Maximum).Maximum
    [void](Invoke-Api POST "/digests/notified" @{ up_to_id = [int64]$maxId })
}

if ($Test) {
    Show-Toast "Job engine notifier works" @("Click to open the digest page.") "test"
    exit 0
}

$script:Token = Get-Token
$misses = 0
$warned = $false
while ($true) {
    try {
        Check
        if ($warned) { Show-Toast "Job engine reachable again" @("The stack is back up.") "reach" }
        $misses = 0; $warned = $false
    } catch {
        $misses++
        if ($misses -ge $UnreachableAfter -and -not $warned) {
            Show-Toast "Job engine not reachable" @(
                "Is Docker Desktop running? Try: docker compose up -d",
                "$($_.Exception.Message)"
            ) "reach"
            $warned = $true
        }
    }
    if ($Once) { break }
    Start-Sleep -Seconds $IntervalSeconds
}
