"""Passe d'assignation + réconciliation des composantes — match/create/skip **et** merge/split unifiés.

Recalcule les composantes connexes du voisinage 1-hop des `source_publications` marquées `keys_dirty` et assigne chaque SP au pub-ancre de sa partition `(composante ∩ DOI)`. Assignation d'un orphelin (match/create/skip) et réconciliation de publications matérialisées (merge/split) sont des facettes du même primitif. La décision est portée par `domain.publications.reconciliation.plan_reconciliation` (pure) ; ici on applique :

- **groupes** : on rattache les SP de chaque groupe à son ancre (pub existant conservé), ou à un **nouveau** pub créé quand la partition n'a pas d'ancre existante (split) ;
- **publications dissoutes** (vidées de toutes leurs SP par un merge) : leurs dépendants curatés/importés (`distinct_publications`, `apc_payments`) sont re-pointés vers le successeur, puis `refresh_from_sources` les supprime (orphelines) ;
- **rafraîchissement** : `refresh_from_sources` recompute les métadonnées canoniques de chaque pub touché (et supprime les orphelines).

Les `authorships` canoniques sont laissées à la phase `authorships` (`insert_missing` + `prune_orphan`, set-based) — la réconciliation gère l'appartenance des SP et les métadonnées des publications, pas la projection authorships.

Voisinage 1-hop, pas de fermeture transitive : l'invariant *dirty* garantit que toute arête neuve a une extrémité dirty (raisonnement détaillé dans `domain/publications/reconciliation.py`).

L'orchestrateur dépend du port `PublicationsReconciliationQueries`. Le point d'entrée CLI est dans `interfaces/cli/pipeline/reconcile_components.py`.
"""

import logging
from typing import NamedTuple

from sqlalchemy import Connection

from application.pipeline._savepoint import savepoint
from application.ports.pipeline.publications_reconciliation import (
    PublicationsReconciliationQueries,
    ReconcileRow,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.publications import refresh_from_sources
from domain.publications.metadata import OA_STATUS_UNKNOWN_DEFAULT
from domain.publications.reconciliation import ReconcileMember, WorkGroup, plan_reconciliation
from domain.source_publications.keys import project_confirmation_keys


def _member(row: ReconcileRow) -> ReconcileMember:
    keys = project_confirmation_keys(
        row.doi, row.external_ids, row.doc_type, row.title_normalized, row.pub_year
    )
    return ReconcileMember(
        source_publication_id=row.id,
        publication_id=row.publication_id,
        publication_doi=row.publication_doi,
        effective_doi=keys.doi,
        tokens=keys.tokens(),
        in_perimeter=row.in_perimeter,
        title_normalized=row.title_normalized,
        pub_year=row.pub_year,
    )


def _create_new_publication(
    group: WorkGroup, rows_by_sp: dict[int, ReconcileRow], pub_repo: PublicationRepository
) -> int:
    """Crée le pub d'un groupe sans ancre existante (split, ou création depuis orphelins),
    semé depuis sa plus petite SP portant une année (`pub_year`, seule colonne NOT NULL de
    `publications` ici). Les métadonnées définitives sont posées juste après par
    `refresh_from_sources`.

    Un groupe `target=None` est soit une partition d'orphelins ayant passé le gate
    `has_minimal_publication_metadata` (≥1 membre titre + année), soit une partition split
    perdante (membres matérialisés, qui portaient déjà une année) — dans les deux cas ≥1
    membre a une année."""
    seed = min(
        (rows_by_sp[sp] for sp in group.source_publication_ids if rows_by_sp[sp].pub_year),
        key=lambda r: r.id,
    )
    assert seed.pub_year is not None
    return pub_repo.create(
        title=seed.title_normalized or "",
        title_normalized=seed.title_normalized or "",
        doc_type=seed.doc_type or "other",
        pub_year=seed.pub_year,
        doi=seed.doi,
        oa_status=OA_STATUS_UNKNOWN_DEFAULT,
        journal_id=None,
        container_title=None,
        language=None,
    )


class ReconcileStats(NamedTuple):
    """Bilan d'une passe de réconciliation (pour le logging du `run`)."""

    dirty: int
    groups: int
    new_pubs: int
    dissolved: int
    survivors: int
    cleared: int


def reconcile(
    conn: Connection,
    queries: PublicationsReconciliationQueries,
    *,
    pub_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> ReconcileStats | None:
    """Planifie et applique la réconciliation du voisinage dirty, **sans `commit`** (à la charge
    du caller). Retourne `None` si aucune SP n'est dirty, sinon le bilan.

    Primitif partagé par le `run` du pipeline (qui commit) et le helper de tests d'intégration
    (qui rollback en fin de fixture) — d'où l'absence de `commit` ici.
    """
    dirty_ids = queries.fetch_dirty_source_publication_ids(conn)
    if not dirty_ids:
        return None

    rows = queries.fetch_reconciliation_universe(conn)
    rows_by_sp = {row.id: row for row in rows}
    plan = plan_reconciliation(_member(row) for row in rows)

    survivors: set[int] = set()

    # 1. Groupes : rattacher chaque SP à son ancre (ou à un nouveau pub — orphelins in-périmètre
    #    ou partition perdante d'un split).
    for group in plan.groups:
        target = group.target_publication_id
        if target is None:
            target = _create_new_publication(group, rows_by_sp, pub_repo)
        queries.repoint_source_publications(conn, list(group.source_publication_ids), target)
        survivors.add(target)

    # 2. Dissolutions d'abord : sauver les dépendants curatés vers le successeur, puis
    #    `refresh_from_sources` supprime la pub vidée (cas orphelin). Avant les survivants,
    #    pour libérer le DOI dupliqué (sinon l'auto-merge-sur-collision-DOI du refresh
    #    survivant retomberait dessus).
    for dissolved in plan.dissolved:
        queries.repoint_dependents(
            conn, dissolved.publication_id, dissolved.successor_publication_id
        )
        with savepoint(conn, "reconcile_dissolve"):
            refresh_from_sources(dissolved.publication_id, repo=pub_repo, audit_repo=audit_repo)

    # 3. Rafraîchir les survivants : métadonnées canoniques recomputées.
    for pub_id in sorted(survivors):
        with savepoint(conn, "reconcile_refresh"):
            refresh_from_sources(pub_id, repo=pub_repo, audit_repo=audit_repo)

    cleared = queries.clear_keys_dirty(conn, dirty_ids)
    new_pubs = sum(1 for g in plan.groups if g.target_publication_id is None)
    return ReconcileStats(
        dirty=len(dirty_ids),
        groups=len(plan.groups),
        new_pubs=new_pubs,
        dissolved=len(plan.dissolved),
        survivors=len(survivors),
        cleared=cleared,
    )


def run(
    conn: Connection,
    queries: PublicationsReconciliationQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
    dry_run: bool = False,
) -> None:
    try:
        if dry_run:
            dirty_ids = queries.fetch_dirty_source_publication_ids(conn)
            logger.info("Réconciliation (dry-run) : %d source_publications dirty", len(dirty_ids))
            if dirty_ids:
                plan = plan_reconciliation(
                    _member(row) for row in queries.fetch_reconciliation_universe(conn)
                )
                new_pubs = sum(1 for g in plan.groups if g.target_publication_id is None)
                logger.info(
                    "  %d groupe(s), %d nouveau(x) pub(s), %d publication(s) dissoute(s)",
                    len(plan.groups),
                    new_pubs,
                    len(plan.dissolved),
                )
            conn.rollback()
            return

        stats = reconcile(conn, queries, pub_repo=pub_repo, audit_repo=audit_repo)
        if stats is None:
            logger.info("Réconciliation : aucune source_publication dirty")
            return
        conn.commit()
        logger.info(
            "✓ %d dirty, %d survivant(s), %d nouveau(x), %d dissous, %d SP nettoyées",
            stats.dirty,
            stats.survivors,
            stats.new_pubs,
            stats.dissolved,
            stats.cleared,
        )
    except Exception:
        conn.rollback()
        logger.exception("Erreur")
        raise
