<#
Job engine desktop helper. Runs on the Windows host and does three things:
  1. shows a Windows notification when a pipeline run has recorded a digest (or failed),
     and when the engine cannot be reached;
  2. announces follow-ups that are due (day 7 / day 14 after you sent an application)
     and the weekly report;
  3. prints queued application PDFs with Edge, exactly as V1 did. The API container has
     no browser and none of the CV's fonts, so the PDF you send is made here.
Nothing leaves this machine: it only talks to the local factbank-api on 127.0.0.1:8000.

    powershell -File scripts\windows\notifier.ps1            # loop (what the logon task runs)
    powershell -File scripts\windows\notifier.ps1 -Once      # check once, then exit
    powershell -File scripts\windows\notifier.ps1 -Test      # show a test notification

Clicking a notification opens http://localhost:8000/ (the digest page).
Started at sign-in by the scheduled task from install-notifier.ps1.
#>
param(
    [switch]$Once,
    [switch]$Test,
    [int]$IntervalSeconds = 30,
    [int]$UnreachableAfter = 12,         # consecutive failed checks before warning (~6 min)
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

function Show-Toast([string]$Title, [string[]]$Lines, [string]$Tag, [string]$Url = $PageUrl, [string]$Button = "Open") {
    $body = ($Lines | Where-Object { $_ } | Select-Object -First 3 | ForEach-Object { "<text>$(Esc $_)</text>" }) -join ""
    $xml = @"
<toast activationType="protocol" launch="$(Esc $Url)">
  <visual><binding template="ToastGeneric"><text>$(Esc $Title)</text>$body</binding></visual>
  <actions><action content="$(Esc $Button)" activationType="protocol" arguments="$(Esc $Url)"/></actions>
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
        Show-Toast "$new new job(s), $($last.inbox_size) waiting" $top "digest" $PageUrl "Open inbox"
    }
    $maxId = ($pending | Measure-Object -Property id -Maximum).Maximum
    [void](Invoke-Api POST "/digests/notified" @{ up_to_id = [int64]$maxId })
}

# ------------------------------------------------------------------ PDFs (printed here)

$Browser = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
$OutDir = [System.IO.Path]::GetFullPath((Join-Path $Root "out")) + "\"

function Resolve-Inside([string]$rel, [string]$ext) {
    # Paths come from the API; accept only files inside <repo>\out\ with the expected extension.
    $full = [System.IO.Path]::GetFullPath((Join-Path $Root ($rel -replace '/', '\')))
    if (-not $full.StartsWith($OutDir, [StringComparison]::OrdinalIgnoreCase)) { throw "path outside out\: $rel" }
    if ([System.IO.Path]::GetExtension($full) -ne $ext) { throw "unexpected file type: $rel" }
    return $full
}

function Print-Pdfs {
    $jobs = @((Invoke-Api GET "/pdf/pending").jobs)
    foreach ($j in $jobs) {
        $ok = $false; $err = $null
        try {
            if (-not $Browser) { throw "no Edge or Chrome found on this PC" }
            $html = Resolve-Inside $j.html_path ".html"
            $pdf = Resolve-Inside $j.pdf_path ".pdf"
            if (-not (Test-Path $html)) { throw "missing $($j.html_path)" }
            $before = if (Test-Path $pdf) { (Get-Item $pdf).LastWriteTimeUtc } else { [DateTime]::MinValue }
            # Own profile dir, so a running Edge window does not swallow the headless call.
            $profileDir = Join-Path $env:TEMP "job-engine-pdf-profile"
            $uri = ([System.Uri]$html).AbsoluteUri
            $p = Start-Process -FilePath $Browser -PassThru -WindowStyle Hidden -ArgumentList @(
                "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run",
                "--user-data-dir=`"$profileDir`"", "--print-to-pdf=`"$pdf`"", "`"$uri`"")
            # Headless Chrome/Edge can return before the file is flushed: poll for it (V1 lesson).
            for ($i = 0; $i -lt 60; $i++) {
                if ((Test-Path $pdf) -and (Get-Item $pdf).Length -gt 0 -and (Get-Item $pdf).LastWriteTimeUtc -gt $before) { $ok = $true; break }
                Start-Sleep -Milliseconds 500
            }
            if (-not $ok) { throw "the browser produced no PDF within 30 s" }
        } catch { $err = $_.Exception.Message }
        [void](Invoke-Api POST "/pdf/$($j.id)/done" @{ ok = $ok; error = $err })
        if (-not $ok) {
            Show-Toast "PDF could not be printed" @($j.pdf_path, $err) "pdf" "http://localhost:8000/applications" "Open applications"
        }
    }
}

# ------------------------------------------------------------------ follow-ups

function Announce-FollowUps {
    $due = @((Invoke-Api GET "/reminders/due").reminders)
    if ($due.Count -eq 0) { return }
    if ($due.Count -eq 1) {
        $r = $due[0]
        Show-Toast "Follow up: $($r.company)" @("$($r.title)", "Sent $($r.sent_date), $($r.kind) reminder. No reply yet? A short, polite nudge.") "followup" "http://localhost:8000/applications" "Open applications"
    } else {
        $names = @($due | Select-Object -First 3 | ForEach-Object { "$($_.company): $($_.title)" })
        Show-Toast "$($due.Count) follow-ups due" $names "followup" "http://localhost:8000/applications" "Open applications"
    }
    [void](Invoke-Api POST "/reminders/shown" @{ ids = @($due | ForEach-Object { [int64]$_.id }) })
}

# ------------------------------------------------------------------ weekly report

function Announce-Report {
    $r = @((Invoke-Api GET "/report/pending").reports)
    if ($r.Count -eq 0) { return }
    Show-Toast "Weekly report: $($r[0].headline)" @($r[0].detail) "report" "http://localhost:8000/report" "Open report"
    [void](Invoke-Api POST "/report/notified" @{ ids = @($r | ForEach-Object { [int64]$_.id }) })
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
        Print-Pdfs
        Announce-FollowUps
        Announce-Report
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
