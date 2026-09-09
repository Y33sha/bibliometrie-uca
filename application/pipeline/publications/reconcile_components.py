"""Passe d'assignation + réconciliation des composantes — match/create/skip **et** merge/split unifiés.

Recalcule les composantes connexes du voisinage 1-hop des `source_publications` marquées `keys_dirty` et assigne chaque SP au pub-ancre de sa partition `(composante ∩ DOI)`. Assignation d'un orphelin (match/create/skip) et réconciliation de publications matérialisées (merge/split) sont des facettes du même primitif. La décision est portée par `domain.publications.reconciliation.plan_reconciliation` (pure) ; ici on applique :

- **groupes** : on rattache les SP de chaque groupe à son ancre (pub existant conservé), ou à un **nouveau** pub créé quand la partition n'a pas d'ancre existante (split) ;
- **publications dissoutes** (vidées de toutes leurs SP par un merge) : leurs dépendants curatés/importés (`distinct_publications`, `apc_payments`) sont re-pointés vers le successeur, puis `refresh_from_sources` les supprime (orphelines) ;
- **rafraîchissement** : `refresh_from_sources` recompute les métadonnées canoniques de chaque pub touché (et supprime les orphelines).

Les `authorships` canoniques sont laissées à la phase `authorships` (`insert_missing` + `prune_orphan`, set-based) — la réconciliation gère l'appartenance des SP et les métadonnées des publications, pas la projection authorships.

Voisinage 1-hop, pas de fermeture transitive : l'invariant *dirty* garantit que toute arête neuve a une extrémité dirty (raisonnement détaillé dans `domain/publications/reconciliation.py`). La passe s'ouvre sur la propagation de `keys_dirty` aux source_publications co-rattachées à une publication avec une SP dirty, qui clôt le voisinage sur les arêtes **retirées** autant que sur les neuves.

L'orchestrateur dépend du port `PublicationsReconciliationQueries` ; il est appelé par `run_pipeline`.
"""

import logging
import time
from typing import NamedTuple

from sqlalchemy import Connection

from application.pipeline._savepoint import savepoint
from application.pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, ETAPE, accord, forme
from application.pipeline.progression import attente, progression
from application.ports.pipeline.publications.reconciliation import (
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
    group: WorkGroup, rows_by_sp: dict[int, ReconcileRow], publication_repo: PublicationRepository
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
        repo=publication_repo,
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
    publication_repo: PublicationRepository,
    logger: logging.Logger | None = None,
) -> ReconcileStats | None:
    """Planifie et applique la réconciliation du voisinage dirty, **sans `commit`** (à la charge du caller). Retourne `None` si aucune SP n'est dirty, sinon le bilan.

    Primitif partagé par le `run` du pipeline (qui commit) et le helper de tests d'intégration (qui rollback en fin de fixture) — d'où l'absence de `commit` ici.
    """
    queries.mark_publication_siblings_dirty(conn)
    dirty_ids = queries.fetch_dirty_source_publication_ids(conn)
    if not dirty_ids:
        return None
    if logger:
        logger.info(
            "%s%s %s (nouveaux ou mis à jour)",
            ETAPE,
            accord(len(dirty_ids), "document"),
            forme(len(dirty_ids), "examiné"),
        )
    rows = queries.fetch_reconciliation_universe(conn)
    rows_by_sp = {row.id: row for row in rows}
    existing_pub_by_doi = queries.fetch_publication_ids_by_doi(conn)
    plan = plan_reconciliation(
        (_member(row) for row in rows), existing_pub_by_doi=existing_pub_by_doi
    )
    if logger:
        # Le plan sépare déjà les publications à créer de celles qu'un groupe rejoint.
        a_creer = sum(1 for g in plan.groups if g.target_publication_id is None)
        logger.info(
            "%srésolus en %s (%d déjà existantes, %d nouvelles ; %s à fusionner)",
            BRANCHE,
            accord(len(plan.groups), "publication"),
            len(plan.groups) - a_creer,
            a_creer,
            accord(len(plan.dissolved), "doublon"),
        )

    survivors: set[int] = set()
    created = 0
    splits = 0

    t0 = time.perf_counter()
    with attente(f"{DERNIERE_BRANCHE}application", logger) as ligne:
        # 1. Groupes : rattacher chaque SP à son ancre (ou à un nouveau pub — orphelins in-périmètre, ou partition perdante d'un split = scission d'une publication existante).
        for group in plan.groups:
            target = group.target_publication_id
            if target is None:
                from_existing = any(
                    rows_by_sp[sp].publication_id is not None for sp in group.source_publication_ids
                )
                target = _create_new_publication(group, rows_by_sp, publication_repo)
                created += 1
                if from_existing:
                    splits += 1
            queries.repoint_source_publications(conn, list(group.source_publication_ids), target)
            survivors.add(target)

        # 2. Dissolutions : les dépendants corrigés à la main passent au successeur, puis
        # `refresh_from_sources` supprime la publication vidée. Avant les survivants, pour libérer
        # le DOI qu'un survivant reprend — la contrainte unique le refuserait autrement.
        for dissolved in plan.dissolved:
            queries.repoint_dependents(
                conn, dissolved.publication_id, dissolved.successor_publication_id
            )
            with savepoint(conn):
                refresh_from_sources(dissolved.publication_id, repo=publication_repo)

        ligne.conclut(f"{DERNIERE_BRANCHE}Terminé en {time.perf_counter() - t0:.1f}s")

    # 3. Rafraîchir les survivants : métadonnées recomputées depuis leurs sources.
    survivor_ids = sorted(survivors)
    if logger:
        logger.info("")
        logger.info("%sRecalcul des métadonnées consolidées", ETAPE)
    with progression(len(survivor_ids), DERNIERE_BRANCHE.rstrip(), logger) as avancement:
        for pub_id in survivor_ids:
            avancement.avance()
            with savepoint(conn):
                refresh_from_sources(pub_id, repo=publication_repo)

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
    publication_repo: PublicationRepository,
) -> ReconcileStats | None:
    try:
        stats = reconcile(conn, queries, publication_repo=publication_repo, logger=logger)
        if stats is None:
            return None
        conn.commit()
        return stats
    except Exception:
        conn.rollback()
        logger.exception("Erreur")
        raise
