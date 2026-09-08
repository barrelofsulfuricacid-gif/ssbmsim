# Windows uses the same supported Linux build through WSL.
$ErrorActionPreference = 'Stop'
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL is required. Run: wsl --install -d Ubuntu-22.04'
}
& wsl.exe --cd $PSScriptRoot python3 tools/setup.py @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
