#!/usr/bin/env python3
"""
Orchestrateur du pipeline bibliométrique UCA.

Usage:
    python run_pipeline.py                    # Pipeline complet
    python run_pipeline.py --from normalize   # Reprendre depuis la normalisation
    python run_pipeline.py --only extract     # Exécuter une seule phase
    python run_pipeline.py --list             # Lister les phases
    python run_pipeline.py --dry-run          # Afficher sans exécuter
    python run_pipeline.py --mode daily       # Import quotidien (HAL depuis dernier run)
    python run_pipeline.py --mode weekly      # Import années n et n-1 (WoS exclu)
    python run_pipeline.py --mode full        # Repasse complète + cross-imports + enrichissements
    python run_pipeline.py --sources hal,openalex  # Extraction HAL + OA seulement
    python run_pipeline.py --only extract --sources scanr --year 2023  # ScanR 2023 seul

Phases (dans l'ordre d'execution):
    extract              Extraction des sources vers staging (HAL, OpenAlex, WoS, ScanR, theses.fr)
    fetch_missing_hal_id Fetch des documents HAL manquants par hal-id/NNT (auto-borné, tourne toujours)
    fetch_missing_doi    Fetch par DOI des records manquants dans chaque source (scope policy)
    normalize      Normalisation staging -> tables sources (source_publications, source_persons,
                   source_authorships). Rattachement aux publications existantes par DOI/NNT/
                   HAL-ID, mais PAS de creation de publications. Inclut enrichissement
                   structures HAL et extraction des identifiants ORCID/IdRef depuis le TEI HAL.
                   Crée les adresses et liens source_authorship_addresses.
                   Vide le raw_data du staging apres traitement + VACUUM.
    affiliations   Résolution adresses → structures, puis propagation
                   in_perimeter et structure_ids sur source_authorships
    publications   Creation des publications pour les source_publications in-perimeter non
                   rattaches + merges inter-sources (HAL-ID, NNT)
    persons        Creation/mapping personnes + formes de noms
    authorships    Reconstruction authorships canoniques (table de verite) + propagation UCA
    countries      Detection pays des adresses + recalcul pays des publications
    subjects       Ingestion des sujets/mots-cles depuis source_publications vers subjects + publication_subjects
    cooccurrences  Recalcul de subjects.usage_count + table subject_cooccurrences (post-subjects)
    enrich         Enrichissements optionnels (statut OA via Unpaywall, APC revues)
"""

import argparse
import atexit
import datetime
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from domain.pipeline_modes import MODE_NAMES, MODES
from domain.sources import ALL_SOURCES_SET
from infrastructure.log import setup_logger
from infrastructure.pipeline_status import clear_status, read_status, write_status

BASE = Path(__file__).resolve().parent

# `setup_logger` (au lieu d'un simple `getLogger`) attache un FileHandler
# sur `logs/pipeline.log` quand `LOG_TO_FILE=true`. Indispensable pour
# que `read_new_logs` (cf. `infrastructure/pipeline_metrics.py`) capture
# les logs des phases qui réutilisent ce logger parent (subjects,
# cooccurrences, enrich) et les remonte dans /admin/pipeline.
log = setup_logger("pipeline", str(BASE / "logs"))


# Garantir le nettoyage même en cas de Ctrl+C ou crash
atexit.register(clear_status)


# ---------------------------------------------------------------------------
# Définition des phases
# ---------------------------------------------------------------------------


def phase_extract(mode: Any = "full", sources: Any = None, year: Any = None, **kw: Any) -> Any:
    """Phase 1 : Extraction des sources vers staging + refetch truncated.

    La politique du mode (sources à interroger, plage d'années, refetch OA)
    vit dans `domain/pipeline_modes.py`. Les scripts d'extraction lisent
    la config DB pour les plages d'années (`pipeline_years_full/weekly`).
    """
    policy = MODES[mode]
    effective = (set(sources) if sources else set(policy.extract_sources)) & policy.extract_sources
    year_args = ["--year", str(year)] if year else []

    if policy.year_selection == "since_last":
        # HAL uniquement, depuis le dernier rapport de pipeline (à 00:00).
        # OpenAlex n'a pas d'équivalent (filtre `from_updated_date` payant ;
        # changefiles non filtrables par institution) et est rattrapé par
        # le mode weekly.
        from infrastructure.pipeline_metrics import get_last_report_date

        last = get_last_report_date()
        if last is not None:
            since = last.isoformat()
            log.info("Mode quotidien : HAL depuis %s (dernier rapport)", since)
        else:
            since = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
            log.info("Mode quotidien : HAL depuis %s (fallback, aucun rapport)", since)
        if "hal" in effective:
            run_python("infrastructure/sources/hal/extract_hal.py", "--since", since)
    else:
        sub_mode = policy.year_selection  # "weekly" ou "full"
        if mode == "weekly":
            log.info("Mode hebdomadaire (WoS exclu)")
        if "openalex" in effective:
            run_python(
                "infrastructure/sources/openalex/extract_openalex.py",
                "--mode",
                sub_mode,
                *year_args,
            )
        if "hal" in effective:
            run_python("infrastructure/sources/hal/extract_hal.py", "--mode", sub_mode, *year_args)
        if "wos" in effective:
            run_python("infrastructure/sources/wos/extract_wos.py", "--mode", sub_mode, *year_args)
        if "scanr" in effective:
            run_python(
                "infrastructure/sources/scanr/extract_scanr.py", "--mode", sub_mode, *year_args
            )
        if "theses" in effective:
            run_python(
                "infrastructure/sources/theses/extract_theses.py",
                "--mode",
                sub_mode,
                *year_args,
            )

    if policy.refetch_truncated_oa and "openalex" in effective:
        run_python("infrastructure/sources/openalex/refetch_truncated.py")


def phase_fetch_missing_hal_id(mode: Any = "full", sources: Any = None, **kw: Any) -> Any:
    """Phase 2a : fetch des documents HAL manquants par hal-id/NNT.

    Opération auto-bornée : les hal-ids/NNT introuvables sont marqués
    `not_found=TRUE` dans staging et ne sont jamais re-interrogés. Tourne
    donc systématiquement (daily/weekly/full) sans scope.
    """
    if sources and "hal" not in sources:
        return
    run_python("infrastructure/sources/hal/fetch_missing_hal_id.py", "--mode", mode)


def phase_fetch_missing_doi(mode: Any = "full", sources: Any = None, **kw: Any) -> Any:
    """Phase 2b : fetch des records manquants par DOI dans chaque source.

    Scope (`unprocessed` vs `all`) et sources cibles viennent de la policy
    du mode (cf. `domain/pipeline_modes.py`). Un seul dispatcher CLI
    (`interfaces.cli.pipeline.fetch_missing_doi`) est appelé une fois
    par source cible.
    """
    policy = MODES[mode]
    effective = (
        set(sources) if sources else set(policy.fetch_missing_doi_sources)
    ) & policy.fetch_missing_doi_sources
    scope_flag = ["--all"] if policy.fetch_missing_doi_scope == "all" else []

    for target in ("hal", "openalex", "wos", "scanr", "crossref"):
        if target in effective:
            run_python(
                "interfaces/cli/pipeline/fetch_missing_doi.py",
                "--target",
                target,
                *scope_flag,
            )


def phase_normalize(**kw: Any) -> Any:
    """Normalisation staging -> tables sources.

    Rattache aux publications existantes (DOI/NNT/HAL-ID) sans en creer.
    Stocke les metadonnees (abstract, keywords, topics, biblio, etc.) sur
    source_publications. Vide le raw_data du staging apres traitement.
    Pour HAL : enrichit les structures et extrait ORCID/IdRef depuis le TEI.
    """
    sources = kw.get("sources", set(ALL_SOURCES_SET))
    # Ordre d'exécution : source la plus autoritative en premier
    # (cf. SOURCE_PRIORITY dans domain/sources.py). Les sources suivantes
    # n'écrasent pas les métadonnées déjà posées par les précédentes
    # lors de `refresh_from_sources`.
    if "theses" in sources:
        _run_normalize_theses()
    if "crossref" in sources:
        _run_normalize_crossref()
    if "scanr" in sources:
        _run_normalize_scanr()
    if "hal" in sources:
        _run_normalize_hal()
    if "openalex" in sources:
        _run_normalize_openalex()
    if "wos" in sources:
        _run_normalize_wos()
    mode = kw.get("mode", "full")
    policy = MODES[mode]
    # Libérer l'espace TOAST du staging (raw_data vidé après normalisation)
    if policy.vacuum_full:
        log.info("VACUUM FULL staging...")
        _vacuum_staging(full=True)
    else:
        log.info("VACUUM staging...")
        _vacuum_staging(full=False)


def _vacuum_staging(full: bool = False) -> Any:
    """VACUUM sur staging. FULL en mode full/monthly, simple sinon."""
    from infrastructure.db.connection import get_connection

    conn = get_connection()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("VACUUM FULL staging" if full else "VACUUM staging")
    conn.close()


def phase_affiliations(**kw: Any) -> Any:
    """Résolution des affiliations UCA sur les source_authorships.

    1. resolve_addresses : matche les adresses vers les structures connues
    2. populate_affiliations : propage in_perimeter et structure_ids

    Phase source-agnostique : `--sources` n'est pas propagé. Sinon des
    source_authorships d'une source non listée resteraient bloquées sans
    `structure_ids` après la résolution d'une nouvelle adresse.
    """
    mode = kw.get("mode", "full")
    _run_resolve_addresses(mode)
    _run_populate_affiliations(mode=mode)


def phase_publications(**kw: Any) -> Any:
    """Creation des publications canoniques.

    Ne cree des publications que pour les source_publications ayant au moins
    une source_authorship in_perimeter (evite de creer des publications
    hors perimetre). Applique ensuite les merges inter-sources (HAL-ID, NNT).
    """
    _run_create_publications()
    _run_merge_pubs_by_hal_id()
    _run_merge_pubs_by_nnt()


def phase_persons(**kw: Any) -> Any:
    """Creation et rattachement des personnes.

    Cree des personnes a partir des source_authorships in_perimeter non rattachees.
    Exclut les publications de type memoir (v_active_publications).
    Rattache aussi les authorships theses hors-perimetre par IdRef.
    """
    _run_create_persons()
    _run_populate_person_name_forms()


def phase_authorships(**kw: Any) -> Any:
    """Construction de la table de verite authorships.

    Consolide les source_authorships en authorships canoniques
    (une entree par couple publication x personne), avec in_perimeter
    et structure_ids propages.

    Phase source-agnostique : `--sources` n'est pas propagé. Une
    source_authorship peut etre touchee par d'autres voies que sa propre
    normalisation (re-population d'affiliations, refresh_from_sources,
    etc.) — toutes les sources doivent etre reconsolidees a chaque run.
    """
    _run_build_authorships()


def phase_countries(**kw: Any) -> Any:
    """Detection des pays des adresses et recalcul sur les publications."""
    run_python("interfaces/cli/pipeline/detect_address_countries.py", "--direct", "--apply")
    run_python("interfaces/cli/pipeline/suggest_address_countries.py")
    _run_refresh_publication_countries()


def phase_subjects(**kw: Any) -> Any:
    """Ingestion des sujets/mots-clés depuis source_publications.

    Lit les colonnes `keywords` et `topics` déjà persistées par les
    normalizers et alimente les tables canoniques `subjects` et
    `publication_subjects`. Idempotent.

    Phase source-agnostique : `--sources` n'est pas propagé. Les topics
    peuvent évoluer côté `source_publications` par d'autres voies (re-
    normalisation, refresh_from_sources) — toutes les sources doivent
    être ré-ingérées à chaque run.
    """
    _run_ingest_subjects()


def phase_cooccurrences(**kw: Any) -> Any:
    """Recalcul de `subjects.usage_count` + table `subject_cooccurrences`.

    Doit tourner après `subjects`. Idempotent.
    """
    _run_cooccurrences()


def _run_create_publications() -> None:
    from application.pipeline.publications.create_publications import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.publications.create import PgPublicationsCreateQueries
    from infrastructure.repositories import publication_repository

    log.info("▶ create_publications")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        run(
            conn,
            PgPublicationsCreateQueries(),
            log,
            pub_repo=publication_repository(conn),
        )
    finally:
        conn.close()
    log.info("✓ create_publications terminé en %.1fs", time.time() - t0)


def _run_create_persons() -> None:
    from application.pipeline.persons.create_persons_from_source_authorships import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.persons.create import PgPersonsCreateQueries
    from infrastructure.repositories import person_repository

    log.info("▶ create_persons_from_source_authorships")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        run(
            conn,
            PgPersonsCreateQueries(),
            log,
            person_repo=person_repository(conn),
        )
    finally:
        conn.close()
    log.info("✓ create_persons_from_source_authorships terminé en %.1fs", time.time() - t0)


def _run_build_authorships() -> None:
    from application.pipeline.authorships.build_authorships import build
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.authorships_build import PgAuthorshipsBuildQueries

    log.info("▶ build_authorships")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        build(conn, PgAuthorshipsBuildQueries(), log)
        conn.commit()
    finally:
        conn.close()
    log.info("✓ build_authorships terminé en %.1fs", time.time() - t0)


def _run_populate_affiliations(*, mode: str) -> None:
    from application.pipeline.affiliations.populate_affiliations import run_populate
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.affiliations import PgAffiliationsQueries
    from infrastructure.perimeter import (
        get_affiliations_structure_ids,
        get_persons_structure_ids,
    )

    log.info("▶ populate_affiliations --mode %s", mode)
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        perimeter_ids = get_persons_structure_ids(conn)
        wide_ids = get_affiliations_structure_ids(conn)
        run_populate(
            conn,
            PgAffiliationsQueries(),
            log,
            perimeter_ids,
            wide_ids,
            mode=mode,
        )
    finally:
        conn.close()
    log.info("✓ populate_affiliations terminé en %.1fs", time.time() - t0)


def _run_populate_person_name_forms() -> None:
    from application.pipeline.persons.populate_person_name_forms import populate
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.name_forms import PgNameFormsQueries

    log.info("▶ populate_person_name_forms")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        populate(conn, PgNameFormsQueries(), log)
    finally:
        conn.close()
    log.info("✓ populate_person_name_forms terminé en %.1fs", time.time() - t0)


def _run_merge_pubs_by_nnt() -> None:
    from application.pipeline.publications.merge_pubs_by_nnt import run_merge
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.merge import PgMergeQueries
    from infrastructure.repositories import publication_repository

    log.info("▶ merge_pubs_by_nnt")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        run_merge(conn, PgMergeQueries(), log, pub_repo=publication_repository(conn))
    finally:
        conn.close()
    log.info("✓ merge_pubs_by_nnt terminé en %.1fs", time.time() - t0)


def _run_merge_pubs_by_hal_id() -> None:
    from application.pipeline.publications.merge_pubs_by_hal_id import run_merge
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.merge import PgMergeQueries
    from infrastructure.repositories import publication_repository

    log.info("▶ merge_pubs_by_hal_id")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        run_merge(conn, PgMergeQueries(), log, pub_repo=publication_repository(conn))
    finally:
        conn.close()
    log.info("✓ merge_pubs_by_hal_id terminé en %.1fs", time.time() - t0)


def _run_normalize_hal() -> None:
    from application.pipeline.normalize.normalize_hal import HalNormalizer
    from infrastructure.addresses import PgAddressLinker
    from infrastructure.app_config import get_api_base_urls
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.normalize_hal import PgHalNormalizeQueries
    from infrastructure.db.queries.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )
    from infrastructure.zenodo import HttpZenodoResolver

    log.info("▶ normalize_hal")
    t0 = time.time()
    engine = get_sync_engine()
    with engine.connect() as bootstrap:
        zenodo_api = get_api_base_urls(bootstrap)["zenodo"]
    conn = engine.connect()
    HalNormalizer(
        conn,
        log,
        PgStagingQueries(),
        PgHalNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
        zenodo_resolver=HttpZenodoResolver(api_base=zenodo_api),
        address_linker=PgAddressLinker(),
    ).run([])
    log.info("✓ normalize_hal terminé en %.1fs", time.time() - t0)


def _run_normalize_wos() -> None:
    from application.pipeline.normalize.normalize_wos import WosNormalizer
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.normalize_wos import PgWosNormalizeQueries
    from infrastructure.db.queries.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )

    log.info("▶ normalize_wos")
    t0 = time.time()
    conn = get_sync_engine().connect()
    WosNormalizer(
        conn,
        log,
        PgStagingQueries(),
        PgWosNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
    ).run([])
    log.info("✓ normalize_wos terminé en %.1fs", time.time() - t0)


def _run_normalize_openalex() -> None:
    from application.pipeline.normalize.normalize_openalex import OpenalexNormalizer
    from infrastructure.addresses import PgAddressLinker
    from infrastructure.app_config import get_api_base_urls
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.normalize_openalex import PgOpenalexNormalizeQueries
    from infrastructure.db.queries.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )
    from infrastructure.zenodo import HttpZenodoResolver

    log.info("▶ normalize_openalex")
    t0 = time.time()
    engine = get_sync_engine()
    with engine.connect() as bootstrap:
        zenodo_api = get_api_base_urls(bootstrap)["zenodo"]
    conn = engine.connect()
    OpenalexNormalizer(
        conn,
        log,
        PgStagingQueries(),
        PgOpenalexNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
        zenodo_resolver=HttpZenodoResolver(api_base=zenodo_api),
        address_linker=PgAddressLinker(),
    ).run([])
    log.info("✓ normalize_openalex terminé en %.1fs", time.time() - t0)


def _run_normalize_scanr() -> None:
    from application.pipeline.normalize.normalize_scanr import ScanrNormalizer
    from infrastructure.addresses import PgAddressLinker
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.normalize_scanr import PgScanrNormalizeQueries
    from infrastructure.db.queries.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )

    log.info("▶ normalize_scanr")
    t0 = time.time()
    conn = get_sync_engine().connect()
    ScanrNormalizer(
        conn,
        log,
        PgStagingQueries(),
        PgScanrNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
        address_linker=PgAddressLinker(),
    ).run([])
    log.info("✓ normalize_scanr terminé en %.1fs", time.time() - t0)


def _run_normalize_theses() -> None:
    from application.pipeline.normalize.normalize_theses import ThesesNormalizer
    from infrastructure.addresses import PgAddressLinker
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.normalize_theses import PgThesesNormalizeQueries
    from infrastructure.db.queries.staging import PgStagingQueries
    from infrastructure.repositories import publication_repository

    log.info("▶ normalize_theses")
    t0 = time.time()
    conn = get_sync_engine().connect()
    ThesesNormalizer(
        conn,
        log,
        PgStagingQueries(),
        PgThesesNormalizeQueries(),
        pub_repo_factory=publication_repository,
        address_linker=PgAddressLinker(),
    ).run([])
    log.info("✓ normalize_theses terminé en %.1fs", time.time() - t0)


def _run_normalize_crossref() -> None:
    from application.pipeline.normalize.normalize_crossref import CrossrefNormalizer
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.normalize_crossref import PgCrossrefNormalizeQueries
    from infrastructure.db.queries.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )

    log.info("▶ normalize_crossref")
    t0 = time.time()
    conn = get_sync_engine().connect()
    CrossrefNormalizer(
        conn,
        log,
        PgStagingQueries(),
        PgCrossrefNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
    ).run([])
    log.info("✓ normalize_crossref terminé en %.1fs", time.time() - t0)


def _run_enrich_oa_status() -> None:
    from application.pipeline.enrich.enrich_oa_status import run_enrich
    from infrastructure.api_limits import UNPAYWALL_DELAY
    from infrastructure.app_config import get_api_base_urls
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.enrich import PgEnrichQueries
    from infrastructure.repositories import publication_repository

    log.info("▶ enrich_oa_status")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        run_enrich(
            conn,
            PgEnrichQueries(),
            log,
            pub_repo=publication_repository(conn),
            unpaywall_base=get_api_base_urls(conn)["unpaywall"],
            rate_delay=UNPAYWALL_DELAY,
        )
    finally:
        conn.close()
    log.info("✓ enrich_oa_status terminé en %.1fs", time.time() - t0)


def _run_enrich_journal_apc() -> None:
    from application.pipeline.enrich.enrich_journal_apc import run_enrich
    from infrastructure.api_limits import DOAJ_DELAY
    from infrastructure.app_config import get_api_base_urls
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.enrich import PgEnrichQueries
    from infrastructure.repositories import journal_repository

    log.info("▶ enrich_journal_apc")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        run_enrich(
            conn,
            PgEnrichQueries(),
            log,
            journal_repo=journal_repository(conn),
            mailto="bibliometrie@uca.fr",
            openalex_sources_api=get_api_base_urls(conn)["openalex_sources"],
            rate_delay=DOAJ_DELAY,
        )
    finally:
        conn.close()
    log.info("✓ enrich_journal_apc terminé en %.1fs", time.time() - t0)


def _run_resolve_addresses(mode: str) -> None:
    from application.pipeline.affiliations.resolve_addresses import run_resolution
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.address_resolution import PgAddressResolutionQueries
    from infrastructure.perimeter import get_persons_structure_ids

    log.info("▶ resolve_addresses --mode %s", mode)
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        perimeter_ids = get_persons_structure_ids(conn)
        run_resolution(conn, PgAddressResolutionQueries(), perimeter_ids, log, mode=mode)
    finally:
        conn.close()
    log.info("✓ resolve_addresses terminé en %.1fs", time.time() - t0)


def _run_refresh_publication_countries() -> None:
    from application.pipeline.countries.refresh_publication_countries import refresh
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.countries import PgCountryQueries

    log.info("▶ refresh_publication_countries")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        refresh(conn, PgCountryQueries(), log)
        conn.commit()
    finally:
        conn.close()
    log.info("✓ refresh_publication_countries terminé en %.1fs", time.time() - t0)


def _run_ingest_subjects() -> None:
    from application.pipeline.subjects.run import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.subjects import PgSubjectsQueries

    log.info("▶ subjects")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        run(conn, PgSubjectsQueries(), log)
        conn.commit()
    finally:
        conn.close()
    log.info("✓ subjects terminé en %.1fs", time.time() - t0)


def _run_cooccurrences() -> None:
    from application.pipeline.cooccurrences.run import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.queries.subjects import PgSubjectsQueries

    log.info("▶ cooccurrences")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        run(conn, PgSubjectsQueries(), log)
        conn.commit()
    finally:
        conn.close()
    log.info("✓ cooccurrences terminé en %.1fs", time.time() - t0)


def phase_enrich(mode: Any = "full", **kw: Any) -> Any:
    """Enrichissements optionnels (Unpaywall, APC revues).

    Gouverné par `ModePolicy.run_enrich` (cf. `domain/pipeline_modes.py`).
    """
    if MODES[mode].run_enrich:
        _run_enrich_oa_status()
        _run_enrich_journal_apc()
    else:
        log.info("Enrichissements ignorés en mode %s", mode)


# Registre des phases, dans l'ordre
PHASES = [
    ("extract", phase_extract),
    ("fetch_missing_hal_id", phase_fetch_missing_hal_id),
    ("fetch_missing_doi", phase_fetch_missing_doi),
    ("normalize", phase_normalize),
    ("affiliations", phase_affiliations),
    ("publications", phase_publications),
    ("persons", phase_persons),
    ("authorships", phase_authorships),
    ("countries", phase_countries),
    ("subjects", phase_subjects),
    ("cooccurrences", phase_cooccurrences),
    ("enrich", phase_enrich),
]

PHASE_NAMES = [name for name, _ in PHASES]


# ---------------------------------------------------------------------------
# Helpers d'exécution
# ---------------------------------------------------------------------------


def run_python(script: str, *args: Any) -> Any:
    """Lance un script Python du projet."""
    path = BASE / script
    if not path.exists():
        log.warning("Script introuvable : %s — ignoré", script)
        return
    cmd = [sys.executable, str(path)] + list(args)
    log.info("▶ %s %s", script, " ".join(args) if args else "")
    t0 = time.time()
    result = subprocess.run(cmd, cwd=str(BASE))
    elapsed = time.time() - t0
    if result.returncode != 0:
        log.error("✗ %s a échoué (code %d) en %.1fs", script, result.returncode, elapsed)
        raise RuntimeError(f"{script} a échoué (code {result.returncode})")
    log.info("✓ %s terminé en %.1fs", script, elapsed)

    # run_sql supprimé — tous les scripts SQL ont été convertis en Python


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _sigterm_raises_keyboard_interrupt(_signum: int, _frame: Any) -> None:
    raise KeyboardInterrupt


def _install_sigterm_handler() -> None:
    """Convertit SIGTERM en KeyboardInterrupt pour réutiliser le handler
    existant (log d'interruption, rapport partiel, commande de reprise).

    Utile quand un orchestrateur (systemd, docker stop, kubectl delete)
    arrête le pipeline poliment. Sans ça, le process est tué silencieusement
    sans trace du point d'interruption — l'idempotence permettrait quand
    même la reprise, mais sans rapport sur le run coupé.
    No-op effectif sur Windows où SIGTERM n'est pas délivré par os.kill.
    """
    signal.signal(signal.SIGTERM, _sigterm_raises_keyboard_interrupt)


def main() -> None:
    _install_sigterm_handler()
    # Nettoie un status.json orphelin (PID mort : SIGKILL, crash, OOM)
    # laissé par un run précédent — sinon le prochain lecteur verrait un
    # statut fantôme jusqu'à notre premier write_status() de phase.
    read_status()
    parser = argparse.ArgumentParser(description="Orchestrateur pipeline bibliométrique UCA")
    parser.add_argument(
        "--from", dest="from_phase", metavar="PHASE", help="Reprendre depuis cette phase"
    )
    parser.add_argument("--only", metavar="PHASE", help="Exécuter uniquement cette phase")
    parser.add_argument("--list", action="store_true", help="Lister les phases disponibles")
    parser.add_argument("--dry-run", action="store_true", help="Afficher les étapes sans exécuter")
    parser.add_argument(
        "--mode",
        choices=list(MODE_NAMES),
        default="full",
        help="Mode d'exécution (défaut: full)",
    )
    parser.add_argument(
        "--sources",
        default=",".join(ALL_SOURCES_SET),
        help="Sources, séparées par des virgules (défaut: hal,openalex,wos,scanr,theses)",
    )
    parser.add_argument(
        "--year", type=int, help="Surcharger l'année d'extraction (une seule année)"
    )
    parser.add_argument(
        "--sandbox", action="store_true", help="Utiliser la base bibliometrie_sandbox"
    )
    args = parser.parse_args()

    if args.sandbox:
        os.environ["BIBLIOMETRIE_SANDBOX"] = "1"
        log.info("MODE SANDBOX — base bibliometrie_sandbox")

    if args.list:
        print("Phases disponibles :")
        for i, (name, fn) in enumerate(PHASES, 1):
            doc = fn.__doc__.strip().split("\n")[0] if fn.__doc__ else ""
            print(f"  {i}. {name:15s} — {doc}")
        return

    # Déterminer les phases à exécuter
    if args.only:
        if args.only not in PHASE_NAMES:
            print(f"Phase inconnue : {args.only}. Phases : {', '.join(PHASE_NAMES)}")
            sys.exit(1)
        phases_to_run = [(n, fn) for n, fn in PHASES if n == args.only]
    elif args.from_phase:
        if args.from_phase not in PHASE_NAMES:
            print(f"Phase inconnue : {args.from_phase}. Phases : {', '.join(PHASE_NAMES)}")
            sys.exit(1)
        idx = PHASE_NAMES.index(args.from_phase)
        phases_to_run = PHASES[idx:]
    else:
        phases_to_run = PHASES

    log.info("=" * 60)
    log.info("PIPELINE BIBLIOMÉTRIQUE UCA — mode %s", args.mode)
    log.info("Phases : %s", " → ".join(n for n, _ in phases_to_run))
    log.info("=" * 60)

    if args.dry_run:
        for name, fn in phases_to_run:
            doc = fn.__doc__.strip().split("\n")[0] if fn.__doc__ else ""
            print(f"  [{name}] {doc}")
        print("\n(dry-run : rien n'a été exécuté)")
        return

    sources = set(s.strip() for s in args.sources.split(",") if s.strip())
    log.info("Sources : %s", ", ".join(sorted(sources)))

    # Métriques pipeline
    from infrastructure.pipeline_metrics import capture_log_offsets, generate_report, read_new_logs

    phase_results = []  # [(name, duration, logs)]

    t0_total = time.time()
    pipeline_started_at = datetime.datetime.now().isoformat(timespec="seconds")
    for i, (name, fn) in enumerate(phases_to_run):
        log.info("─" * 40)
        log.info("PHASE : %s", name)
        log.info("─" * 40)

        write_status(
            mode=args.mode,
            phase=name,
            started_at=pipeline_started_at,
            phases_done=i,
            phases_total=len(phases_to_run),
        )

        log_offsets = capture_log_offsets()
        t0_phase = time.time()
        try:
            fn(
                mode=args.mode,
                sources=sources,
                year=args.year,
            )
        except KeyboardInterrupt:
            log.warning("Pipeline interrompu par l'utilisateur à la phase '%s'", name)
            log.info("Pour reprendre : python run_pipeline.py --from %s", name)
            phase_logs = read_new_logs(log_offsets)
            phase_results.append((name + " (INTERROMPU)", time.time() - t0_phase, phase_logs))
            report_path = generate_report(args.mode, sources, phase_results, time.time() - t0_total)
            log.info("Rapport partiel : %s", report_path)
            clear_status()
            sys.exit(130)
        except RuntimeError as e:
            log.error("Pipeline interrompu à la phase '%s' : %s", name, e)
            log.error("Pour reprendre : python run_pipeline.py --from %s", name)
            phase_logs = read_new_logs(log_offsets)
            phase_results.append((name + " (ERREUR)", time.time() - t0_phase, phase_logs))
            report_path = generate_report(args.mode, sources, phase_results, time.time() - t0_total)
            log.info("Rapport partiel : %s", report_path)
            clear_status()
            sys.exit(1)

        duration = time.time() - t0_phase
        phase_logs = read_new_logs(log_offsets)
        phase_results.append((name, duration, phase_logs))

    elapsed_total = time.time() - t0_total

    # Générer le rapport
    report_path = generate_report(args.mode, sources, phase_results, elapsed_total)
    log.info("Rapport : %s", report_path)

    clear_status()
    log.info("=" * 60)
    log.info("PIPELINE TERMINÉ en %.0fs (%.1f min)", elapsed_total, elapsed_total / 60)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
