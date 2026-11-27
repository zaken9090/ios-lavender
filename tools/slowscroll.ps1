# Slow Settings scroll (2 s swipes) and the frame pacing during it, from the SWEET FPS lines:
# frames a second, "late" (gap > 20 ms) share, and the gap classes (1 / 2 / 3 / more panel periods).
# usage: .\tools\slowscroll.ps1 -Tag T
param([Parameter(Mandatory)][string]$Tag)
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$log = "..\dump\slow-$Tag.txt"
$steps = "tap 164 565; wait 3" + ("; swipe 540 1900 540 1100 2000; wait 2.5; swipe 540 1100 540 1900 2000; wait 2.5" * 5) + "; swipe 540 2330 540 1500 200; wait 2"
python tools\uishot.py "sl$Tag" --log $log --steps $steps | Out-Null
python tools\slowscroll.py $log
