"""Ingestion des sujets d'une publication — première étape de la phase `subjects` (avant les co-occurrences).

Incrémental et publication-centré :
  1. Sélectionne les publications à ingérer : `publications.subjects_ingested_at` vide. L'enregistrement d'une publication recalculée depuis ses sources vide cette date ; les autres écritures sur la publication (statut OA…) la laissent en place.
  2. Dégage leurs liens `publication_subjects` (non rejetés).
  3. Ré-ingère, par `source_record`, via l'extracteur de libellés de chaque source (`extractors`), avec un `SubjectCache` global (un même label ne déclenche qu'un seul UPSERT, y compris entre sources).
  4. Date l'ingestion de chaque publication traitée, qu'elle ait des sujets ou non.
  5. Purge les `subjects` devenus orphelins (plus aucun lien).

Seuls les concepts issus des ontologies sources (champ `topics` : domaines, topics, disciplines…) sont ingérés. Les mots-clés libres (`keywords`) restent portés par `source_records` et affichés via `publications_detail.keywords`, hors de `subjects`.

On lit les `source_records` (et non `publications_detail`) pour préserver l'attribution par-source : `publication_subjects.source` dit quelle source a fourni chaque sujet.
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

    `metrics.new` porte le nombre de liens publication↔sujet créés ; le résumé sur-mesure expose les sujets ajoutés (évolution nette du référentiel, ingestion moins purge des orphelins), le nouveau total du vocabulaire et le nombre de publications ré-ingérées.

    `rebuild` marque d'abord toutes les publications à ingérer : chaque lien non rejeté est effacé puis reconstruit, et la purge finale retire les sujets devenus sans lien. Sert à propager une évolution des règles d'ingestion sur tout le stock.
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
