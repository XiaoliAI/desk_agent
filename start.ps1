$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "main\desk-agent"
$Frontend = Join-Path $Root "main\desk-agent-ui"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"
$Model = Join-Path $Backend "models\SenseVoiceSmall\model.pt"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}
if (-not (Test-Path $Model)) {
    throw "ASR model not found. Run .\scripts\download_models.ps1 first."
}

$backendProcess = Start-Process -FilePath $Python -ArgumentList "start_all.py" -WorkingDirectory $Backend -PassThru -WindowStyle Hidden
$frontendProcess = Start-Process -FilePath $Python -ArgumentList "start.py" -WorkingDirectory $Frontend -PassThru -WindowStyle Hidden

Write-Host "Desk Agent started."
Write-Host "Digital human UI: http://127.0.0.1:8006/index.html"
Write-Host "Agent WebSocket: ws://127.0.0.1:8000/xiaozhi/v1/"
Write-Host "Press Ctrl+C to stop all services."

try {
    while (-not $backendProcess.HasExited -and -not $frontendProcess.HasExited) {
        Start-Sleep -Seconds 1
        $backendProcess.Refresh()
        $frontendProcess.Refresh()
    }
    if ($backendProcess.HasExited) {
        throw "Backend exited with code $($backendProcess.ExitCode)."
    }
    throw "Digital human UI exited with code $($frontendProcess.ExitCode)."
}
finally {
    foreach ($process in @($frontendProcess, $backendProcess)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
        }
    }
}

