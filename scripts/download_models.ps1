$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$ModelDir = Join-Path $Root "main\desk-agent\models\SenseVoiceSmall"
$ModelPath = Join-Path $ModelDir "model.pt"
$ModelUrl = "https://modelscope.cn/models/iic/SenseVoiceSmall/resolve/master/model.pt"

New-Item -ItemType Directory -Force $ModelDir | Out-Null
if (Test-Path $ModelPath) {
    Write-Host "SenseVoiceSmall model already exists: $ModelPath"
    exit 0
}

Write-Host "Downloading SenseVoiceSmall (about 900 MB)..."
Invoke-WebRequest -Uri $ModelUrl -OutFile $ModelPath
Write-Host "Model downloaded: $ModelPath"

