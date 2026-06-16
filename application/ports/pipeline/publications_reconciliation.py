"""Port : SQL de la passe de réconciliation des composantes (`reconcile_components`).

Implémenté par `infrastructure.queries.pipeline.publications_reconciliation.PgPublicationsReconciliationQueries`.

La passe lit le **voisinage 1-hop** des `source_publications` marquées `keys_dirty` (les SP dirty + celles qui partagent une clé de confirmation avec elles), décide les assignations SP → pub-ancre (`domain.publications.reconciliation.plan_reconciliation` — merge et split unifiés), les applique, puis efface le drapeau. Cf. le raisonnement 1-hop documenté côté domaine.
"""

from typing import NamedTuple, Protocol

from sqlalchemy import Connection


class ReconcileRow(NamedTuple):
    """Projection d'une `source_publication` du voisinage : clés + publication courante.

    `doc_type`/`title_normalized`/`pub_year` alimentent le token métadonnée thèse de
    `project_confirmation_keys` (les identifiants viennent de `doi`/`external_ids`).
    `publication_doi` = DOI canonique de la publication courante, qui sert à choisir
    l'ancre de réconciliation (le pub portant le DOI de la partition)."""

    id: int
    doi: str | None
    external_ids: dict[str, object] | None
    publication_id: int
    doc_type: str | None
    title_normalized: str | None
    pub_year: int | None
    publication_doi: str | None


class PublicationsReconciliationQueries(Protocol):
    """Opérations SQL de la réconciliation des composantes."""

    def fetch_dirty_source_publication_ids(self, conn: Connection) -> list[int]:
        """Les `source_publications` `keys_dirty` rattachées à une publication (seeds à réconcilier
        puis à nettoyer). Les orphelines dirty (sans publication) sont ignorées : rien à réconcilier
        tant qu'elles ne sont pas matérialisées ; elles restent dirty jusqu'à leur rattachement."""
        ...

    def fetch_reconciliation_universe(self, conn: Connection) -> list[ReconcileRow]:
        """Le voisinage 1-hop : les SP dirty (avec publication) **et** les SP qui partagent une clé
        de confirmation (DOI / NNT / hal_id / PMID, ou le composite thèse `title_normalized`+`pub_year`)
        avec l'une d'elles. Univers sur lequel tourne `connected_components`."""
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
