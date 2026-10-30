# Image de production : l'API sert aussi le frontend buildé.
#
# Préfixe de déploiement : `ROOT_PATH`, vide par défaut (service à la racine). Le build du frontend le reçoit en `BASE_PATH`, l'application le lit à l'exécution :
#   docker build --build-arg ROOT_PATH=/foo ...
#   docker run -e ROOT_PATH=/foo ...
#
# Images de base épinglées par empreinte ; l'étiquette reste lisible, et le robot de mise à jour suit les deux.

ARG ROOT_PATH=

# ---- Étape 1 : build du frontend ----
FROM node:26-slim@sha256:36793bcbb160a6a16cede1e62b93f84e26b78a972a8a4c0b879c1c12f22761ec AS frontend-build

ARG ROOT_PATH
ENV BASE_PATH=$ROOT_PATH

WORKDIR /app/interfaces/frontend
COPY interfaces/frontend/package*.json ./
RUN npm ci
COPY interfaces/frontend/ .
RUN npm run build

# ---- Étape 2 : binaire uv ----
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

# ---- Étape 3 : image Python finale ----
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

ARG ROOT_PATH
ENV ROOT_PATH=$ROOT_PATH

WORKDIR /app

# Correctifs de sécurité des paquets système publiés depuis l'image de base.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Les dépendances s'installent par uv : pip et ses dépendances sortent de l'image et de l'analyse d'image.
RUN python -m pip uninstall --yes pip

COPY pyproject.toml uv.lock ./
COPY application/     ./application/
COPY domain/          ./domain/
COPY infrastructure/  ./infrastructure/
COPY interfaces/      ./interfaces/

# Versions de `uv.lock`, celles de l'intégration continue. uv est monté pour cette seule instruction, et `--no-cache` écarte les archives des paquets : l'image finale ne contient ni l'un ni les autres.
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-cache

ENV PATH="/app/.venv/bin:${PATH}"

# Frontend buildé, servi par l'API (`SPAStaticFiles`).
COPY --from=frontend-build /app/interfaces/frontend/build ./interfaces/frontend/build

# Utilisateur non privilégié. `data/` et `logs/` sont créés dans l'image : un volume monté dessus appartient alors à l'utilisateur applicatif.
RUN mkdir -p /app/data /app/logs \
    && useradd --uid 10001 --home-dir /app --shell /usr/sbin/nologin --no-create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# L'application gère le préfixe de déploiement (`ROOT_PATH`), derrière un proxy qui le retire comme derrière un proxy qui le transmet. `--root-path` le doublerait dans le second cas.
#
# Forme exec : uvicorn est le processus 1 et reçoit le signal d'arrêt du conteneur.
CMD ["uvicorn", "interfaces.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
