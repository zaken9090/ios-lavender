# CPU per frame of backboardd while Settings scrolls (needs boot-args sweetsample=zz sweetsample_s=6 sweetfps=1).
# Opens Settings, scrolls down/up 12 times (~36 s) while logging, then prints backboardd CPU ms per
# presented frame from the SMC and SWEET FPS lines of that window.
# usage: .\tools\cpuframe.ps1 -Tag T
param([Parameter(Mandatory)][string]$Tag)
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$log = "..\dump\cpuframe-$Tag.txt"
$steps = "tap 164 565; wait 3" + ("; swipe 540 1900 540 600 500; wait 1.5; swipe 540 600 540 1900 500; wait 1.5" * 12) + "; swipe 540 2330 540 1500 200; wait 2"
python tools\uishot.py "cf$Tag" --log $log --steps $steps | Out-Null
python tools\cpuframe.py $log
