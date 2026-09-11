#!/bin/bash
# Lance le backend + frontend en dev (uvicorn via le venv du projet, géré par uv).
# `bash start.sh <nom>` lance l'instance décrite par instances/<nom>/instance.env.
if [ -n "$1" ]; then
    export BIBLIO_INSTANCE="$1"
fi
uv run python -m interfaces.cli.dev.serve_api &
cd interfaces/frontend && npm run dev
