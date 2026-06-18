"""Abstraction du store de payloads bruts (raw store).

Un `RawStore` conserve hors BDD les payloads JSON bruts renvoyés par les APIs
sources, pour re-normalisation / audit / re-matérialisation. Deux
implémentations : `LocalFileRawStore` (dev) et, à venir, un backend S3-compatible
(Backblaze B2) en prod.

Clé logique = `(source, source_id)`. L'encodage de cette clé en chemin/objet
physique (URL-encoding du `source_id`, compression gzip) est un détail de
chaque implémentation, pas du contrat.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol


class RawStore(Protocol):
    """Contrat d'un store de payloads bruts, indexé par `(source, source_id)`."""

    def put(self, source: str, source_id: str, payload: bytes) -> None:
        """Écrit (ou écrase) le payload brut de `(source, source_id)`."""

    def get(self, source: str, source_id: str) -> bytes:
        """Retourne le payload brut. Lève `KeyError` si absent."""

    def exists(self, source: str, source_id: str) -> bool:
        """True si un payload est stocké pour `(source, source_id)`."""

    def delete(self, source: str, source_id: str) -> bool:
        """Supprime le payload de `(source, source_id)`. True si un payload existait.

        Idempotent : une clé absente retourne False sans lever.
        """

    def iter_keys(self, source: str) -> Iterator[str]:
        """Itère les `source_id` (clés logiques décodées) stockés pour `source`."""
