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
FROM node:25-slim AS frontend-build

ARG ROOT_PATH
ENV BASE_PATH=$ROOT_PATH

WORKDIR /app/interfaces/frontend
COPY interfaces/frontend/package*.json ./
RUN npm ci
COPY interfaces/frontend/ .
RUN npm run build

# ---- Étape 2 : image Python finale ----
FROM python:3.12-slim

ARG ROOT_PATH
ENV ROOT_PATH=$ROOT_PATH

WORKDIR /app

# Correctifs de sécurité des paquets système : l'image de base est publiée à intervalles
# espacés, et porte entre deux publications les failles corrigées depuis. La mise à jour les
# applique à la construction ; l'analyse d'image de l'intégration continue vérifie qu'il n'en
# reste aucune de gravité haute pour laquelle un correctif existe.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

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
COPY --from=frontend-build /app/interfaces/frontend/build ./interfaces/frontend/build

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

# L'application porte elle-même le préfixe de déploiement (variable `ROOT_PATH`, lue à sa
# construction), et son routage l'ôte du chemin quand il y est, le laisse intact quand il est
# absent : les deux sortes de reverse-proxy, celui qui retire le préfixe et celui qui le
# transmet, fonctionnent sans réglage supplémentaire.
#
# Le serveur ASGI, lui, reçoit son adresse et son port, rien d'autre. `--root-path` ajoute le
# préfixe au chemin reçu, ce qui le doublerait derrière un proxy qui le transmet.
CMD uvicorn interfaces.api.app:app --host 0.0.0.0 --port 8000
