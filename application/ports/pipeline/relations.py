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


class SharedKeyPair(NamedTuple):
    """Deux publications distinctes (DOI distincts) partageant une clé de confirmation (hal_id,
    arXiv, PMID, NNT). `a_id < b_id` par construction. Le type de relation se déduit du couple de
    `doc_type` (`domain.publications.relations.infer_shared_key_relation`)."""

    a_id: int
    a_doc_type: str | None
    a_doi: str
    b_id: int
    b_doc_type: str | None
    b_doi: str


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

    def fetch_shared_key_pairs(self, conn: Connection) -> list[SharedKeyPair]:
        """Les paires de publications distinctes (DOI distincts) partageant une clé de confirmation
        (signal #2)."""
        ...

    def replace_shared_key_relations(self, conn: Connection, edges: list[RelationEdge]) -> int:
        """Remplace les relations issues des clés partagées (`source` shared_key) par `edges`,
        avec la même résolution/dédup que `replace_declared_relations`."""
        ...
