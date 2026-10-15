#!/bin/bash
# Lance le backend + frontend en dev (uvicorn via le venv du projet, géré par uv).
# `bash start.sh <nom>` lance l'instance décrite par instances/<nom>/instance.env.
if [ -n "$1" ]; then
    export BIBLIO_INSTANCE="$1"
fi
# Signale une base en retard sur les migrations du dépôt.
revision=$(uv run python -m alembic current 2>/dev/null)
if [[ "$revision" != *"(head)"* ]]; then
    echo "Base ${BIBLIO_INSTANCE:-par défaut} à la révision ${revision:-inconnue}, en retard sur les migrations : lancer migrate_all." >&2
fi
uv run python -m interfaces.cli.dev.serve_api &
cd interfaces/frontend && npm run dev
