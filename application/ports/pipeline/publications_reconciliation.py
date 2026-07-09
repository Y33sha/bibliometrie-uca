"""Port : SQL de la passe de réconciliation des composantes (`reconcile_components`).

Implémenté par `infrastructure.queries.pipeline.publications_reconciliation.PgPublicationsReconciliationQueries`.

La passe lit le **voisinage 1-hop** des `source_publications` marquées `keys_dirty` (les SP dirty + celles qui partagent une clé de confirmation avec elles), décide les assignations SP → pub-ancre (`domain.publications.reconciliation.plan_reconciliation` — assignation, merge et split unifiés : un orphelin se fait matcher/créer/skipper par le même primitif), les applique, puis efface le drapeau. Cf. le raisonnement 1-hop documenté côté domaine.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class ReconcileRow(NamedTuple):
    """Projection d'une `source_publication` du voisinage : clés + publication courante.

    `doc_type`/`title_normalized`/`pub_year` alimentent le token métadonnée thèse de
    `project_confirmation_keys` (les identifiants viennent de `doi`/`external_ids`).
    `publication_id` = `None` si orpheline ; `publication_doi` = DOI canonique de la
    publication courante (`None` si orpheline), pour choisir l'ancre ; `in_perimeter` =
    la SP a ≥1 authorship in-périmètre (gate de création d'une pub neuve)."""

    id: int
    doi: str | None
    external_ids: dict[str, object] | None
    publication_id: int | None
    doc_type: str | None
    title_normalized: str | None
    pub_year: int | None
    publication_doi: str | None
    in_perimeter: bool


class PublicationsReconciliationQueries(Protocol):
    """Opérations SQL de la réconciliation des composantes."""

    def mark_keys_dirty(self, conn: Connection) -> int:
        """Pose `keys_dirty = true` sur toutes les `source_publications` (rebuild complet).

        Retourne le nombre de lignes marquées. Force la réconciliation à dégénérer en
        cluster-then-materialize global (après une évolution des règles de clés).
        """
        ...

    def fetch_dirty_source_publication_ids(self, conn: Connection) -> list[int]:
        """Les `source_publications` `keys_dirty` (**orphelines comprises** : la réconciliation est
        aussi l'assignation). Seeds à réconcilier puis à nettoyer (`clear_keys_dirty`)."""
        ...

    def fetch_reconciliation_universe(self, conn: Connection) -> list[ReconcileRow]:
        """Le voisinage 1-hop : les SP dirty (orphelines comprises) **et** les SP qui partagent une
        clé de confirmation (DOI / NNT / hal_id / PMID, ou le composite thèse `title_normalized`+`pub_year`)
        avec l'une d'elles — matérialisées ou orphelines. Univers sur lequel tourne `connected_components`."""
        ...

    def fetch_publication_ids_by_doi(self, conn: Connection) -> dict[str, int]:
        """Map `lower(doi) → id` des publications existantes portant un DOI.

        Permet à `plan_reconciliation` d'ancrer un groupe sur la publication qui porte
        déjà son DOI même quand **aucune** SP du voisinage n'y est rattachée — publication
        devenue orpheline après un TRUNCATE + réimport des sources, ou dérive du
        `publications.doi` vis-à-vis de ses sources. Sans cela, le groupe créerait une
        publication neuve qui heurterait la contrainte unique sur le DOI."""
        ...

    def repoint_source_publications(
        self, conn: Connection, source_publication_ids: list[int], publication_id: int
    ) -> None:
        """Rattache un ensemble de `source_publications` à `publication_id` (assignation d'un groupe)."""
        ...

    def repoint_dependents(
        self, conn: Connection, from_publication_id: int, to_publication_id: int
    ) -> None:
        """Re-pointe les dépendants curatés/importés d'une publication **dissoute** vers son
        successeur : paires `distinct_publications` (réordonnées + dédupliquées) et
        `apc_payments`. À appeler avant la suppression de la publication dissoute (sinon CASCADE
        / SET NULL les perdrait)."""
        ...

    def clear_keys_dirty(self, conn: Connection, source_publication_ids: list[int]) -> int:
        """Efface `keys_dirty` sur les SP réconciliées. Retourne le nombre de lignes touchées."""
        ...

    def count_dedup_inputs(self, conn: Connection) -> tuple[int, int]:
        """`(source_publications in-périmètre, publications)` pour le facteur de dédup global. Une SP est in-périmètre si elle a au moins une authorship in-périmètre (même définition que l'univers de réconciliation). Les publications hors périmètre n'existent pas — la réconciliation gate leur création sur le périmètre."""
        ...
