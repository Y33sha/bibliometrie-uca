"""Encodage de textes en vecteurs (embeddings) par un modèle ONNX exécuté sur CPU (fastembed)."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast

import numpy as np

from infrastructure import PROJECT_ROOT
from infrastructure.embedding_model import EMBEDDING_MODEL
from infrastructure.settings import settings


class TextEncoder(Protocol):
    """Encodeur de textes en vecteurs normalisés."""

    model: str
    """Nom du modèle, enregistré avec chaque vecteur."""

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """Renvoie le vecteur normalisé de chaque texte, dans l'ordre."""
        ...


def model_dir() -> Path:
    """Renvoie le répertoire des fichiers du modèle (`embeddings_model_dir`, à défaut `data/models`)."""
    return (
        Path(settings.embeddings_model_dir)
        if settings.embeddings_model_dir
        else PROJECT_ROOT / "data" / "models"
    )


class FastembedEncoder:
    """Encodeur fastembed. Le modèle se charge au premier `encode`, depuis `model_dir()`, et se télécharge s'il en est absent."""

    model = EMBEDDING_MODEL

    def __init__(self, batch_size: int = 64) -> None:
        self._batch_size = batch_size
        self._embedding = None

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if self._embedding is None:
            from fastembed import TextEmbedding

            self._embedding = TextEmbedding(self.model, cache_dir=str(model_dir()))
        vectors = np.array(
            list(self._embedding.embed(list(texts), batch_size=self._batch_size)), dtype=np.float32
        )
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        return cast(list[list[float]], vectors.tolist())
