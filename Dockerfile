# =============================================================
# Dockerfile de production — multi-stage
# Le backend sert à la fois l'API et le frontend buildé (SPA)
# =============================================================

# ---- Étape 1 : build du frontend ----
FROM node:22-slim AS frontend-build

WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# ---- Étape 2 : image Python finale ----
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code applicatif
COPY backend/        ./backend/
COPY config/__init__.py ./config/
COPY config/settings.docker.py ./config/settings.py
COPY db/              ./db/
COPY extraction/      ./extraction/
COPY processing/      ./processing/
COPY services/        ./services/
COPY utils/           ./utils/
COPY run_pipeline.py  .

# Frontend buildé (servi par le backend via SPAStaticFiles)
COPY --from=frontend-build /build/build ./frontend/build

EXPOSE 8000

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
