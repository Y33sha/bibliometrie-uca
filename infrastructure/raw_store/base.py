"""Archive des payloads bruts des sources (raw store).

Un `RawStore` garde hors base les payloads JSON bruts que rendent les API des sources, pour normaliser de nouveau, auditer ou reconstruire. Implémentations : `LocalFileRawStore`, `NullRawStore`.

La clé est `(source, source_id)` ; son encodage en chemin relève de l'implémentation.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol


class UnreadablePayloadError(Exception):
    """Le payload stocké pour une clé est illisible : fichier tronqué ou corrompu."""


class RawStore(Protocol):
    """Contrat d'un store de payloads bruts, indexé par `(source, source_id)`."""

    def put(self, source: str, source_id: str, payload: bytes) -> None:
        """Écrit, ou écrase, le payload brut de la clé."""

    def get(self, source: str, source_id: str) -> bytes:
        """Payload brut de la clé. Lève `KeyError` s'il manque, `UnreadablePayloadError` s'il est illisible."""

    def exists(self, source: str, source_id: str) -> bool:
        """Vrai si un payload est stocké pour la clé."""

    def delete(self, source: str, source_id: str) -> bool:
        """Supprime le payload de la clé, et rend vrai s'il existait. Une clé absente rend faux."""

    def iter_keys(self, source: str) -> Iterator[str]:
        """Itère les `source_id` stockés pour la source."""
