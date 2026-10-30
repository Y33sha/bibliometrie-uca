"""`RawStore` qui ne conserve rien.

L'archivage des réponses brutes sert à rejouer les traitements sans interroger de nouveau les sources. Sans archivage, un déploiement évite d'ouvrir un emplacement en écriture. Ce store accepte les écritures sans les conserver, et se lit comme un store vide.
"""

from __future__ import annotations

from collections.abc import Iterator


class NullRawStore:
    """`RawStore` sans stockage."""

    def put(self, source: str, source_id: str, payload: bytes) -> None:
        return None

    def get(self, source: str, source_id: str) -> bytes:
        raise KeyError(f"{source}/{source_id}")

    def exists(self, source: str, source_id: str) -> bool:
        return False

    def delete(self, source: str, source_id: str) -> bool:
        return False

    def iter_keys(self, source: str) -> Iterator[str]:
        return iter(())
