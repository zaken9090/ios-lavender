# One GPU test run without idle waits: build the image, boot, bench as soon as the lock screen is drawn.
# usage: .\quick.ps1 -Tag e30 [-Kernel ..\..\ci\run-N] [-Userland ..\..\ci\userland-N\topaz-userland] [-Extra "x=1"] [-Install] [-NoBench]
#   -Kernel / -Userland default to the newest in ..\..\ci.  -Install: the userland changed - boot once until the
#   kernel has written it (LVINSTALL done), back to fastboot, boot again (it takes effect from the next boot).
# Readiness is a log line (backboardd's 40th GL frame), not a fixed sleep.
param(
    [Parameter(Mandatory)][string]$Tag,
    [string]$Kernel, [string]$Userland, [string]$Extra = "",
    [switch]$Install, [switch]$NoBench,
    [string]$Ready = "redwood-gl: frame 40:"
)
$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$ci = Join-Path $root "..\ci"
if (-not $Kernel) { $Kernel = (Get-ChildItem $ci -Directory -Filter "run-*" | Where-Object { Test-Path (Join-Path $_.FullName "kernel.development.sweet") } | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName }
if (-not $Userland) { $Userland = (Get-ChildItem $ci -Directory -Filter "userland-*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName + "\topaz-userland" }
$k = Join-Path $Kernel "kernel.development.sweet"

function Stop-Loggers { Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "usblog|bench" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force } }
function To-Fastboot {
    Stop-Loggers
    if (& ..\platform-tools\fastboot.exe devices) { return }
    python tools\usblog.py --cmd "lv:fastboot" --wait 10 --idle 3 --out "..\dump\usblog-$Tag-fb.txt" 2>&1 | Out-Null
    foreach ($i in 1..30) { Start-Sleep 1; if (& ..\platform-tools\fastboot.exe devices) { return } }
}

# files for the iOS root (kept out of the repo): written by the kernel when present (patch 1035)
$rootArgs = @(); if (Test-Path ..\downloads\root-files) { $rootArgs = @("--rootfiles", (Resolve-Path ..\downloads\root-files).Path) }
$cmdline = ((Get-Content shim\out\e7-bootargs.txt) + " gpu=1 glfetch=0 lv_sleep=1 " + $Extra).Trim()
python tools\mkpayload.py "shim\out\payload-$Tag.bin" --kernel $k --adt shim\out\lavender.adt --cmdline $cmdline --fw (Resolve-Path ..\downloads\gpu-fw).Path --userland (Resolve-Path $Userland).Path @rootArgs | Out-Null
powershell -ExecutionPolicy Bypass -File shim\build.ps1 -Dtb ..\dump\miui-boot\split\dtb5.dtb -Payload "shim\out\payload-$Tag.bin" -Out "shim\out\$Tag.img" | Out-Null
To-Fastboot
if ($Install) {
    powershell -ExecutionPolicy Bypass -File tools\boot.ps1 -Image "shim\out\$Tag.img" -Log "..\dump\usblog-$Tag-a.txt" -Until "LVINSTALL done" -Idle 240 | Out-Null
    Start-Sleep 3
    To-Fastboot
}
powershell -ExecutionPolicy Bypass -File tools\boot.ps1 -Image "shim\out\$Tag.img" -Log "..\dump\usblog-$Tag.txt" -Until $Ready -Idle 240 | Out-Null
if (-not $NoBench) {
    $b = python tools\bench.py $Tag --log "..\dump\bench-$Tag.txt" --settle 2 2>&1 | Select-String "^BENCH" | Select-Object -Last 1
    "$Extra -> $b"
}
