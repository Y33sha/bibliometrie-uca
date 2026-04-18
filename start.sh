#!/bin/bash
# Lance le backend + frontend en dev
python -m uvicorn interfaces.api.app:app --host 127.0.0.1 --port 8003 --reload &
cd interfaces/frontend && npm run dev -- --port 5176
