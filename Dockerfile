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
#
# Images de base épinglées par empreinte, l'étiquette restant en commentaire pour la lisibilité
# et pour le robot de mise à jour, qui suit les deux. Une étiquette se redéplace sur une autre
# image ; l'empreinte désigne celle qui a été examinée. La construction reste non reproductible
# à l'octet près — la mise à jour des paquets système appliquée plus bas prend ce qui est publié
# au moment où elle tourne —, mais son point de départ, lui, est celui qu'on croit.
FROM node:24-slim@sha256:ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e AS frontend-build

ARG ROOT_PATH
ENV BASE_PATH=$ROOT_PATH

WORKDIR /app/interfaces/frontend
COPY interfaces/frontend/package*.json ./
RUN npm ci
COPY interfaces/frontend/ .
RUN npm run build

# ---- Étape 2 : binaire uv ----
#
# Image officielle réduite au binaire, épinglée par son empreinte comme les autres. La version y
# est désignée : une installation par l'installateur de paquets prendrait celle publiée au moment
# de la construction, sans que rien ne dise laquelle.
FROM ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff AS uv

# ---- Étape 3 : image Python finale ----
FROM python:3.14-slim@sha256:656d12e70054d5fda18a045e2494c96701e9792dd1445f95b3d038df954f57e9

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

# `uv sync --frozen` plus bas installe exactement les versions de uv.lock, celles sur lesquelles
# l'intégration exécute ses tests et ses analyses.
COPY --from=uv /uv /usr/local/bin/uv

# L'installation des dépendances passant par `uv`, l'image n'a pas d'emploi pour pip, que l'image
# de base préinstalle. Le retirer ôte de l'exécution un installateur de paquets, et avec lui les
# dépendances qu'il embarque — que l'analyse d'image compte parmi les paquets présents, et qui
# vieillissent au rythme de l'image de base. Le retrait précède l'installation : la construction
# échouerait si quoi que ce soit en dépendait encore.
RUN python -m pip uninstall --yes pip

COPY pyproject.toml uv.lock ./
COPY application/     ./application/
COPY domain/          ./domain/
COPY infrastructure/  ./infrastructure/
COPY interfaces/      ./interfaces/

# `--no-cache` : le cache que l'installation remplit ne resservirait qu'à une installation
# ultérieure, qui n'a pas lieu dans l'image. Sans lui, l'image transporte les archives des
# paquets en plus des paquets eux-mêmes, et les fait passer sous l'analyse d'image.
RUN uv sync --frozen --no-dev --no-cache

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
#
# Forme exec : le serveur tient le premier numéro de processus et reçoit le signal d'arrêt.
# En forme shell, `/bin/sh` s'interpose, garde ce numéro, et n'ayant pas de gestionnaire pour
# ce signal, ne le relaie pas — l'arrêt du conteneur consomme alors le délai de grâce entier
# et coupe les connexions en cours.
CMD ["uvicorn", "interfaces.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
