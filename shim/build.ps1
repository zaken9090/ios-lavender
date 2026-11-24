# Builds the shim and packs it as a boot image for `fastboot boot`.
# usage: .\build.ps1 -Dtb <lavender dtb> [-Payload payload.bin | -SelfTest] [-Out out\shim.img]
#   -Payload   append a payload made by tools\mkpayload.py (kernel + ADT + command line)
#   -SelfTest  build and append the loader self-test (shim\selftest\fake.c)
# Needs LLVM for Windows (clang, ld.lld, llvm-objcopy, llvm-nm) and Python 3.
param(
    [Parameter(Mandatory)][string]$Dtb,
    [string]$Payload,
    [switch]$SelfTest,
    [string]$Out,
    [string]$Llvm = "C:\Program Files\LLVM\bin"
)
$ErrorActionPreference = "Stop"
$o = "$PSScriptRoot\out"
$tools = "$PSScriptRoot\..\tools"
if (-not $Out) { $Out = "$o\shim.img" }   # $PSScriptRoot is empty inside param() on PowerShell 5.1
New-Item -ItemType Directory -Force $o | Out-Null
$cflags = "--target=aarch64-none-elf", "-mcpu=cortex-a53", "-ffreestanding", "-fno-builtin", "-fno-pic",
          "-fno-stack-protector", "-mgeneral-regs-only", "-mstrict-align", "-O2", "-Wall", "-Wextra"
function Invoke-Tool($exe, $toolArgs) {
    & "$Llvm\$exe" @toolArgs
    if ($LASTEXITCODE) { throw "$exe failed" }
}
function Invoke-Python($pyArgs) {
    python @pyArgs
    if ($LASTEXITCODE) { throw "python $($pyArgs[0]) failed" }
}

Invoke-Tool clang.exe ($cflags + "-c", "$PSScriptRoot\start.S", "-o", "$o\start.o")
Invoke-Tool clang.exe ($cflags + "-c", "$PSScriptRoot\shim.c", "-o", "$o\shim.o")
Invoke-Tool ld.lld.exe ("-T", "$PSScriptRoot\shim.ld", "-o", "$o\shim.elf", "$o\start.o", "$o\shim.o")
Invoke-Tool llvm-objcopy.exe ("-O", "binary", "$o\shim.elf", "$o\Image")

if ($SelfTest) {
    Invoke-Tool clang.exe ($cflags + "-c", "$PSScriptRoot\selftest\fake.c", "-o", "$o\fake.o")
    Invoke-Tool ld.lld.exe ("-T", "$PSScriptRoot\selftest\fake.ld", "-o", "$o\fake.elf", "$o\fake.o")
    Invoke-Tool llvm-objcopy.exe ("-O", "binary", "$o\fake.elf", "$o\fake.bin")
    $Payload = "$o\selftest-payload.bin"
    Invoke-Python ("$tools\mkpayload.py", $Payload, "--flat", "$o\fake.bin", "--memsize", "0x80000", "--cmdline", "selftest=1")
}

if ($Payload) {
    # The payload sits at the linker symbol _payload, after the stacks; the header's image size grows by it.
    $sym = @{}
    & "$Llvm\llvm-nm.exe" "$o\shim.elf" | ForEach-Object { $f = $_ -split '\s+'; $sym[$f[2]] = [Convert]::ToUInt64($f[0], 16) }
    $image = [System.IO.File]::ReadAllBytes("$o\Image")
    $blob = [System.IO.File]::ReadAllBytes((Resolve-Path $Payload))
    $padded = New-Object byte[] ([int]($sym["_payload"] - $sym["_image_start"]) + $blob.Length)
    [Array]::Copy($image, $padded, $image.Length)
    [Array]::Copy($blob, 0, $padded, $padded.Length - $blob.Length, $blob.Length)
    [BitConverter]::GetBytes([uint64]$padded.Length).CopyTo($padded, 0x10)
    [System.IO.File]::WriteAllBytes("$o\Image", $padded)
}
Invoke-Python ("$tools\mkbootimg.py", "$o\Image", $Dtb, $Out)
