# Builds the optional Rust fast path and puts the DLL where playfellow_coop looks for it.
# Needs a Rust toolchain on PATH (https://rustup.rs). Keep it off your system drive if you like: set RUSTUP_HOME and
# CARGO_HOME to folders of your choice BEFORE installing, and CARGO_TARGET_DIR before building.
#   powershell -ExecutionPolicy Bypass -File rust/build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$manifest = Join-Path $root "rust\fastpath\Cargo.toml"
cargo test --release --manifest-path $manifest
cargo build --release --manifest-path $manifest
$target = if ($env:CARGO_TARGET_DIR) { $env:CARGO_TARGET_DIR } else { Join-Path $root "rust\fastpath\target" }
$dll = Get-ChildItem -Path $target -Recurse -Filter "pf_fastpath.dll" | Where-Object { $_.FullName -match "release" } | Select-Object -First 1
if (-not $dll) { throw "pf_fastpath.dll was not built" }
$dest = Join-Path $root "playfellow_coop\_native"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item $dll.FullName (Join-Path $dest "pf_fastpath.dll") -Force
Write-Host "Built: $dest\pf_fastpath.dll"
Write-Host "Check it: python -c ""from playfellow_coop import fastpath; print(fastpath.available())"""
