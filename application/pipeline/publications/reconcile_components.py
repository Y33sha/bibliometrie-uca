"""Passe de réconciliation des composantes — côté **merge** (3.2a).

Après l'assignation : recalcule les composantes connexes du voisinage 1-hop des `source_publications` marquées `keys_dirty` et fusionne les publications matérialisées en surplus, pour qu'il y ait une publication par composante (dans le respect du cannot-link DOI). La décision est portée par `domain.publications.reconciliation.plan_merges` (pure) ; ici on lit le voisinage, on applique les fusions via `merge_publications`, on rafraîchit les ancres, puis on efface le drapeau.

Voisinage 1-hop, pas de fermeture transitive : l'invariant *dirty* garantit que toute arête neuve a une extrémité dirty (raisonnement détaillé dans `domain/publications/reconciliation.py`).

Merge-only : le **split** (publication dont les SP s'étalent sur plusieurs composantes, après retrait d'une clé) est détecté par `plan_merges` et seulement **journalisé** ici — son traitement (re-pointage des dépendants) est un chantier ultérieur.

L'orchestrateur dépend du port `PublicationsReconciliationQueries`. Le point d'entrée CLI est dans `interfaces/cli/pipeline/reconcile_components.py`.
"""

import logging

from sqlalchemy import Connection

from application.pipeline._savepoint import savepoint
from application.ports.pipeline.publications_reconciliation import (
    PublicationsReconciliationQueries,
)
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.publications import merge_publications, refresh_from_sources
from domain.errors import DistinctDoiError
from domain.publications.reconciliation import ReconcileMember, plan_merges
from domain.source_publications.keys import project_confirmation_keys


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
        members = [
            ReconcileMember(
                source_publication_id=row.id,
                publication_id=row.publication_id,
                effective_doi=(keys := project_confirmation_keys(row.doi, row.external_ids)).doi,
                tokens=keys.tokens(),
            )
            for row in rows
        ]

        plan = plan_merges(members)
        logger.info(
            "  %d composante(s) à fusionner, %d publication(s) au split différé",
            len(plan.merges),
            len(plan.deferred_split_publication_ids),
        )
        if plan.deferred_split_publication_ids:
            logger.info("  split différé (publications) : %s", plan.deferred_split_publication_ids)

        if dry_run:
            conn.rollback()
            return

        merged = 0
        skipped = 0
        for group in plan.merges:
            absorbed_ok = False
            for absorbed_id in group.absorbed_publication_ids:
                try:
                    with savepoint(conn, "reconcile_merge"):
                        merge_publications(
                            group.anchor_publication_id,
                            absorbed_id,
                            repo=pub_repo,
                            audit_repo=audit_repo,
                        )
                    merged += 1
                    absorbed_ok = True
                except DistinctDoiError:
                    # Garde de défense-en-profondeur : `plan_merges` ne fusionne que du
                    # DOI-compatible, ce cas ne devrait pas survenir. On saute sans casser le batch.
                    logger.warning(
                        "  fusion %d ← %d refusée (DOI distincts)",
                        group.anchor_publication_id,
                        absorbed_id,
                    )
                    skipped += 1
            if absorbed_ok:
                refresh_from_sources(
                    group.anchor_publication_id, repo=pub_repo, audit_repo=audit_repo
                )

        cleared = queries.clear_keys_dirty(conn, dirty_ids)
        conn.commit()
        logger.info(
            "✓ %d publication(s) absorbée(s)%s, %d SP nettoyées",
            merged,
            f", {skipped} refusée(s)" if skipped else "",
            cleared,
        )
    except Exception:
        conn.rollback()
        logger.exception("Erreur")
        raise
