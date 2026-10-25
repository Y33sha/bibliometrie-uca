"""Helper de tests : exécute la vraie phase « publications » du pipeline.

Partagé par les tests d'idempotence et de re-traitement, qui ont besoin de
créer/rattacher les publications de leurs source_records orphelins sans
réimplémenter l'assignation.
"""

import logging

from sqlalchemy import Connection, text

from pipeline.transformation.publications.correction.correct_by_cluster import (
    compute_updates as compute_cluster_updates,
)
from pipeline.transformation.publications.correction.correct_unary import (
    compute_update as compute_unary_update,
)
from pipeline.transformation.publications.correction.correction_store import (
    SourceRecordCorrectionStore,
)
from pipeline.transformation.publications.reconciliation import reconcile


def apply_metadata_corrections(conn: Connection) -> None:
    """Joue `metadata_correction` (unaire puis cluster) sur toutes les enregistrements sources, en place.

    Compose fetch→compute→persist sans le `run()` applicatif : ce dernier batche et
    `conn.commit()` entre lots, ce qui casserait l'isolation transactionnelle du
    fixture `sa_sync_conn` (un `begin()` rollbacké en fin de test).

    À rejouer après chaque (re-)normalize qui réécrit les colonnes enregistrement source avec le brut
    source, avant tout `refresh_from_sources` / matching : c'est l'ordre du pipeline
    (phase `metadata_correction` avant phase `publications`).
    """
    queries = SourceRecordCorrectionStore(conn)

    unary_rows = queries.fetch_for_unary_correction()
    unary_updates = [u for row in unary_rows if (u := compute_unary_update(row)) is not None]
    queries.persist_corrections(unary_updates)

    cluster_updates = compute_cluster_updates(queries.fetch_doi_cluster_candidates())
    queries.persist_doi_corrections(cluster_updates)


def create_all_publications(conn: Connection) -> None:
    """Crée/rattache les publications des source_records orphelins via la
    vraie passe d'assignation+réconciliation du pipeline (`reconcile`), pas une
    cascade réimplémentée.

    Joue d'abord `metadata_correction` (unaire puis cluster), comme l'ordre réel
    du pipeline : l'assignation lit le `doc_type`/`serial_id`/`oa_status` canonique
    corrigé écrit en place sur la `source_record`, elle ne re-mappe ni ne
    re-corrige. Sans cette passe, un enregistrement source porterait sa nomenclature source brute
    (`ART`, `journal-article`…) jusqu'à l'enum canonique → écriture invalide.

    Ces tests ne jouent pas la phase affiliations : aucun `source_contribution`
    n'est in_perimeter, or l'assignation ne *crée* une publication que pour un
    orphelin in_perimeter. On sème donc le périmètre à la main (indice `address`)
    — équivalent de ce que pose la phase affiliations en prod.

    `reconcile` ne commit pas (à la charge du caller), ce qui préserve l'isolation
    transactionnelle du fixture `sa_sync_conn`.
    """
    conn.execute(text("UPDATE source_contributions SET perimeter_evidence = '{address}'"))

    apply_metadata_corrections(conn)

    reconcile(conn, logging.getLogger("create_all_publications"))


__all__ = ["apply_metadata_corrections", "create_all_publications"]
