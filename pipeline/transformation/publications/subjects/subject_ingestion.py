"""Sujets des publications, première tâche de la phase `subjects`.

Une publication est ingérée quand `publications.subjects_ingested_at` est vide. Le recalcul d'une publication depuis ses enregistrements sources vide cette date. Ses liens non rejetés sont supprimés, puis dérivés des sujets de ses enregistrements sources (`source_record_subjects`), ancêtres compris. `publication_subjects.source` garde ainsi la source de chaque sujet. Les sujets sans lien sont ensuite supprimés.

Les mots-clés libres (`keywords`) restent hors de `subjects`.
"""

import logging

from sqlalchemy import Connection

from pipeline.runtime.observability.log_format import (
    BRANCH,
    LAST_BRANCH,
    inflect,
    nothing_to_do,
    quantity,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress
from pipeline.transformation.publications.subjects.subject_store import SubjectStore

_BATCH = 2000
"""Publications dérivées par instruction."""


def run(conn: Connection, logger: logging.Logger, *, rebuild: bool = False) -> PhaseMetrics:
    """Ré-ingère les sujets des publications à ingérer.

    `metrics.new` compte les liens publication-sujet créés. Le résumé donne l'évolution nette du nombre de sujets, leur total et le nombre de publications ingérées.

    Args:
        rebuild: marque d'abord toutes les publications, pour appliquer une évolution des règles d'ingestion à tout le stock.
    """
    store = SubjectStore(conn)
    subjects_before = store.count_all_subjects()
    if rebuild:
        store.mark_all_publications_to_reingest()
    publication_ids = store.select_publications_to_reingest()

    metrics = PhaseMetrics()
    if publication_ids:
        n_source_records = store.count_source_records(publication_ids=publication_ids)
        logger.info(
            "%s%s à traiter (%s), soit %s",
            BRANCH,
            quantity(len(publication_ids), "publication"),
            "reconstruction complète"
            if rebuild
            else f"{inflect(len(publication_ids), 'nouvelle')} ou {inflect(len(publication_ids), 'modifiée')}",
            quantity(n_source_records, "document source", "documents sources"),
        )
        n_links = 0
        with track_progress(len(publication_ids), LAST_BRANCH.rstrip(), logger) as progress:
            for start in range(0, len(publication_ids), _BATCH):
                batch = publication_ids[start : start + _BATCH]
                store.clear_publication_subjects_for_publications(publication_ids=batch)
                n_links += store.derive_publication_subjects(publication_ids=batch)
                store.mark_subjects_ingested(publication_ids=batch)
                progress.advance(len(batch))
        metrics.add(new=n_links, seen=n_source_records)
    else:
        nothing_to_do(logger)

    store.purge_orphan_subjects()
    subjects_after = store.count_all_subjects()
    metrics.details["summary"] = {
        "subjects_added": subjects_after - subjects_before,
        "subjects_total": subjects_after,
        "publications_updated": len(publication_ids),
    }
    return metrics
