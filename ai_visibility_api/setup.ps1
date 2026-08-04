$ErrorActionPreference = "Stop"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example -- add your OPENAI_API_KEY before triggering the pipeline."
}

python -m venv .venv
& ".\.venv\Scripts\pip.exe" install -r requirements.txt

$env:FLASK_APP = "run.py"
& ".\.venv\Scripts\flask.exe" db upgrade

Write-Host ""
Write-Host "Setup complete. Start the API with:"
Write-Host "  .\.venv\Scripts\python.exe run.py"
