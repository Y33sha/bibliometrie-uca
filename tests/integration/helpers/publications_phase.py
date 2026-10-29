"""Phases `metadata_correction` et `publications` du pipeline, jouées dans la transaction d'un test d'idempotence ou de retraitement."""

import logging

from sqlalchemy import Connection, text

from pipeline.transformation.publications.correction.correct_unary import (
    compute_update as compute_unary_update,
)
from pipeline.transformation.publications.correction.correction_store import (
    SourceRecordCorrectionStore,
)
from pipeline.transformation.publications.correction.doi_targets import compute_doi_targets
from pipeline.transformation.publications.correction.matchable import (
    compute_updates as compute_matchable_updates,
)
from pipeline.transformation.publications.correction.remove_identifiers import (
    compute_updates as compute_removal_updates,
)
from pipeline.transformation.publications.reconciliation import reconcile


def apply_metadata_corrections(conn: Connection) -> None:
    """Joue les sous-étapes de `metadata_correction` (correction unaire, cibles des DOI, retraits de DOI, puis `is_matchable`) sur tous les enregistrements sources, sans valider la transaction.

    Le `run()` de chaque sous-étape valide la transaction après chaque lot ; ce helper enchaîne donc lecture, calcul et écriture lui-même. À rejouer après chaque normalisation, avant la réconciliation, comme dans le pipeline.
    """
    queries = SourceRecordCorrectionStore(conn)
    missing_hal_ids = queries.fetch_missing_hal_ids()

    unary_rows = queries.fetch_for_unary_correction()
    unary_updates = [
        u
        for row in unary_rows
        if (u := compute_unary_update(row, missing_hal_ids=missing_hal_ids)) is not None
    ]
    queries.persist_corrections(unary_updates)
    queries.delete_missing_hal_locations()

    queries.replace_doi_targets(compute_doi_targets(queries.fetch_secondary_form_declarations()))
    queries.persist_doi_corrections(compute_removal_updates(queries.fetch_doi_cluster_candidates()))

    matchable_updates = compute_matchable_updates(
        queries.fetch_matchability_rows(), missing_hal_ids
    )
    queries.persist_matchability(matchable_updates)


def create_all_publications(conn: Connection) -> None:
    """Crée ou rattache les publications des enregistrements sources orphelins par la réconciliation du pipeline (`reconcile`), sans valider la transaction.

    Pose d'abord l'indice `address` sur toutes les contributions sources, comme la phase `affiliations` : la réconciliation crée une publication seulement pour un enregistrement source du périmètre. Joue ensuite `metadata_correction` : la réconciliation lit le type de document et la revue corrigés.
    """
    conn.execute(text("UPDATE source_contributions SET perimeter_evidence = '{address}'"))

    apply_metadata_corrections(conn)

    reconcile(conn, logging.getLogger("create_all_publications"))


__all__ = ["apply_metadata_corrections", "create_all_publications"]
