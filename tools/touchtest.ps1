# Boot a kernel with extra boot-args, then beep and count the user's real touches.
# Real touches are fingers 0-8 in "SWEET HID: touch N"; finger 9 is injected over USB (lv:tap/lv:swipe)
# and goes around the touch controller, so bench.py cannot see a dead controller.
# usage: .\touchtest.ps1 -Kernel ..\..\ci\run-X -Tag e10g3 -Extra "lv_gpu=3" [-Seconds 40]
param(
    [Parameter(Mandatory)][string]$Kernel,
    [Parameter(Mandatory)][string]$Tag,
    [string]$Extra = "",
    [int]$Seconds = 40
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$k = (Get-ChildItem $Kernel -Recurse -Filter "kernel.*" | Select-Object -First 1).FullName
$cmdline = ((Get-Content shim\out\e7-bootargs.txt) + " " + $Extra).Trim()
python tools\mkpayload.py "shim\out\payload-$Tag.bin" --kernel $k --adt shim\out\lavender.adt --cmdline $cmdline | Out-Null
powershell -ExecutionPolicy Bypass -File shim\build.ps1 -Dtb ..\dump\miui-boot\split\dtb5.dtb -Payload "shim\out\payload-$Tag.bin" -Out "shim\out\$Tag.img" | Out-Null
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "usblog" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
powershell -ExecutionPolicy Bypass -File tools\boot.ps1 -Image "shim\out\$Tag.img" -Log "..\dump\usblog-$Tag.txt" -Until "SWEET FPS" -Idle 240 | Out-Null
$f = "..\dump\usblog-$Tag-touch.txt"
$p = Start-Process python -ArgumentList "tools\usblog.py", "--wait", "3", "--out", $f -PassThru -WindowStyle Hidden
[console]::beep(1000, 300); [console]::beep(1300, 300)
Start-Sleep $Seconds
Stop-Process -Id $p.Id -Force
$real = (Select-String -Path $f -Pattern "HID: touch [0-8] ").Count
Select-String -Path "..\dump\usblog-$Tag.txt", $f -Pattern "LVGPU" | ForEach-Object { $_.Line }
"TOUCHTEST $Tag ($Extra): real touches $real"
