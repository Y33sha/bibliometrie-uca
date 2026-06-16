"""Passe de réconciliation des composantes — merge **et** split unifiés.

Après l'assignation : recalcule les composantes connexes du voisinage 1-hop des `source_publications` marquées `keys_dirty`, et assigne chaque SP au pub-ancre de sa partition `(composante ∩ DOI)`. La décision est portée par `domain.publications.reconciliation.plan_reconciliation` (pure) ; ici on applique :

- **groupes** : on rattache les SP de chaque groupe à son ancre (pub existant conservé), ou à un **nouveau** pub créé quand la partition n'a pas d'ancre existante (split) ;
- **publications dissoutes** (vidées de toutes leurs SP par un merge) : leurs dépendants curatés/importés (`distinct_publications`, `apc_payments`) sont re-pointés vers le successeur, puis `refresh_from_sources` les supprime (orphelines) ;
- **rafraîchissement** : `refresh_from_sources` recompute les métadonnées canoniques de chaque pub touché (et supprime les orphelines).

Les `authorships` canoniques sont laissées à la phase `authorships` (`insert_missing` + `prune_orphan`, set-based), comme pour les pubs neuves de `match_or_create` — la réconciliation gère l'appartenance et les métadonnées, pas la projection authorships.

Voisinage 1-hop, pas de fermeture transitive : l'invariant *dirty* garantit que toute arête neuve a une extrémité dirty (raisonnement détaillé dans `domain/publications/reconciliation.py`).

L'orchestrateur dépend du port `PublicationsReconciliationQueries`. Le point d'entrée CLI est dans `interfaces/cli/pipeline/reconcile_components.py`.
"""

import logging

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
    )


def _create_new_publication(
    group: WorkGroup, rows_by_sp: dict[int, ReconcileRow], pub_repo: PublicationRepository
) -> int:
    """Crée le pub d'un groupe split sans ancre existante, semé depuis sa SP de plus petit id.
    Les métadonnées définitives sont posées juste après par `refresh_from_sources`."""
    seed = rows_by_sp[min(group.source_publication_ids)]
    # Toute SP de l'univers est matérialisée (rattachée à une publication) : elle a donc
    # passé le gate `has_minimal_publication_metadata` de l'assignation → `pub_year` présent.
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
        dirty_ids = queries.fetch_dirty_source_publication_ids(conn)
        logger.info(
            "Réconciliation : %d source_publications dirty (avec publication)", len(dirty_ids)
        )
        if not dirty_ids:
            return

        rows = queries.fetch_reconciliation_universe(conn)
        rows_by_sp = {row.id: row for row in rows}
        plan = plan_reconciliation(_member(row) for row in rows)

        new_pubs = sum(1 for g in plan.groups if g.target_publication_id is None)
        logger.info(
            "  %d groupe(s), %d nouveau(x) pub(s) (split), %d publication(s) dissoute(s)",
            len(plan.groups),
            new_pubs,
            len(plan.dissolved),
        )

        if dry_run:
            conn.rollback()
            return

        survivors: set[int] = set()

        # 1. Groupes : rattacher chaque SP à son ancre (ou à un nouveau pub pour un split).
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
        conn.commit()
        logger.info(
            "✓ %d survivant(s), %d nouveau(x), %d dissous, %d SP nettoyées",
            len(survivors),
            new_pubs,
            len(plan.dissolved),
            cleared,
        )
    except Exception:
        conn.rollback()
        logger.exception("Erreur")
        raise
