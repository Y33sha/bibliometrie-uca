"""Port : SQL de la phase `relations` (population de `publication_relations`).

Implémenté par `infrastructure.queries.pipeline.relations.PgPublicationRelationsQueries`.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection

from domain.types import JsonValue


class DeclaredRelationSource(NamedTuple):
    """Une `source_publication` rattachée qui déclare des relations dans son `meta`
    (DataCite `related_identifiers` ou Crossref `relation`)."""

    publication_id: int
    source: str
    meta: dict[str, JsonValue]


class RelationEdge(NamedTuple):
    """Une arête de relation à persister : publication déclarante → DOI cible, typée."""

    from_publication_id: int
    relation_type: str
    target_doi: str
    source: str


class PublicationRelationsQueries(Protocol):
    """Opérations SQL de la phase `relations`."""

    def fetch_declared_relation_sources(self, conn: Connection) -> list[DeclaredRelationSource]:
        """Les `source_publications` rattachées dont le `meta` déclare des relations."""
        ...

    def replace_declared_relations(self, conn: Connection, edges: list[RelationEdge]) -> int:
        """Remplace les relations déclarées (`source` datacite/crossref) par `edges` :
        résout chaque `target_doi` en `target_publication_id`, écarte les auto-relations,
        dédoublonne par `(from, type, target)`. Retourne le nombre de relations écrites."""
        ...
