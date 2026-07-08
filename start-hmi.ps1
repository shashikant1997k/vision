# Launch the VIS HMI with the Baumer GigE camera.
# Usage:  .\start-hmi.ps1        (from E:\vision\camera)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$env:VIS_CAMERA   = "gige"
$env:VIS_GENTL_CTI = "E:\vision\Baumer_GAPI_SDK_2.16.1_win_x86_64_cpp\bin\bgapi2_gige.cti"

# Use the in-house ocr-trainer recogniser when a trained model is present at
# E:\vision\ocr-trainer\model\ (ocrab_svtr256.onnx / vis_ocr.onnx). Until then the
# reader falls back to the built-in engine automatically, so this is always safe.
$env:VIS_TEXT_READER = "vis_ocr"

if (-not (Test-Path $env:VIS_GENTL_CTI)) {
    Write-Warning "GenTL producer not found at $env:VIS_GENTL_CTI - HMI will fall back to the simulator."
}

# Refuse to start a second instance (a GigE camera can be owned by one process only).
if (Get-Process vis-hmi -ErrorAction SilentlyContinue) {
    Write-Warning "vis-hmi is already running. Close it first, or use that window."
    return
}

Write-Host "Starting HMI with VIS_CAMERA=gige ..." -ForegroundColor Green
& (Join-Path $here ".venv\Scripts\vis-hmi.exe")
