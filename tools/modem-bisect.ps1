# Boots the phone once per boot-arg set and reports whether the modem stayed up.
# usage: .\modem-bisect.ps1 -Kernel ..\..\ci\run-N -Tag e53 -Sets "modem_wlfw=1","modem_wlfw=2"
# Each run: quick.ps1 -NoBench with "modem=1 lv_serror=1 <set>", then the log is read until it is
# $Seconds old; the result line names the last WLFW step and the modem's crash reason, if any.
param(
    [Parameter(Mandatory)][string]$Kernel,
    [Parameter(Mandatory)][string]$Tag,
    [Parameter(Mandatory)][string[]]$Sets,
    [int]$Seconds = 45
)
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$i = 0
foreach ($set in $Sets) {
    $i++
    $t = "$Tag-$i"
    $p = Start-Process powershell -ArgumentList "-NoProfile -File tools\quick.ps1 -Tag $t -Kernel `"$Kernel`" -Extra `"modem=1 lv_serror=1 $set`" -NoBench" -PassThru -WindowStyle Hidden -RedirectStandardOutput "..\dump\quick-$t.txt"
    $null = $p.WaitForExit(240000)
    if (-not $p.HasExited) { $p.Kill() }
    $log = "..\dump\usblog-$t.txt"
    # wait until the modem has run for $Seconds (its own clock in the log) or the log stops growing
    foreach ($n in 1..10) {
        Start-Sleep 5
        $last = Select-String -Path $log -Pattern "TopazModem: t=(\d+) ms" | Select-Object -Last 1
        if ($last -and [int]$last.Matches[0].Groups[1].Value -ge $Seconds * 1000) { break }
        if (Select-String -Path $log -Pattern "modem crash reason" -Quiet) { break }
    }
    $step = (Select-String -Path $log -Pattern "wlfw: stopped after|WLFW left alone|WLAN FIRMWARE READY|MSA_READY indication" | Select-Object -Last 1).Line
    $crash = (Select-String -Path $log -Pattern "modem crash reason" | Select-Object -First 1).Line
    $at = (Select-String -Path $log -Pattern "TopazModem: t=(\d+) ms.*FATAL" | Select-Object -First 1).Line
    $seen = (Select-String -Path $log -Pattern "TopazModem: t=(\d+) ms" | Select-Object -Last 1).Line
    "RESULT [$set] step: $step | crash: $crash | fatal: $at | last: $seen"
}
