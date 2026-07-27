"""Helper de tests : exécute la vraie phase « publications » du pipeline.

Partagé par les tests d'idempotence et de re-traitement, qui ont besoin de
créer/rattacher les publications de leurs source_publications orphelins sans
réimplémenter l'assignation.
"""

from sqlalchemy import Connection, text

from application.pipeline.metadata_correction.correct_by_cluster import (
    compute_updates as compute_cluster_updates,
)
from application.pipeline.metadata_correction.correct_unary import (
    compute_update as compute_unary_update,
)
from application.pipeline.publications.reconcile_components import reconcile
from infrastructure.pipeline.metadata_correction import PgMetadataCorrectionQueries
from infrastructure.pipeline.publications.reconciliation import (
    PgPublicationsReconciliationQueries,
)
from infrastructure.repositories import publication_repository


def apply_metadata_corrections(conn: Connection) -> None:
    """Joue `metadata_correction` (unaire puis cluster) sur toutes les SP, en place.

    Compose fetch→compute→persist sans le `run()` applicatif : ce dernier batche et
    `conn.commit()` entre lots, ce qui casserait l'isolation transactionnelle du
    fixture `sa_sync_conn` (un `begin()` rollbacké en fin de test).

    À rejouer après chaque (re-)normalize qui réécrit les colonnes SP avec le brut
    source, avant tout `refresh_from_sources` / matching : c'est l'ordre du pipeline
    (phase `metadata_correction` avant phase `publications`).
    """
    queries = PgMetadataCorrectionQueries()

    unary_rows = queries.fetch_for_unary_correction(conn)
    unary_updates = [u for row in unary_rows if (u := compute_unary_update(row)) is not None]
    queries.persist_corrections(conn, unary_updates)

    cluster_updates = compute_cluster_updates(queries.fetch_doi_cluster_candidates(conn))
    queries.persist_doi_corrections(conn, cluster_updates)


def create_all_publications(conn: Connection) -> None:
    """Crée/rattache les publications des source_publications orphelins via la
    vraie passe d'assignation+réconciliation du pipeline (`reconcile`), pas une
    cascade réimplémentée.

    Joue d'abord `metadata_correction` (unaire puis cluster), comme l'ordre réel
    du pipeline : l'assignation lit le `doc_type`/`journal_id`/`oa_status` canonique
    corrigé écrit en place sur la `source_publication`, elle ne re-mappe ni ne
    re-corrige. Sans cette passe, une SP porterait sa nomenclature source brute
    (`ART`, `journal-article`…) jusqu'à l'enum canonique → écriture invalide.

    Ces tests ne jouent pas la phase affiliations : aucun `source_authorship`
    n'est in_perimeter, or l'assignation ne *crée* une publication que pour un
    orphelin in_perimeter. On sème donc le périmètre à la main (`in_perimeter = TRUE`)
    — équivalent de ce que pose la phase affiliations en prod.

    `reconcile` ne commit pas (à la charge du caller), ce qui préserve l'isolation
    transactionnelle du fixture `sa_sync_conn`.
    """
    conn.execute(text("UPDATE source_authorships SET in_perimeter = TRUE"))

    apply_metadata_corrections(conn)

    reconcile(
        conn, PgPublicationsReconciliationQueries(), publication_repo=publication_repository(conn)
    )


__all__ = ["apply_metadata_corrections", "create_all_publications"]
