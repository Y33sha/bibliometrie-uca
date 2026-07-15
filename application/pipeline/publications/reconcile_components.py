"""Passe d'assignation + réconciliation des composantes — match/create/skip **et** merge/split unifiés.

Recalcule les composantes connexes du voisinage 1-hop des `source_publications` marquées `keys_dirty` et assigne chaque SP au pub-ancre de sa partition `(composante ∩ DOI)`. Assignation d'un orphelin (match/create/skip) et réconciliation de publications matérialisées (merge/split) sont des facettes du même primitif. La décision est portée par `domain.publications.reconciliation.plan_reconciliation` (pure) ; ici on applique :

- **groupes** : on rattache les SP de chaque groupe à son ancre (pub existant conservé), ou à un **nouveau** pub créé quand la partition n'a pas d'ancre existante (split) ;
- **publications dissoutes** (vidées de toutes leurs SP par un merge) : leurs dépendants curatés/importés (`distinct_publications`, `apc_payments`) sont re-pointés vers le successeur, puis `refresh_from_sources` les supprime (orphelines) ;
- **rafraîchissement** : `refresh_from_sources` recompute les métadonnées canoniques de chaque pub touché (et supprime les orphelines).

Les `authorships` canoniques sont laissées à la phase `authorships` (`insert_missing` + `prune_orphan`, set-based) — la réconciliation gère l'appartenance des SP et les métadonnées des publications, pas la projection authorships.

Voisinage 1-hop, pas de fermeture transitive : l'invariant *dirty* garantit que toute arête neuve a une extrémité dirty (raisonnement détaillé dans `domain/publications/reconciliation.py`).

L'orchestrateur dépend du port `PublicationsReconciliationQueries` ; il est appelé par `run_pipeline`.
"""

import logging
from typing import NamedTuple

from sqlalchemy import Connection

from application.pipeline._savepoint import savepoint
from application.ports.pipeline.publications_reconciliation import (
    PublicationsReconciliationQueries,
    ReconcileRow,
)
from application.ports.repositories.publication_repository import PublicationRepository
from application.services.publications.core import create_publication, refresh_from_sources
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
    """Crée la publication d'un groupe sans ancre existante (split, ou création depuis orphelins), semée depuis sa plus petite SP portant une année. Les métadonnées définitives sont posées juste après par `refresh_from_sources`.

    Un groupe `target=None` est soit une partition d'orphelins ayant passé le gate `has_minimal_publication_metadata` (≥1 membre titre + année), soit une partition split perdante (membres matérialisés, qui portaient déjà une année) — dans les deux cas ≥1 membre a une année."""
    seed = min(
        (rows_by_sp[sp] for sp in group.source_publication_ids if rows_by_sp[sp].pub_year),
        key=lambda r: r.id,
    )
    assert seed.pub_year is not None
    return create_publication(
        title_normalized=seed.title_normalized or "",
        doc_type=seed.doc_type,
        pub_year=seed.pub_year,
        doi=seed.doi,
        repo=pub_repo,
    )


class ReconcileStats(NamedTuple):
    """Bilan d'une passe de réconciliation, en vocabulaire lisible (pour le log de `run`).

    `processed` = SP dirty traitées ; `publications` = publications résultantes (auxquelles des SP sont rattachées) ; `created` = parmi elles, nouvellement créées (orphelins matérialisés **et** spin-offs de scission) ; `existing` = déjà existantes conservées ; `merges` = publications redondantes absorbées dans une autre et supprimées ; `splits` = nouvelles publications issues d'une scission (un DOI distinct détaché d'une publication existante).
    """

    processed: int
    publications: int
    created: int
    existing: int
    merges: int
    splits: int
    cleared: int


def reconcile(
    conn: Connection,
    queries: PublicationsReconciliationQueries,
    *,
    pub_repo: PublicationRepository,
    logger: logging.Logger | None = None,
) -> ReconcileStats | None:
    """Planifie et applique la réconciliation du voisinage dirty, **sans `commit`** (à la charge du caller). Retourne `None` si aucune SP n'est dirty, sinon le bilan.

    Primitif partagé par le `run` du pipeline (qui commit) et le helper de tests d'intégration (qui rollback en fin de fixture) — d'où l'absence de `commit` ici. `logger` (optionnel) émet la progression : sur un full rerun, le rafraîchissement des survivants domine le temps, d'où le compteur `i/total`.
    """
    dirty_ids = queries.fetch_dirty_source_publication_ids(conn)
    if not dirty_ids:
        return None

    if logger:
        logger.info(
            "Réconciliation : %d source_publications dirty, chargement de l'univers…",
            len(dirty_ids),
        )
    rows = queries.fetch_reconciliation_universe(conn)
    rows_by_sp = {row.id: row for row in rows}
    existing_pub_by_doi = queries.fetch_publication_ids_by_doi(conn)
    plan = plan_reconciliation(
        (_member(row) for row in rows), existing_pub_by_doi=existing_pub_by_doi
    )
    if logger:
        logger.info(
            "  univers de %d SP → %d publications cibles, %d doublons à fusionner ; application…",
            len(rows),
            len(plan.groups),
            len(plan.dissolved),
        )

    survivors: set[int] = set()
    created = 0
    splits = 0

    # 1. Groupes : rattacher chaque SP à son ancre (ou à un nouveau pub — orphelins in-périmètre, ou partition perdante d'un split = scission d'une publication existante).
    for group in plan.groups:
        target = group.target_publication_id
        if target is None:
            from_existing = any(
                rows_by_sp[sp].publication_id is not None for sp in group.source_publication_ids
            )
            target = _create_new_publication(group, rows_by_sp, pub_repo)
            created += 1
            if from_existing:
                splits += 1
        queries.repoint_source_publications(conn, list(group.source_publication_ids), target)
        survivors.add(target)

    # 2. Dissolutions d'abord : sauver les dépendants curatés vers le successeur, puis `refresh_from_sources` supprime la pub vidée (cas orphelin). Avant les survivants, pour libérer le DOI qu'un survivant reprend : sinon son `save` heurterait la contrainte unique tant que la pub dissoute porte encore ce DOI.
    for dissolved in plan.dissolved:
        queries.repoint_dependents(
            conn, dissolved.publication_id, dissolved.successor_publication_id
        )
        with savepoint(conn):
            refresh_from_sources(dissolved.publication_id, repo=pub_repo)

    # 3. Rafraîchir les survivants : métadonnées canoniques recomputées. Phase la plus longue sur un gros run → progression tous les 5000.
    survivor_ids = sorted(survivors)
    total = len(survivor_ids)
    for i, pub_id in enumerate(survivor_ids, 1):
        with savepoint(conn):
            refresh_from_sources(pub_id, repo=pub_repo)
        if logger and (i % 5000 == 0 or i == total):
            logger.info("  rafraîchissement des métadonnées : %d/%d publications", i, total)

    cleared = queries.clear_keys_dirty(conn, dirty_ids)
    return ReconcileStats(
        processed=len(dirty_ids),
        publications=len(survivors),
        created=created,
        existing=len(survivors) - created,
        merges=len(plan.dissolved),
        splits=splits,
        cleared=cleared,
    )


def run(
    conn: Connection,
    queries: PublicationsReconciliationQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
) -> ReconcileStats | None:
    try:
        stats = reconcile(conn, queries, pub_repo=pub_repo, logger=logger)
        if stats is None:
            logger.info("Réconciliation : aucune source_publication dirty")
            return None
        conn.commit()
        logger.info("✓ %d source_publications traitées", stats.processed)
        logger.info(
            "  → rattachées à %d publications (%d nouvelles dont %d par scission, %d déjà existantes)",
            stats.publications,
            stats.created,
            stats.splits,
            stats.existing,
        )
        logger.info("  → %d doublons fusionnés", stats.merges)
        return stats
    except Exception:
        conn.rollback()
        logger.exception("Erreur")
        raise
