$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "main\desk-agent"
$VenvPython = Join-Path $Backend ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating Python 3.10 virtual environment..."
    py -3.10 -m venv (Join-Path $Backend ".venv")
}

& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $Backend "requirements.txt")
& $VenvPython -m pip install -r (Join-Path $Root "main\desk-agent-ui\wakeword_runtime\requirements.txt")

$PrivateConfig = Join-Path $Backend "data\.config.yaml"
if (-not (Test-Path $PrivateConfig)) {
    New-Item -ItemType Directory -Force (Split-Path $PrivateConfig) | Out-Null
    Copy-Item (Join-Path $Backend "config.example.yaml") $PrivateConfig
    Write-Host "Created main\desk-agent\data\.config.yaml"
}

Write-Host "Setup complete. Fill in data/.config.yaml, then download the ASR model."

