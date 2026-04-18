#!/bin/bash
# Lance le backend + frontend en mode sandbox (base bibliometrie_sandbox)
export BIBLIOMETRIE_SANDBOX=1
echo "=== MODE SANDBOX — base bibliometrie_sandbox ==="
python -m uvicorn interfaces.api.app:app --host 127.0.0.1 --port 8004 --reload &
cd frontend && API_TARGET=http://127.0.0.1:8004 npm run dev -- --port 5177
