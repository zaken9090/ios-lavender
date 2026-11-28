# Waits in fastboot while the phone charges: until the battery reads -Until mV or -MaxMin minutes have passed.
# usage: .\charge.ps1 [-Until 3950] [-MaxMin 9]      (the phone must be in fastboot; it drains under iOS)
param([int]$Until = 3950, [int]$MaxMin = 9)
$fb = Join-Path $PSScriptRoot "..\..\platform-tools\fastboot.exe"
$end = (Get-Date).AddMinutes($MaxMin)
do {
    $line = (& $fb getvar battery-voltage 2>&1 | Select-String "battery-voltage: (\d+)")
    $mv = if ($line) { [int]$line.Matches[0].Groups[1].Value } else { 0 }
    if ($mv -ge $Until -or (Get-Date) -ge $end) { break }
    Start-Sleep 30
} while ($true)
"battery $mv mV"
