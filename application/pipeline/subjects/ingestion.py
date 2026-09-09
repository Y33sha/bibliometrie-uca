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

from sqlalchemy import Connection

from application.pipeline.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape, forme
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.progression import progression
from application.pipeline.subjects._common import SubjectCache
from application.pipeline.subjects.extractors import SUBJECT_EXTRACTORS
from application.ports.pipeline.subjects import PublicationSubjectLink, SubjectsIngestionQueries


def run(
    conn: Connection,
    queries: SubjectsIngestionQueries,
    logger: logging.Logger,
    *,
    rebuild: bool = False,
) -> PhaseMetrics:
    """Ré-ingère les sujets des publications modifiées depuis la dernière passe (ou de toutes si `rebuild`).

    `metrics.new` porte le nombre de liens publication↔sujet créés ; le résumé sur-mesure expose les sujets ajoutés (évolution nette du référentiel, ingestion moins purge des orphelins), le nouveau total du vocabulaire et le nombre de publications ré-ingérées.

    `rebuild` repasse toutes les publications, indépendamment du signal incrémental : chaque lien non rejeté est effacé puis reconstruit, et la purge finale retire les sujets devenus sans lien. Sert à propager une évolution des règles d'ingestion sur tout le stock.
    """
    subjects_before = queries.count_all_subjects(conn)
    etape(logger, "Liens publications-sujets")

    if rebuild:
        pub_ids = queries.select_all_publication_ids(conn)
    else:
        pub_ids = queries.select_publications_to_reingest(conn)
    if not pub_ids:
        queries.purge_orphan_subjects(conn)
        logger.info("%sRien à faire", DERNIERE_BRANCHE)
        subjects_after = queries.count_all_subjects(conn)
        metrics = PhaseMetrics()
        metrics.details["summary"] = {
            "subjects_added": subjects_after - subjects_before,
            "subjects_total": subjects_after,
            "publications_updated": 0,
        }
        return metrics

    queries.clear_publication_subjects_for_pubs(conn, publication_ids=pub_ids)
    rows = queries.select_source_publications_for_pubs(conn, publication_ids=pub_ids)
    logger.info(
        "%s%s à traiter (%s), soit %s",
        BRANCHE,
        accord(len(pub_ids), "publication"),
        "reconstruction complète"
        if rebuild
        else f"{forme(len(pub_ids), 'nouvelle')} ou {forme(len(pub_ids), 'modifiée')}",
        accord(len(rows), "document source"),
    )

    cache = SubjectCache(queries)
    n_links = 0
    with progression(len(rows), DERNIERE_BRANCHE.rstrip(), logger) as avancement:
        for r in rows:
            avancement.avance()
            extractor_lang = SUBJECT_EXTRACTORS.get(r.source)
            if extractor_lang is None:
                continue
            extractor, language = extractor_lang
            links = [
                PublicationSubjectLink(
                    r.publication_id,
                    cache.get_or_upsert(conn, label=label, language=language),
                )
                for label in extractor(r.topics)
            ]
            n_links += cache.link_bulk(conn, source=r.source, rows=links)

    queries.purge_orphan_subjects(conn)
    subjects_after = queries.count_all_subjects(conn)

    metrics = PhaseMetrics()
    metrics.add(new=n_links, total=len(rows))
    metrics.details["summary"] = {
        "subjects_added": subjects_after - subjects_before,
        "subjects_total": subjects_after,
        "publications_updated": len(pub_ids),
    }
    return metrics
