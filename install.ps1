# PlayFellow co-op: the one-line install for Windows.
#   irm https://raw.githubusercontent.com/hesham88/playfellow-coop/main/install.ps1 | iex
# Clones this repository (default: %USERPROFILE%\PlayFellow\playfellow-coop; set $env:PLAYFELLOW_DIR to choose), then runs
# bootstrap.ps1 there: a virtual environment, the engine at its pinned tag beside it, both installed, and the doctor.
# It sends no key and calls no model. Running it again updates the clone and skips finished steps.
# Everything runs inside one script block, so nothing is left behind in your PowerShell session.
& {
    $ErrorActionPreference = "Stop"
    $base = if ($env:PLAYFELLOW_DIR) { $env:PLAYFELLOW_DIR } else { Join-Path $env:USERPROFILE "PlayFellow" }
    $repo = Join-Path $base "playfellow-coop"
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "PlayFellow needs Git (git-scm.com) and Python 3.11-3.13 (python.org). Install them, then run this line again."
    }
    New-Item -ItemType Directory -Force $base | Out-Null
    if (Test-Path (Join-Path $repo ".git")) {
        Write-Host "Updating $repo ..."
        git -C $repo pull --ff-only
    } else {
        Write-Host "Cloning PlayFellow co-op into $repo ..."
        git clone https://github.com/hesham88/playfellow-coop.git $repo
    }
    if ($LASTEXITCODE -ne 0) { throw "Getting PlayFellow co-op failed (git exit code $LASTEXITCODE)." }
    # A process-only bypass: the machine's execution policy is not changed.
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "bootstrap.ps1")
    if ($LASTEXITCODE -ne 0) { throw "The install did not finish (see the message above). Fix it, then run this line again." }
    Write-Host ""
    Write-Host "PlayFellow is in $repo. Start your game, then:"
    Write-Host "  cd `"$repo`""
    Write-Host "  .\playfellow games"
}
