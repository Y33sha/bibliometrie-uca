# Image de développement de l'API, pour la composition de développement.
FROM ghcr.io/astral-sh/uv:0.13.10@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f AS uv

FROM python:3.14-slim@sha256:22eafb370920ad8b429e0aec3fff433e0669968519f5d60469d83729c138b28b

WORKDIR /app

# Venv hors de `/app`, que la composition recouvre d'un montage depuis le poste.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY --from=uv /uv /usr/local/bin/uv

# Versions de `uv.lock`, groupe `dev` compris (pytest, ruff, pyrefly). Le montage de la composition recouvre le code copié ici.
COPY pyproject.toml uv.lock ./
COPY application/     ./application/
COPY domain/          ./domain/
COPY infrastructure/  ./infrastructure/
COPY interfaces/      ./interfaces/

RUN uv sync --frozen

EXPOSE 8000

CMD ["uvicorn", "interfaces.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
