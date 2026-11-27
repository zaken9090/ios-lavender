# Settings: short slow drags with a screenshot right after each (doubled rows / ghost trails show there).
# usage: .\tools\ghost.ps1 -Tag T
param([Parameter(Mandatory)][string]$Tag)
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$steps = "swipe 540 2330 540 1500 200; wait 2; tap 164 565; wait 3"
foreach ($i in 1..4) { $steps += "; swipe 540 1500 540 1350 400; shot; swipe 540 1350 540 1500 400; shot" }
$steps += "; swipe 540 2330 540 1500 200; wait 1"
python tools\uishot.py "gh$Tag" --steps $steps 2>&1 | Select-Object -Last 1
