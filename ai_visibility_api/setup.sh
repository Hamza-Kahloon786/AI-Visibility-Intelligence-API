#!/usr/bin/env bash
set -e

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example -- add your OPENAI_API_KEY before triggering the pipeline."
fi

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -r requirements.txt

export FLASK_APP=run.py
flask db upgrade

echo ""
echo "Setup complete. Start the API with:"
echo "  source .venv/bin/activate && python run.py"
