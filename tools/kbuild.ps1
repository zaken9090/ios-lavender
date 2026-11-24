# Builds the kernel on GitHub Actions and downloads it.
# The pushed HEAD is built on both runner types at once (Apple silicon is faster but often queued,
# Intel starts at once); the first run to succeed wins and the other is cancelled.
# usage: .\kbuild.ps1 [-OutRoot ..\..\ci] [-Runners macos-15,macos-15-intel]
# Prints the folder holding kernel.development.sweet as the last line.
param(
    [string]$OutRoot,
    [string[]]$Runners = @("macos-15", "macos-15-intel"),
    [string]$Repo = "zaken9090/ios-lavender",
    [int]$TimeoutMin = 60
)
$ErrorActionPreference = "Stop"
if (-not $OutRoot) { $OutRoot = Join-Path $PSScriptRoot "..\..\ci" }
$head = (git -C $PSScriptRoot rev-parse HEAD).Trim()
if ((git -C $PSScriptRoot rev-parse "origin/main").Trim() -ne $head) { throw "push main first" }

function Get-Runs { gh run list -R $Repo -w xnu.yml -L 10 --json databaseId,headSha,status,conclusion,createdAt | ConvertFrom-Json }

$before = @(Get-Runs | ForEach-Object databaseId)
foreach ($r in $Runners) { gh workflow run xnu.yml -R $Repo -f "runner=$r" | Out-Null }
$mine = @()
foreach ($i in 1..20) {
    Start-Sleep 3
    $mine = @(Get-Runs | Where-Object { $_.headSha -eq $head -and $before -notcontains $_.databaseId })
    if ($mine.Count -ge $Runners.Count) { break }
}
if (-not $mine) { throw "dispatched runs not found" }
$ids = $mine | ForEach-Object databaseId
Write-Host "runs: $($ids -join ', ')"

$deadline = (Get-Date).AddMinutes($TimeoutMin)
$winner = $null
while (-not $winner -and (Get-Date) -lt $deadline) {
    Start-Sleep 20
    $state = Get-Runs | Where-Object { $ids -contains $_.databaseId }
    $winner = $state | Where-Object { $_.conclusion -eq "success" } | Select-Object -First 1
    if (-not ($state | Where-Object { $_.status -ne "completed" }) -and -not $winner) {
        foreach ($s in $state) { gh run view $s.databaseId -R $Repo --log-failed | Select-String "error:" | Select-Object -First 15 | ForEach-Object { Write-Host $_.Line } }
        throw "every run failed"
    }
}
if (-not $winner) { throw "no result after $TimeoutMin min" }
foreach ($id in $ids) { if ($id -ne $winner.databaseId) { gh run cancel $id -R $Repo 2>$null | Out-Null } }
$dir = Join-Path $OutRoot "run-$($winner.databaseId)"
New-Item -ItemType Directory -Force $dir | Out-Null
gh run download $winner.databaseId -R $Repo -n xnu-kernel -D $dir
(Resolve-Path $dir).Path
