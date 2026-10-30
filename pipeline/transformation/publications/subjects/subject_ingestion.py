"""Sujets des publications, première tâche de la phase `subjects`.

Une publication est ingérée quand `publications.subjects_ingested_at` est vide. Le recalcul d'une publication depuis ses enregistrements sources vide cette date. Ses liens non rejetés sont supprimés, puis reconstruits depuis le champ `topics` de chacun de ses enregistrements sources, lu selon sa source (`SUBJECT_EXTRACTORS`). `publication_subjects.source` garde ainsi la source de chaque sujet. Les sujets sans lien sont ensuite supprimés.

Les mots-clés libres (`keywords`) restent hors de `subjects`.
"""

import logging

from pipeline.runtime.observability.log_format import (
    BRANCH,
    LAST_BRANCH,
    inflect,
    nothing_to_do,
    quantity,
    step,
)
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress
from pipeline.transformation.publications.subjects.subject_cache import SubjectCache
from pipeline.transformation.publications.subjects.subject_extractors import SUBJECT_EXTRACTORS
from pipeline.transformation.publications.subjects.subject_store import (
    PublicationSubjectLink,
    SubjectStore,
)


def run(
    store: SubjectStore,
    logger: logging.Logger,
    *,
    rebuild: bool = False,
) -> PhaseMetrics:
    """Ré-ingère les sujets des publications à ingérer.

    `metrics.new` compte les liens publication-sujet créés. Le résumé donne l'évolution nette du nombre de sujets, leur total et le nombre de publications ingérées.

    Args:
        rebuild: marque d'abord toutes les publications, pour appliquer une évolution des règles d'ingestion à tout le stock.
    """
    subjects_before = store.count_all_subjects()
    step(logger, "Liens publications-sujets")

    if rebuild:
        store.mark_all_publications_to_reingest()
    publication_ids = store.select_publications_to_reingest()
    if not publication_ids:
        store.purge_orphan_subjects()
        nothing_to_do(logger)
        subjects_after = store.count_all_subjects()
        metrics = PhaseMetrics()
        metrics.details["summary"] = {
            "subjects_added": subjects_after - subjects_before,
            "subjects_total": subjects_after,
            "publications_updated": 0,
        }
        return metrics

    store.clear_publication_subjects_for_publications(publication_ids=publication_ids)
    rows = store.select_source_records_for_publications(publication_ids=publication_ids)
    logger.info(
        "%s%s à traiter (%s), soit %s",
        BRANCH,
        quantity(len(publication_ids), "publication"),
        "reconstruction complète"
        if rebuild
        else f"{inflect(len(publication_ids), 'nouvelle')} ou {inflect(len(publication_ids), 'modifiée')}",
        quantity(len(rows), "document source", "documents sources"),
    )

    cache = SubjectCache(store)
    n_links = 0
    with track_progress(len(rows), LAST_BRANCH.rstrip(), logger) as progress:
        for r in rows:
            progress.advance()
            extractor_lang = SUBJECT_EXTRACTORS.get(r.source)
            if extractor_lang is None:
                continue
            extractor, language = extractor_lang
            links = [
                PublicationSubjectLink(
                    r.publication_id,
                    cache.get_or_upsert(label=label, language=language),
                )
                for label in extractor(r.topics)
            ]
            n_links += cache.link_bulk(source=r.source, rows=links)

    store.mark_subjects_ingested(publication_ids=publication_ids)
    store.purge_orphan_subjects()
    subjects_after = store.count_all_subjects()

    metrics = PhaseMetrics()
    metrics.add(new=n_links, seen=len(rows))
    metrics.details["summary"] = {
        "subjects_added": subjects_after - subjects_before,
        "subjects_total": subjects_after,
        "publications_updated": len(publication_ids),
    }
    return metrics
