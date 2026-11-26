# One telephony test boot: the modem without Wi-Fi, CommCenter's own log lines in the USB log.
# usage: .\cc-run.ps1 -Kernel ..\..\ci\run-N -Tag e60 [-Adt shim\out\lavender-bb.adt] [-Extra "x=1"] [-Seconds 60]
# Prints the lines of the baseband services (LV BB / LV PDP / LV ABP), CommCenter's stderr
# (|CommCenter| ..., needs OS_ACTIVITY_DT_MODE=YES in its launchd job) and crashes.
param(
    [Parameter(Mandatory)][string]$Kernel,
    [Parameter(Mandatory)][string]$Tag,
    [string]$Adt = "shim\out\lavender.adt",
    [string]$Extra = "",
    [int]$Seconds = 60,
    [int]$First = 160,
    [string]$Pattern = "LV ABP|LV BB:|LV PDP:|\|CommCenter\||CRASH CommCenter|CRASH abm|exec CommCenter$"
)
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$p = Start-Process powershell -ArgumentList "-NoProfile -File tools\quick.ps1 -Tag $Tag -Kernel `"$Kernel`" -Adt $Adt -Extra `"modem=1 lv_serror=1 modem_wlfw=0 abp=1 sweetstderr=CommCenter $Extra`" -NoBench" -PassThru -WindowStyle Hidden -RedirectStandardOutput "..\dump\quick-$Tag.txt"
$null = $p.WaitForExit(240000)
if (-not $p.HasExited) { $p.Kill() }
Start-Sleep $Seconds
Select-String -Path "..\dump\usblog-$Tag.txt" -Pattern $Pattern | ForEach-Object { $_.Line.Substring(0, [Math]::Min(300, $_.Line.Length)) } | Select-Object -First $First
