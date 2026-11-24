# Builds the shim and packs it as a boot image for `fastboot boot`.
# usage: .\build.ps1 -Dtb <lavender dtb> [-Out out\shim.img]
# Needs LLVM for Windows (clang, ld.lld, llvm-objcopy) and Python 3.
param(
    [Parameter(Mandatory)][string]$Dtb,
    [string]$Out,
    [string]$Llvm = "C:\Program Files\LLVM\bin"
)
$ErrorActionPreference = "Stop"
$o = "$PSScriptRoot\out"
if (-not $Out) { $Out = "$o\shim.img" }   # $PSScriptRoot is empty inside param() on PowerShell 5.1
New-Item -ItemType Directory -Force $o | Out-Null
$cflags = "--target=aarch64-none-elf", "-mcpu=cortex-a53", "-ffreestanding", "-fno-builtin", "-fno-pic",
          "-fno-stack-protector", "-mgeneral-regs-only", "-mstrict-align", "-O2", "-Wall", "-Wextra"
function Invoke-Tool($exe, $toolArgs) {
    & "$Llvm\$exe" @toolArgs
    if ($LASTEXITCODE) { throw "$exe failed" }
}
Invoke-Tool clang.exe ($cflags + "-c", "$PSScriptRoot\start.S", "-o", "$o\start.o")
Invoke-Tool clang.exe ($cflags + "-c", "$PSScriptRoot\shim.c", "-o", "$o\shim.o")
Invoke-Tool ld.lld.exe ("-T", "$PSScriptRoot\shim.ld", "-o", "$o\shim.elf", "$o\start.o", "$o\shim.o")
Invoke-Tool llvm-objcopy.exe ("-O", "binary", "$o\shim.elf", "$o\Image")
python "$PSScriptRoot\..\tools\mkbootimg.py" "$o\Image" $Dtb $Out
if ($LASTEXITCODE) { throw "mkbootimg failed" }
