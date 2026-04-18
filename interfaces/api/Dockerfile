FROM python:3.12-slim

WORKDIR /app

# Les deps viennent de pyproject.toml. En dev, le code applicatif est monté
# en volume via docker-compose (il écrase ce qui est copié ici).
COPY pyproject.toml .
COPY application/     ./application/
COPY domain/          ./domain/
COPY infrastructure/  ./infrastructure/
COPY interfaces/      ./interfaces/

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "interfaces.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
