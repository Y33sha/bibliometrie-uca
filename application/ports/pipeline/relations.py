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


class ErratumTitleMatch(NamedTuple):
    """Un erratum rapproché de l'œuvre qu'il corrige par le titre (signal #3). Le titre d'un erratum
    reproduit verbatim celui du parent après un préfixe (« Erratum: », « Corrigendum to »…), donc le
    `title_normalized` du parent est un suffixe de celui de l'erratum — rapprochement exact, pas
    flou. La cible est désignée par son DOI (parent au corpus, donc résoluble en `publication_id`)."""

    erratum_id: int
    parent_doi: str


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

    def fetch_erratum_title_matches(self, conn: Connection) -> list[ErratumTitleMatch]:
        """Les erratums rapprochés par titre de l'œuvre qu'ils corrigent (signal #3).

        Pour chaque erratum, candidats = publications non-erratum, au corpus (DOI présent), titre
        assez long, publiées dans la fenêtre `[année − 2 … année]`, dont le `title_normalized` est un
        suffixe de celui de l'erratum. Garde d'ambiguïté : on ne rapproche que si **exactement un**
        candidat « substantiel » (hors `preprint` et `dataset`, qui ne sont que des formes de la même
        œuvre) porte ce titre — deux articles distincts au même titre = collision, on s'abstient."""
        ...

    def replace_title_match_relations(self, conn: Connection, edges: list[RelationEdge]) -> int:
        """Remplace les relations rapprochées par titre (`source` title_match) par `edges`, avec la
        même résolution/dédup que `replace_declared_relations`."""
        ...
