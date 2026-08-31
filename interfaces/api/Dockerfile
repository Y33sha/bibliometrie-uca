FROM python:3.12-slim

WORKDIR /app

# Le venv vit hors de `/app`, que la composition de développement recouvre par un montage
# depuis le poste : logé dedans, il disparaîtrait sous le montage.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

RUN pip install --no-cache-dir uv

# Les versions viennent de `uv.lock`, comme l'intégration et l'image de production.
# `--extra dev` ajoute pytest, ruff et mypy, pour lancer les contrôles dans le conteneur.
# Le code applicatif copié ici est recouvert par le montage de la composition.
COPY pyproject.toml uv.lock ./
COPY application/     ./application/
COPY domain/          ./domain/
COPY infrastructure/  ./infrastructure/
COPY interfaces/      ./interfaces/

RUN uv sync --frozen --extra dev

EXPOSE 8000

CMD ["uvicorn", "interfaces.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
