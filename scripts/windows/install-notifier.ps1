<#
Register (or remove) the scheduled task that starts the job-engine notifier at sign-in.

    powershell -ExecutionPolicy Bypass -File scripts\windows\install-notifier.ps1
    powershell -ExecutionPolicy Bypass -File scripts\windows\install-notifier.ps1 -Uninstall

What it creates: one task, "JobEngineNotifier", for your user only, with normal (not
admin) rights. Trigger: when you sign in. Action: run notifier.ps1 hidden, which then
checks the local API every 2 minutes. If it crashes, it restarts up to 3 times.
#>
param([switch]$Uninstall)

$ErrorActionPreference = "Stop"
$TaskName = "JobEngineNotifier"
$Script = Join-Path $PSScriptRoot "notifier.ps1"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed task $TaskName."
    exit 0
}

$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "Job engine: desktop notifications from the local digest" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Output "Registered and started task $TaskName (runs at sign-in, user $user)."
