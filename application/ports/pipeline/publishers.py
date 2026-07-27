"""Port d'accès pipeline à la table `publishers` : trouve-ou-crée d'un éditeur.

Contrat étroit consommé par le trouve-ou-crée d'éditeur (`services/publishers/core.py:find_or_create_publisher`, appelé par les normaliseurs) et par le volet publisher de la phase `publishers_journals`. Servi par l'adapter `PgPublisherGatewayQueries`.

L'édition curée, la fusion et l'enrichissement pays (maintenance) vivent à part, dans `application/ports/repositories/publisher_repository.py`.
"""

from typing import Protocol


class PublisherFindOrCreateQueries(Protocol):
    """Trouve ou crée un éditeur à partir des métadonnées d'une source."""

    def add_publisher_name_form(self, publisher_id: int, form_normalized: str) -> None:
        """Ajoute une forme de nom normalisée pour un éditeur, si absente (idempotent)."""
        ...

    def find_publisher_by_openalex_id(self, openalex_id: str) -> int | None: ...

    def set_publisher_openalex_id_if_missing(self, publisher_id: int, openalex_id: str) -> None:
        """Attribue un `openalex_id` à l'éditeur s'il n'en porte pas déjà un."""
        ...

    def match_or_create_by_name_form(self, name_raw: str, name_normalized: str) -> tuple[int, bool]:
        """`(id, created)` : l'éditeur dont la forme de nom normalisée existe déjà, sinon un éditeur créé et sa forme enregistrée."""
        ...
