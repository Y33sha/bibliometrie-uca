# =============================================================
# Dockerfile de production — multi-stage
# Le backend sert à la fois l'API et le frontend buildé (SPA)
# =============================================================

# ---- Étape 1 : build du frontend ----
FROM node:22-slim AS frontend-build

WORKDIR /build
COPY interfaces/frontend/package*.json ./
RUN npm ci
COPY interfaces/frontend/ .
RUN npm run build

# ---- Étape 2 : image Python finale ----
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY application/     ./application/
COPY domain/          ./domain/
COPY infrastructure/  ./infrastructure/
COPY interfaces/      ./interfaces/
COPY run_pipeline.py  .

RUN pip install --no-cache-dir .

# Frontend buildé (servi par l'API via SPAStaticFiles)
COPY --from=frontend-build /build/build ./interfaces/frontend/build

EXPOSE 8000

CMD ["uvicorn", "interfaces.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
