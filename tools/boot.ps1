# One test cycle without touching the phone:
#   get it into fastboot from whatever it runs (our kernel: lv:fastboot over USB; Android: adb),
#   `fastboot boot` the image, save the kernel log from USB, optionally return to fastboot.
# usage: .\boot.ps1 -Image ..\shim\out\x.img [-Log ..\..\dump\x.txt] [-Idle 30] [-Until "text"] [-Back]
param(
    [Parameter(Mandatory)][string]$Image,
    [string]$Log,
    [int]$Idle = 30,            # stop reading after this many seconds without new log
    [string]$Until,             # ... or as soon as this text appears
    [switch]$Back,              # send lv:fastboot when done
    [string]$PlatformTools
)
$ErrorActionPreference = "Stop"
if (-not $PlatformTools) { $PlatformTools = Join-Path $PSScriptRoot "..\..\platform-tools" }
$adb = Join-Path $PlatformTools "adb.exe"
$fastboot = Join-Path $PlatformTools "fastboot.exe"
$usblog = Join-Path $PSScriptRoot "usblog.py"

function Test-Fastboot { [bool]((& $fastboot devices) -join '') }
function Test-Adb { ((& $adb devices) -join "`n") -match "`tdevice" }
function Wait-Until([scriptblock]$test, [int]$seconds) {
    foreach ($i in 1..$seconds) { if (& $test) { return $true }; Start-Sleep 1 }
    return $false
}

if (-not (Test-Fastboot)) {
    if (Test-Adb) {
        & $adb reboot bootloader
    } else {
        python $usblog --wait 3 --idle 0 --cmd lv:fastboot 2>$null | Out-Null
        if ($LASTEXITCODE -eq 2) { throw "phone not found: not in fastboot, no adb, no USB log device" }
    }
    if (-not (Wait-Until { Test-Fastboot } 60)) { throw "the phone did not reach fastboot" }
}
cmd /c "`"$fastboot`" boot `"$Image`" 2>&1" | Select-Object -Last 1 | Write-Host
$logArgs = @($usblog, "--wait", "40", "--idle", "$Idle")
if ($Log) { Remove-Item $Log -ErrorAction SilentlyContinue; $logArgs += @("--out", $Log) }
if ($Until) { $logArgs += @("--until", $Until) }
$ErrorActionPreference = "Continue"     # usblog reports on stderr
python @logArgs 2>$null
if ($Back) {
    python $usblog --wait 3 --idle 0 --cmd lv:fastboot 2>$null | Out-Null
    if (Wait-Until { Test-Fastboot } 30) { Write-Host "`nback in fastboot" } else { Write-Host "`nNOT back in fastboot" }
}
