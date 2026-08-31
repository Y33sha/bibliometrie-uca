# Image de base épinglée par empreinte, l'étiquette conservée à côté pour la lisibilité
# et pour le robot de mise à jour, qui suit les deux. Une étiquette se redéplace sur une autre
# image ; l'empreinte désigne celle qui a été examinée.
FROM python:3.12-slim@sha256:09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217

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
