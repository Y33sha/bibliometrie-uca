"""Ingestion des sujets d'une publication — première étape de la phase `subjects` (avant les co-occurrences).

Incrémental et publication-centré :
  1. Sélectionne les publications dont le contenu canonique a changé depuis la dernière ingestion de leurs sujets (`publications.updated_at` > `max(publication_subjects.created_at)`), ou jamais ingérées.
  2. Dégage leurs liens `publication_subjects` (non rejetés).
  3. Ré-ingère, par `source_publication`, via l'extracteur de libellés de chaque source (`extractors`), avec un `SubjectCache` global (un même label ne déclenche qu'un seul UPSERT, y compris entre sources).
  4. Purge les `subjects` devenus orphelins (plus aucun lien).

Seuls les concepts issus des ontologies sources (champ `topics` : domaines, topics, disciplines…) sont ingérés. Les mots-clés libres (`keywords`) restent portés par `source_publications` et affichés via `publications_detail.keywords`, hors de `subjects`.

On lit les `source_publications` (et non `publications_detail`) pour préserver l'attribution par-source : `publication_subjects.source` dit quelle source a fourni chaque sujet.

Aucune colonne d'état dédiée : la référence « dernière ingestion » est le `created_at` des liens eux-mêmes ; la purge des orphelins (étape 4) remplace l'ancien référentiel « jamais purgé ».
"""

import logging
import time

from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.pipeline.subjects._common import SubjectCache
from application.pipeline.subjects.extractors import SUBJECT_EXTRACTORS
from application.ports.pipeline.subjects import SubjectsQueries

# Fréquence des logs de progression.
_LOG_EVERY = 2000


def run(
    conn: Connection,
    queries: SubjectsQueries,
    logger: logging.Logger,
    *,
    rebuild: bool = False,
) -> PhaseMetrics:
    """Ré-ingère les sujets des publications modifiées depuis la dernière passe (ou de toutes si `rebuild`).

    `metrics.new` porte le nombre de liens publication↔sujet créés ; le résumé sur-mesure expose les sujets ajoutés (évolution nette du référentiel, ingestion moins purge des orphelins), le nouveau total du vocabulaire et le nombre de publications ré-ingérées.

    `rebuild` repasse toutes les publications, indépendamment du signal incrémental : chaque lien non rejeté est effacé puis reconstruit, et la purge finale retire les sujets devenus sans lien. Sert à propager une évolution des règles d'ingestion sur tout le stock.
    """
    t_run = time.perf_counter()
    subjects_before = queries.count_subjects(conn)

    if rebuild:
        pub_ids = queries.select_all_publication_ids(conn)
        logger.info("subjects : rebuild complet — %d publications à ré-ingérer", len(pub_ids))
    else:
        pub_ids = queries.select_publications_to_reingest(conn)
    if not pub_ids:
        n_purged = queries.purge_orphan_subjects(conn)
        logger.info("subjects : rien à ré-ingérer ; %d sujets orphelins purgés", n_purged)
        subjects_after = queries.count_subjects(conn)
        metrics = PhaseMetrics()
        metrics.details["summary"] = {
            "subjects_added": subjects_after - subjects_before,
            "subjects_total": subjects_after,
            "publications_updated": 0,
        }
        return metrics

    n_cleared = queries.clear_publication_subjects_for_pubs(conn, publication_ids=pub_ids)
    rows = queries.select_source_publications_for_pubs(conn, publication_ids=pub_ids)
    logger.info(
        "subjects : %d publications à ré-ingérer (%d source_publications, clear: %d liens)",
        len(pub_ids),
        len(rows),
        n_cleared,
    )

    cache = SubjectCache(queries)
    total = len(rows)
    n_links = 0
    t0 = time.perf_counter()
    for i, r in enumerate(rows, start=1):
        extractor_lang = SUBJECT_EXTRACTORS.get(r.source)
        if extractor_lang is None:
            continue
        extractor, language = extractor_lang
        links = [
            (r.publication_id, cache.get_or_upsert(conn, label=label, language=language))
            for label in extractor(r.topics)
        ]
        n_links += cache.link_bulk(conn, source=r.source, rows=links)
        if i % _LOG_EVERY == 0:
            elapsed = time.perf_counter() - t0
            rate = i / elapsed if elapsed else 0.0
            logger.info(
                "subjects : %d/%d source_publications (%.0f/s, %d liens, cache: %d sujets)",
                i,
                total,
                rate,
                n_links,
                sum(cache.stats().values()),
            )

    n_purged = queries.purge_orphan_subjects(conn)
    logger.info(
        "subjects : %d liens créés, %d sujets orphelins purgés, %.1fs",
        n_links,
        n_purged,
        time.perf_counter() - t_run,
    )
    subjects_after = queries.count_subjects(conn)

    metrics = PhaseMetrics()
    metrics.add(new=n_links, total=len(rows))
    metrics.details["summary"] = {
        "subjects_added": subjects_after - subjects_before,
        "subjects_total": subjects_after,
        "publications_updated": len(pub_ids),
    }
    return metrics
