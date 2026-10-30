"""Archive des payloads bruts des sources (raw store).

Un `RawStore` garde hors base les payloads JSON bruts renvoyés par les API des sources, pour normaliser de nouveau, auditer ou reconstruire. Implémentations : `LocalFileRawStore`, `NullRawStore`.

La clé est `(source, source_id)` ; son encodage en chemin relève de l'implémentation.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol


class UnreadablePayloadError(Exception):
    """Payload illisible pour une clé : fichier tronqué ou corrompu."""


class RawStore(Protocol):
    """Contrat d'un store de payloads bruts, indexé par `(source, source_id)`."""

    def put(self, source: str, source_id: str, payload: bytes) -> None:
        """Écrit, ou écrase, le payload brut de la clé."""

    def get(self, source: str, source_id: str) -> bytes:
        """Renvoie le payload brut de la clé.

        Raises:
            KeyError: le payload manque.
            UnreadablePayloadError: le payload est illisible.
        """

    def exists(self, source: str, source_id: str) -> bool:
        """Vrai si un payload est stocké pour la clé."""

    def delete(self, source: str, source_id: str) -> bool:
        """Supprime le payload de la clé. Renvoie vrai s'il existait."""

    def iter_keys(self, source: str) -> Iterator[str]:
        """Itère les `source_id` stockés pour la source."""
