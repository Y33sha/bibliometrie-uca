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
    """Une arête de relation à persister : publication déclarante → cible, typée.

    La cible est désignée par `target_doi` (relations issues des sources, qui pointent
    toujours un DOI — résolu en `target_publication_id` à l'insertion) **ou** directement
    par `target_publication_id` (relations dérivées en interne vers une publication au
    corpus, qui peut ne pas avoir de DOI). Au moins l'un des deux est présent."""

    from_publication_id: int
    relation_type: str
    target_doi: str | None
    source: str
    target_publication_id: int | None = None


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


class TitleMatch(NamedTuple):
    """Une publication rapprochée par titre de l'œuvre dont elle dépend (signal #3) : un erratum de
    l'article qu'il corrige, un preprint de sa version publiée. Le parent est au corpus, désigné par
    son `publication_id` (et son DOI quand il en a un). `child` porte la relation dirigée vers
    `parent` (`is_correction_of`, `is_preprint_of`)."""

    child_id: int
    parent_id: int
    parent_doi: str | None


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

    def fetch_declared_related_pairs(self, conn: Connection) -> set[frozenset[int]]:
        """Les paires déjà reliées par une relation déclarée (signal #1), pour écarter un
        `is_related_to` redondant."""
        ...

    def replace_shared_key_relations(self, conn: Connection, edges: list[RelationEdge]) -> int:
        """Remplace les relations issues des clés partagées (`source` shared_key) par `edges`,
        avec la même résolution/dédup que `replace_declared_relations`."""
        ...

    def fetch_erratum_title_matches(self, conn: Connection) -> list[TitleMatch]:
        """Les erratums rapprochés par titre de l'œuvre qu'ils corrigent (signal #3).

        Pour chaque erratum, candidats = publications non-erratum, titre assez long, publiées dans la
        fenêtre `[année − 2 … année]`, dont le `title_normalized` est un suffixe de celui de
        l'erratum (le titre parent est reproduit verbatim après un préfixe « Erratum: »). Garde
        d'ambiguïté : on ne rapproche que si **exactement un** candidat « substantiel » (hors
        `preprint` et `dataset`, simples formes de la même œuvre) porte ce titre."""
        ...

    def fetch_preprint_title_matches(self, conn: Connection) -> list[TitleMatch]:
        """Les preprints rapprochés par titre de leur version publiée (signal #3).

        Pour chaque preprint, candidats = publications non-preprint au `title_normalized`
        **identique** (le preprint et sa version publiée portent le même titre), titre assez long,
        publiées dans la fenêtre `[année … année + 2]`. Même garde d'ambiguïté : un seul candidat
        substantiel (hors `dataset`) au même titre."""
        ...

    def replace_title_match_relations(self, conn: Connection, edges: list[RelationEdge]) -> int:
        """Remplace les relations rapprochées par titre (`source` title_match) par `edges`, avec la
        même résolution/dédup que `replace_declared_relations`."""
        ...

    def count_by_relation_type(self, conn: Connection) -> list[tuple[str, int]]:
        """`(relation_type, nombre)` par type, décroissant — distribution de `publication_relations`."""
        ...
