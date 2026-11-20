# Image de développement de l'API, pour la composition de développement.
FROM ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d AS uv

FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f

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
