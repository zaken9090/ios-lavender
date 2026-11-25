# Boot one kernel with several boot-arg sets and run tools\bench.py on each, no user needed.
# usage: .\benchset.ps1 -Kernel ..\..\ci\run-X -Prefix e23 -Sets "lv_gpu=0;lv_gpu=10"  (";" separates sets: powershell -File passes one string) [-Fw ..\..\downloads\gpu-fw]
# Results: dump\bench-results.txt (one BENCH line per set, tag = Prefix + index).
param(
    [Parameter(Mandatory)][string]$Kernel,
    [Parameter(Mandatory)][string]$Prefix,
    [Parameter(Mandatory)][string]$Sets,
    [string]$Fw,
    [string]$Userland,          # with -Fw: the userland CI's files for the kernel to install (patch 1015)
    [int]$Settle = 30
)
$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$k = (Get-ChildItem $Kernel -Recurse -Filter "kernel.*" | Select-Object -First 1).FullName
$fwArgs = @(); if ($Fw) { $fwArgs = @("--fw", (Resolve-Path $Fw).Path) }; if ($Fw -and $Userland) { $fwArgs += @("--userland", (Resolve-Path $Userland).Path) }
$i = 0
foreach ($set in ($Sets -split ";")) {
    $tag = "$Prefix-$i"; $i++
    $cmdline = ((Get-Content shim\out\e7-bootargs.txt) + " " + $set).Trim()
    python tools\mkpayload.py "shim\out\payload-$tag.bin" --kernel $k --adt shim\out\lavender.adt --cmdline $cmdline @fwArgs | Out-Null
    powershell -ExecutionPolicy Bypass -File shim\build.ps1 -Dtb ..\dump\miui-boot\split\dtb5.dtb -Payload "shim\out\payload-$tag.bin" -Out "shim\out\$tag.img" | Out-Null
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "usblog|bench" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    powershell -ExecutionPolicy Bypass -File tools\boot.ps1 -Image "shim\out\$tag.img" -Log "..\dump\usblog-$tag.txt" -Until "SWEET FPS" -Idle 240 | Out-Null
    $r = python tools\bench.py "$tag" --log "..\dump\bench-$tag.txt" --settle $Settle 2>&1 | Select-String "^BENCH" | Select-Object -Last 1
    "$set -> $r"
}
