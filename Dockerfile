# Image de production : l'API sert aussi le frontend buildé.
#
# Préfixe de déploiement : `ROOT_PATH`, vide par défaut (service à la racine). Le build du frontend le reçoit en `BASE_PATH`, l'application le lit à l'exécution :
#   docker build --build-arg ROOT_PATH=/foo ...
#   docker run -e ROOT_PATH=/foo ...
#
# Images de base épinglées par empreinte ; l'étiquette reste lisible, et le robot de mise à jour suit les deux.

ARG ROOT_PATH=

# ---- Étape 1 : build du frontend ----
FROM node:26-slim@sha256:e6bedef217677b276c591795e169840edd9096dbf13f29df8ef8d1856b8820bc AS frontend-build

ARG ROOT_PATH
ENV BASE_PATH=$ROOT_PATH

WORKDIR /app/interfaces/frontend
COPY interfaces/frontend/package*.json ./
RUN npm ci
COPY interfaces/frontend/ .
RUN npm run build

# ---- Étape 2 : binaire uv ----
FROM ghcr.io/astral-sh/uv:0.13.10@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f AS uv

# ---- Étape 3 : image Python finale ----
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f

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

# Dépendances seules, avant le code : leur couche reste en cache tant que `uv.lock` ne change pas. Versions de `uv.lock`, celles de l'intégration continue. uv est monté pour cette seule instruction, et `--no-cache` écarte les archives des paquets : l'image finale ne contient ni l'un ni les autres.
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-cache --no-install-project

COPY application/     ./application/
COPY domain/          ./domain/
COPY infrastructure/  ./infrastructure/
COPY interfaces/      ./interfaces/
COPY pipeline/        ./pipeline/

RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-cache

ENV PATH="/app/.venv/bin:${PATH}"

# Frontend buildé, servi par l'API (`SPAStaticFiles`).
COPY --from=frontend-build /app/interfaces/frontend/build ./interfaces/frontend/build

# Utilisateur non privilégié. `data/` et `logs/` sont créés dans l'image : un volume monté dessus appartient alors à l'utilisateur applicatif. Le reste de `/app` reste à root, lisible par tous : un `chown` récursif recopierait l'environnement Python dans une couche de plus.
RUN mkdir -p /app/data /app/logs \
    && useradd --uid 10001 --home-dir /app --shell /usr/sbin/nologin --no-create-home appuser \
    && chown appuser:appuser /app/data /app/logs
USER appuser

EXPOSE 8000

# L'application gère le préfixe de déploiement (`ROOT_PATH`), derrière un proxy qui le retire comme derrière un proxy qui le transmet. `--root-path` le doublerait dans le second cas.
#
# Forme exec : uvicorn est le processus 1 et reçoit le signal d'arrêt du conteneur.
CMD ["uvicorn", "interfaces.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
