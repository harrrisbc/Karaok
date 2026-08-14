Set-Location $PSScriptRoot\..
if (-not (Test-Path .\.venv\Scripts\python.exe)) {
  Write-Error "Create the venv first: py -3.11 -m venv .venv"
  exit 1
}
& .\.venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8000
