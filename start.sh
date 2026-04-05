#!/bin/bash
# Lance le backend + frontend en dev
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8003 --reload &
cd frontend && npm run dev -- --port 5176
