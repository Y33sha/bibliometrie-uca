# =============================================================
# Dockerfile de production — multi-stage
# Le backend sert à la fois l'API et le frontend buildé (SPA)
# =============================================================
#
# Préfixe de déploiement (URL sous laquelle l'appli est servie) :
# - BASE_PATH consommé au BUILD par SvelteKit (URL générées en dur)
# - ROOT_PATH consommé au RUNTIME par uvicorn (`--root-path`)
# Les deux doivent matcher. Vide par défaut → app servie à la racine (accès
# direct sans reverse-proxy). Définir un sous-chemin pour un déploiement
# derrière un proxy qui transmet ce préfixe :
#   docker build --build-arg ROOT_PATH=/foo ...
#   docker run -e ROOT_PATH=/foo ...

ARG ROOT_PATH=

# ---- Étape 1 : build du frontend ----
FROM node:22-slim AS frontend-build

ARG ROOT_PATH
ENV BASE_PATH=$ROOT_PATH

# Préserve l'arborescence repo (interfaces/frontend + docs/) : la route /docs
# lit les markdown de `docs/` via un glob Vite remontant à la racine du repo
# (`../../../../../docs`). Sans `docs/` à la bonne position, la doc serait vide.
WORKDIR /build/interfaces/frontend
COPY interfaces/frontend/package*.json ./
RUN npm ci
COPY interfaces/frontend/ .
COPY docs/ /build/docs/
RUN npm run build

# ---- Étape 2 : image Python finale ----
FROM python:3.12-slim

ARG ROOT_PATH
ENV ROOT_PATH=$ROOT_PATH

WORKDIR /app

# Installer uv (utilisé pour `uv sync --frozen` qui installe
# exactement les versions de uv.lock — mêmes versions que CI + dev).
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY application/     ./application/
COPY domain/          ./domain/
COPY infrastructure/  ./infrastructure/
COPY interfaces/      ./interfaces/
COPY run_pipeline.py  .

RUN uv sync --frozen --no-dev

# Ajouter le venv de uv au PATH (évite `uv run` à chaque invocation).
ENV PATH="/app/.venv/bin:${PATH}"

# Frontend buildé (servi par l'API via SPAStaticFiles)
COPY --from=frontend-build /build/interfaces/frontend/build ./interfaces/frontend/build

# Exécution sous un utilisateur non privilégié : l'API ne requiert aucun droit root
# (port 8000 > 1024, logs sur stdout).
#
# `data/` et `logs/` sont créés ici pour qu'un volume monté dessus hérite de leur
# propriétaire : un volume créé sur un chemin absent de l'image appartiendrait à root, et
# l'uid applicatif ne pourrait pas y écrire.
RUN mkdir -p /app/data /app/logs \
    && useradd --uid 10001 --home-dir /app --shell /usr/sbin/nologin --no-create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Shell form pour interpoler $ROOT_PATH (default défini en haut, surchargeable
# via `docker run -e ROOT_PATH=...`).
CMD uvicorn interfaces.api.app:app --host 0.0.0.0 --port 8000 --root-path "$ROOT_PATH"
