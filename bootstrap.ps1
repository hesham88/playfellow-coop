# PlayFellow co-op: install on Windows (the one-line installer runs this for you).
#   powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1
# Creates .venv here with Python 3.11-3.13, clones the engine at its pinned tag beside this folder, installs both, then runs the doctor.
# It sends no key and calls no model. Re-running it is safe: finished steps are skipped. Every step's exit code is checked.
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$engine = Join-Path (Split-Path $repo -Parent) "playfellow"

function Step([string]$what, [scriptblock]$run) {
    & $run
    if ($LASTEXITCODE -ne 0) { throw "This step failed: $what (exit code $LASTEXITCODE). Nothing after it was run." }
}

# Python 3.11 to 3.13: the engine's pygame has no build for 3.14 yet.
$python = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in "3.13", "3.12", "3.11") {
        & py "-$v" -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) { $python = @("py", "-$v"); break }
    }
}
if (-not $python -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $v = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ($v -in "3.11", "3.12", "3.13") { $python = @("python") }
}
if (-not $python) { throw "PlayFellow needs Python 3.11, 3.12 or 3.13 (3.14 is too new for the engine's pygame). Install 3.13 from python.org, then run this again." }

$venvPy = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "Creating the virtual environment (.venv) with $($python -join ' ')..."
    $pyExe = $python[0]
    $pyArgs = @($python | Select-Object -Skip 1) + @("-m", "venv", (Join-Path $repo ".venv"))
    Step "create the virtual environment" { & $pyExe @pyArgs }
}
if (-not (Test-Path (Join-Path $engine ".git"))) {
    Write-Host "Cloning the PlayFellow engine at tag pre-hackathon into $engine ..."
    Step "clone the engine" { git clone --depth 1 --branch pre-hackathon https://github.com/hesham88/playfellow.git $engine }
}
Step "update pip" { & $venvPy -m pip install --upgrade pip --quiet }
Write-Host "Installing the engine and PlayFellow co-op (with the widget and the game packs)..."
Step "install the engine" { & $venvPy -m pip install -e $engine --quiet }
Step "install PlayFellow co-op" { & $venvPy -m pip install -e "$repo[all]" pytest setuptools --quiet }

Push-Location $repo
try { & $venvPy -m playfellow_coop doctor } finally { Pop-Location }
Write-Host ""
Write-Host "Next: start your game, then in this folder:  .\playfellow games   (no activation needed)"
