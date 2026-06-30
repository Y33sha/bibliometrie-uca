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
    python run_pipeline.py --mode full        # Repasse complète (toutes sources sauf WoS)
    python run_pipeline.py --start-year 2024  # Repasse sur [2024 … année courante]
    python run_pipeline.py --include-wos      # Inclure WoS (opt-in, crédit API limité)
    python run_pipeline.py --sources hal,openalex  # Extraction HAL + OA seulement
    python run_pipeline.py --only extract --sources scanr --year 2023  # ScanR 2023 seul

Phases (dans l'ordre d'execution):
    extract             Extraction des sources vers staging (HAL, OpenAlex, WoS, ScanR, theses.fr)
    cross_imports       Rattrapage cross-source : (1) docs HAL manquants par hal-id/NNT
                        (auto-borné, tourne toujours), puis (2) par DOI dans chaque source
                        cible (auto-borné par le backoff doi_lookups)
    refresh_stale       Refetch des rows à last_seen_at ancien (> STALE_REFRESH_AFTER_DAYS) :
                        trouvé -> bump last_seen_at + refresh ; 404 / sans DOI -> disappeared_at.
                        Marque seulement, aucun effet aval.
    refetch_truncated   Re-fetch des works OpenAlex tronqués à 100 auteurs, avant que
                        normalize ne les consomme.
    normalize           Normalisation staging -> tables sources (source_publications,
                        source_authorships) avec publication_id=NULL (le rattachement aux
                        publications est fait plus tard par la phase publications). Crée les
                        adresses et liens source_authorship_addresses. Vide le raw_data du
                        staging apres traitement + VACUUM.
    affiliations        Résolution adresses → structures, puis propagation in_perimeter
                        sur source_authorships
    publishers_journals Enrichissement du référentiel journals (préfixes DOI, APC, DOAJ,
                        journal_type). L'enrichissement éditeurs est hors pipeline (maintenance).
    metadata_correction Corrections de métadonnées sur source_publications (par enregistrement,
                        et par grappe de DOI : concept DataCite, ouvrage/chapitre)
    publications        Création/rattachement des publications + fusions/scissions, en une passe
    relations           Population des relations sémantiques entre publications (depuis les sources)
    persons             Creation/mapping personnes + formes de noms
    authorships         Reconstruction authorships canoniques (table de verite) + propagation
                        in_perimeter, puis purge des publications orphelines
    countries           Detection pays des adresses + recalcul pays des publications
    subjects            Sujets/mots-clés : ingestion source_publications → subjects +
                        publication_subjects, puis recalcul usage_count + matview cooccurrences
    oa_status           Statut open access par publication via Unpaywall
"""

import argparse
import asyncio
import atexit
import datetime
import signal
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from application.ports.pipeline.extract.fetch_missing_doi import AsyncFetchMissingDoiAdapter
    from infrastructure.queries.pipeline.countries import AddressCountryStatus

from application.pipeline.graph import PHASE_ORDER, watched_tables
from application.pipeline.metadata_correction.correct_by_cluster import ClusterCorrectionStats
from application.pipeline.metadata_correction.correct_unary import UnaryCorrectionStats
from application.pipeline.metadata_correction.journal_by_doi import JournalByDoiStats
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.modes import MODE_NAMES, MODES
from application.pipeline.normalize.base import NormalizeStats
from domain.sources.registry import ALL_SOURCES_SET, DOI_SEARCHABLE_SOURCES
from infrastructure.observability.log import setup_logger
from infrastructure.observability.pipeline_status import clear_status, read_status, write_status
from infrastructure.pipeline_lock import PipelineAlreadyRunningError, acquire_pipeline_lock

BASE = Path(__file__).resolve().parent

# `setup_logger` (au lieu d'un simple `getLogger`) attache un FileHandler
# sur `logs/pipeline.log` quand `LOG_TO_FILE=true` : les logs des phases qui
# réutilisent ce logger parent (subjects, cooccurrences, enrich) sont persistés.
log = setup_logger("pipeline", str(BASE / "logs"))


# Garantir le nettoyage même en cas de Ctrl+C ou crash
atexit.register(clear_status)


# ---------------------------------------------------------------------------
# Définition des phases
# ---------------------------------------------------------------------------


def _timed_metrics(fn: Callable[[], PhaseMetrics]) -> tuple[PhaseMetrics, float]:
    """Exécute `fn` et renvoie ses métriques avec sa durée d'exécution (s).

    Partagé par les phases qui ventilent leurs indicateurs par source / canal
    (`extract`, `cross_imports`, `refresh_stale`) et ont besoin d'une durée par
    sous-tâche, distincte de la durée totale de la phase.
    """
    started = time.time()
    result = fn()
    return result, time.time() - started


def phase_extract(
    mode: Any = "full",
    sources: Any = None,
    year: Any = None,
    start_year: Any = None,
    include_wos: bool = False,
    **kw: Any,
) -> PhaseMetrics:
    """Phase 1 : Extraction des sources vers staging.

    La policy du mode (sources, stratégie d'années) vit dans
    `application/pipeline/modes.py`. Le mode `full` extrait la plage
    `[start_year … courante]` (défaut config `pipeline_start_year_full`) ; le mode
    `daily` extrait HAL en incrémental par date. WoS est opt-in (`--include-wos`).

    Le refetch des works OpenAlex tronqués est une phase distincte
    (`refetch_truncated`), placée après `refresh_stale` et avant `normalize` : il
    doit voir aussi les works ramenés par cross_imports et refresh_stale avant
    que normalize ne les consomme.
    """
    policy = MODES[mode]
    allowed = set(policy.extract_sources) | ({"wos"} if include_wos else set())
    effective = (set(sources) if sources else allowed) & allowed
    metrics = PhaseMetrics()
    by_source: dict[str, dict[str, float]] = {}

    def _summary(source_metrics: PhaseMetrics, duration_s: float) -> dict[str, float]:
        return {
            "found": source_metrics.total,
            "new": source_metrics.new,
            "updated": source_metrics.updated,
            "unchanged": source_metrics.unchanged,
            "errors": source_metrics.errors,
            "duration_s": round(duration_s, 1),
        }

    if policy.year_selection == "since_last":
        # HAL uniquement, depuis la dernière extraction HAL réussie (à 00:00). On se
        # cale sur la dernière phase `extract` ayant inclus HAL, pas sur le dernier run
        # quelconque : un run partiel (sans extract) ne doit pas avancer le curseur.
        # OpenAlex n'a pas d'équivalent (filtre `from_updated_date` payant ;
        # changefiles non filtrables par institution).
        from infrastructure.observability.phase_executions import get_last_extract_date

        last = get_last_extract_date("hal")
        if last is not None:
            since = last.isoformat()
            log.info("Mode quotidien : HAL depuis %s (dernière extraction HAL)", since)
        else:
            since = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
            log.info("Mode quotidien : HAL depuis %s (fallback, aucune extraction HAL)", since)
        if "hal" in effective:
            hal_metrics, hal_duration = _timed_metrics(partial(_run_extract_hal, since=since))
            metrics.merge(hal_metrics)
            by_source["hal"] = _summary(hal_metrics, hal_duration)
    else:
        tasks: list[tuple[str, Callable[[], PhaseMetrics]]] = []
        if "openalex" in effective:
            tasks.append(
                ("openalex", partial(_run_extract_openalex, start_year=start_year, year=year))
            )
        if "hal" in effective:
            tasks.append(("hal", partial(_run_extract_hal, start_year=start_year, year=year)))
        if "wos" in effective:
            tasks.append(("wos", partial(_run_extract_wos, start_year=start_year, year=year)))
        if "scanr" in effective:
            tasks.append(("scanr", partial(_run_extract_scanr, start_year=start_year, year=year)))
        if "theses" in effective:
            tasks.append(("theses", partial(_run_extract_theses, year=year)))
        if tasks:
            # Les helpers `_run_extract_*` ouvrent chacun leur propre connexion DB
            # et écrivent dans des tables `staging.*` distinctes : aucun état
            # partagé, parallélisme thread-safe. La merge des PhaseMetrics est
            # effectuée séquentiellement dans le thread principal (PhaseMetrics
            # n'est pas thread-safe).
            log.info(
                "▶ extracteurs en parallèle (%d) : %s", len(tasks), ", ".join(n for n, _ in tasks)
            )
            with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
                futures = {pool.submit(_timed_metrics, fn): name for name, fn in tasks}
                for future in as_completed(futures):
                    source_metrics, duration = future.result()
                    metrics.merge(source_metrics)
                    by_source[futures[future]] = _summary(source_metrics, duration)

    if by_source:
        metrics.details["table"] = {
            "rows": [{"key": source, **summary} for source, summary in by_source.items()]
        }
    return metrics


def phase_resolve_ra(**kw: Any) -> PhaseMetrics:
    """Résout la Registration Agency des préfixes DOI (`doi.org/ra`) avant cross_imports.

    Permet à `cross_imports` de router les fetches par RA (Crossref vs DataCite) dès le
    run courant, au lieu de tenter chaque DOI contre les deux APIs (ensembles disjoints).
    Le volet publisher (phase `publishers_journals`) complète ensuite les rows via les
    API `/prefixes`.
    """
    return _run_resolve_ra()


def phase_cross_imports(
    mode: Any = "full", sources: Any = None, include_wos: bool = False, **kw: Any
) -> PhaseMetrics:
    """Rattrapage des documents repérés dans une source mais absents d'une autre.

    Deux mécanismes complémentaires, exécutés dans cet ordre :

    1. **Cross-import par hal-id / NNT** (`fetch_missing_hal_id`).
       Pour chaque hal-id ou NNT mentionné dans une autre source mais
       absent du staging HAL, on télécharge le document via l'API HAL.
       Auto-bornée : les hal-ids/NNT introuvables sont marqués
       `not_found_at` dans staging et ne sont jamais re-interrogés.
       Tourne systématiquement (daily/weekly/full).

    2. **Cross-import par DOI** (`fetch_missing_doi`).
       Pour chaque source cible, on cherche les DOI vus dans les autres
       sources mais absents de la sienne, et on tente de les fetcher.
       WoS est opt-in (`--include-wos`) : source en fin de vie, crédit API
       limité, exclue par défaut. Auto-bornée : les DOI absents d'une source non
       native reçoivent un backoff dans `doi_lookups` (re-tenté après
       `DOI_LOOKUP_RETRY_DAYS`), ceux absents de Crossref (source native) un stub
       `staging` définitif.
    """
    metrics = PhaseMetrics()
    by_channel: dict[str, dict[str, float]] = {}

    def _summary(channel_metrics: PhaseMetrics, duration_s: float) -> dict[str, float]:
        return {
            "interrogated": channel_metrics.total,
            "new": channel_metrics.new,
            "not_found": channel_metrics.extras.get("not_found", 0),
            "duration_s": round(duration_s, 1),
        }

    # Étape 1 : par hal-id / NNT
    if not sources or "hal" in sources:
        hal_metrics, hal_duration = _timed_metrics(partial(_run_fetch_missing_hal_id, mode=mode))
        metrics.merge(hal_metrics)
        by_channel["hal-id / NNT"] = _summary(hal_metrics, hal_duration)

    # Étape 2 : par DOI. WoS opt-in (cf. docstring).
    targets = set(DOI_SEARCHABLE_SOURCES)
    if not include_wos:
        targets -= {"wos"}
    effective = (set(sources) if sources else set(targets)) & targets

    doi_targets = [t for t in DOI_SEARCHABLE_SOURCES if t in effective]
    if doi_targets:
        # Cross-imports par DOI en parallèle (comme les extracteurs) : chaque
        # `_run_fetch_missing_doi` ouvre sa propre connexion, frappe une API
        # distincte et écrit dans le staging de sa source — aucun état partagé.
        # La merge des PhaseMetrics reste séquentielle (non thread-safe).
        # Conséquence assumée : une propagation cross-source d'un DOI fraîchement
        # importé peut glisser au run suivant (phase de rattrapage idempotente et
        # auto-bornée), au lieu de l'ordre séquentiel hal→openalex→…
        log.info(
            "▶ cross-imports par DOI en parallèle (%d) : %s",
            len(doi_targets),
            ", ".join(doi_targets),
        )
        with ThreadPoolExecutor(max_workers=len(doi_targets)) as pool:
            futures = {
                pool.submit(_timed_metrics, partial(_run_fetch_missing_doi, t)): t
                for t in doi_targets
            }
            for future in as_completed(futures):
                channel_metrics, duration = future.result()
                metrics.merge(channel_metrics)
                by_channel[futures[future]] = _summary(channel_metrics, duration)

    if by_channel:
        metrics.details["table"] = {
            "rows": [{"key": channel, **summary} for channel, summary in by_channel.items()]
        }
    return metrics


def phase_refresh_stale(sources: Any = None, include_wos: bool = False, **kw: Any) -> PhaseMetrics:
    """Rafraîchit les rows à `last_seen_at` ancien et marque les disparues.

    Tourne à **chaque run** : le seuil `STALE_REFRESH_AFTER_DAYS` étale la
    charge (chaque passe ne ramasse que ce qui vient de franchir le délai).

    Pour chaque source DOI-queryable (`DOI_SEARCHABLE_SOURCES`),
    refetch des DOI stale → trouvé : bump `last_seen_at` + refresh `raw_data` ;
    404 confirmé : `disappeared_at`. Puis marque disparues les rows stale
    **sans DOI** (non refetchables, mais re-moissonnées par le bulk → rester
    stale signifie disparu). WoS est opt-in (`--include-wos`) : exclu par
    défaut, comme `extract` et `cross_imports`.

    Conservateur : on **marque seulement** (`disappeared_at`), aucun effet
    aval. Placée après `cross_imports` (qui a fini de peupler `staging` et
    `last_seen_at`) et avant `normalize` (qui consomme le `raw_data` rafraîchi).
    """
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.common import mark_undiscoverable_stale_disappeared

    metrics = PhaseMetrics()
    by_source: dict[str, dict[str, float]] = {}
    allowed = set(DOI_SEARCHABLE_SOURCES)
    if not include_wos:
        allowed -= {"wos"}
    effective = (set(sources) if sources else allowed) & allowed
    targets = [t for t in DOI_SEARCHABLE_SOURCES if t in effective]
    for target in targets:
        source_metrics, duration = _timed_metrics(partial(_run_refresh_stale_doi, target))
        metrics.merge(source_metrics)
        by_source[target] = {
            "interrogated": source_metrics.total,
            "refreshed": source_metrics.new,
            # 404 confirmé sur un DOI stale → `disappeared_at` (via marker_handler).
            "disappeared": source_metrics.extras.get("not_found", 0),
            "duration_s": round(duration, 1),
        }

    log.info("▶ refresh_stale : marquage des rows stale sans DOI…")
    conn = get_sync_engine().connect()
    try:
        undiscoverable_by_source = mark_undiscoverable_stale_disappeared(conn)
        conn.commit()
    finally:
        conn.close()
    n_undiscoverable = sum(undiscoverable_by_source.values())
    log.info("✓ refresh_stale : %d rows sans DOI marquées disparues", n_undiscoverable)
    metrics.add(disappeared=n_undiscoverable)

    # Disparitions détectées par staleness (rows sans DOI) : rattachées à leur
    # source, fondues dans la même colonne `disappeared` que les 404 par DOI.
    for source, n in undiscoverable_by_source.items():
        row = by_source.setdefault(
            source, {"interrogated": 0, "refreshed": 0, "disappeared": 0, "duration_s": 0}
        )
        row["disappeared"] += n

    if by_source:
        metrics.details["table"] = {
            "rows": [{"key": source, **summary} for source, summary in by_source.items()]
        }
    return metrics


def phase_refetch_truncated(**kw: Any) -> PhaseMetrics:
    """Re-télécharge les works OpenAlex tronqués à 100 auteurs.

    L'API OpenAlex plafonne la liste des auteurs à 100 par réponse. Cette phase
    repère les lignes staging openalex `processed=FALSE` à 100 auteurs et les
    re-télécharge intégralement (pagination des auteurs).

    Placée après `refresh_stale` (pour capter aussi les works tronqués ramenés
    par `cross_imports` et `refresh_stale`) et avant `normalize` (qui passe les
    lignes à `processed=TRUE`, après quoi elles sont invisibles à la détection).
    """
    sources = kw.get("sources", set(ALL_SOURCES_SET))
    metrics = PhaseMetrics()
    # Toujours actif (incrémental : ne repère que les lignes openalex processed=FALSE
    # à 100 auteurs) ; ne dépend que de la présence d'openalex dans les sources.
    if "openalex" in sources:
        metrics.merge(_run_refetch_truncated())
    return metrics


def phase_normalize(**kw: Any) -> PhaseMetrics:
    """Normalisation staging -> tables sources.

    Écrit les `source_publications` avec `publication_id = NULL` (aucun
    rattachement ici : l'assignation aux publications canoniques est faite plus
    tard par la phase `publications`). Stocke les metadonnees (abstract, keywords,
    topics, biblio, etc.) sur source_publications. Vide le raw_data du staging
    apres traitement. Pour HAL : enrichit les structures et extrait ORCID/IdRef
    depuis le TEI.
    """
    sources = kw.get("sources", set(ALL_SOURCES_SET))
    mode = kw.get("mode", "full")
    policy = MODES[mode]
    # Ordre d'exécution : source la plus autoritative en premier
    # (cf. SOURCE_PRIORITY dans domain/sources.py). Les sources suivantes
    # n'écrasent pas les métadonnées déjà posées par les précédentes
    # lors de `refresh_from_sources`.
    rows: list[dict[str, object]] = []
    if "theses" in sources:
        rows.append(_run_normalize_theses())
    if "crossref" in sources:
        rows.append(_run_normalize_crossref())
    if "datacite" in sources:
        rows.append(_run_normalize_datacite())
    if "scanr" in sources:
        rows.append(_run_normalize_scanr())
    if "hal" in sources:
        rows.append(_run_normalize_hal())
    if "openalex" in sources:
        rows.append(_run_normalize_openalex())
    if "wos" in sources:
        rows.append(_run_normalize_wos())
    # Libérer l'espace TOAST du staging (raw_data vidé après normalisation)
    vacuum_label = "VACUUM FULL" if policy.vacuum_full else "VACUUM"
    log.info("▶ %s staging…", vacuum_label)
    t0_vacuum = time.time()
    _vacuum_staging(full=policy.vacuum_full)
    log.info("✓ %s staging terminé en %.1fs", vacuum_label, time.time() - t0_vacuum)
    metrics = PhaseMetrics()
    metrics.add(total=sum(cast("int", r["processed"]) for r in rows))
    metrics.details["table"] = {"rows": rows}
    return metrics


def _run_recompute_address_pub_count() -> None:
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.repositories.address_linker import recompute_pub_count

    log.info("▶ recompute addresses.pub_count")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        n = recompute_pub_count(conn)
        conn.commit()
    finally:
        conn.close()
    log.info("✓ addresses.pub_count : %d rows mises à jour en %.1fs", n, time.time() - t0)


def _vacuum_staging(full: bool = False) -> Any:
    """VACUUM sur staging. FULL en mode full/monthly, simple sinon.

    `staging.raw_data` est un JSONB potentiellement gros (payload brut
    HAL/OpenAlex/WoS) vidé après normalisation : `VACUUM` simple marque
    l'espace réutilisable mais ne le rend pas à l'OS — la table TOAST
    reste gonflée. `VACUUM FULL` réécrit la table et libère l'espace.
    Lock exclusif sur staging pendant la durée — sans conséquence dans
    le créneau d'exécution du mode `full` (mensuel nocturne, aucun
    autre accès concurrent au staging).
    """
    from sqlalchemy import text

    from infrastructure.db.engine import get_sync_engine

    sql = "VACUUM FULL staging" if full else "VACUUM staging"
    with get_sync_engine().connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(sql))


def phase_publishers_journals(**kw: Any) -> PhaseMetrics:
    """Enrichissement du référentiel `journals`, positionné entre `affiliations`
    et `metadata_correction`. Trois sous-étapes, toutes incrémentales :

    1. `resolve_doi_prefixes` : préfixe DOI → Registration Agency + éditeur
       Crossref / repository DataCite. Ne traite que les préfixes absents de
       `doi_prefixes` (préfixe non résoluble → sentinelle `'unknown'`).
    2. `enrich_journals_from_openalex` : OpenAlex Sources → APC + journal_type.
       Ne traite que les revues à `journal_type='unknown'` (converge à zéro,
       OpenAlex typant ses sources).
    3. `enrich_journals_from_doaj` : dump CSV DOAJ (téléchargé au plus tous les
       ~30 jours dans `data/doaj/`) → `doaj_payload` + `is_in_doaj`. DOAJ fait
       autorité et est seul à poser `is_in_doaj` (reset global puis re-pose des
       TRUE). Ne se déclenche que si le dernier `doaj_imported_at` est null ou
       plus vieux que la fenêtre de stale.

    L'enrichissement des **éditeurs** (pays, ROR, type) est purement cosmétique :
    hors pipeline, lancé à la demande via
    `interfaces/cli/maintenance/enrich_publishers.py`.

    Placée **après normalize** : (a) `cross_imports` (en amont) peut introduire de
    nouveaux DOIs via `fetch_missing_hal_id`, (b) `normalize` crée les
    `publishers`/`journals` qu'on veut enrichir.
    """
    publishers = _run_resolve_publishers()
    openalex = _run_enrich_journals_from_openalex()
    doaj = _run_enrich_journals_from_doaj()

    metrics = PhaseMetrics()
    metrics.details["table"] = {
        "rows": [
            {
                "key": "préfixes DOI → publishers",
                "traités": publishers.total,
                "identifiés": publishers.extras.get("publisher_matched", 0),
                "créés": publishers.extras.get("publisher_created", 0),
            },
            {
                "key": "revues OpenAlex",
                "traités": openalex.total,
                "identifiés": openalex.updated,
                "créés": 0,
            },
        ]
    }
    # DOAJ : ligne à part (sous-étape conditionnelle, métrique propre).
    metrics.details["summary"] = {"doaj_matched": doaj.extras.get("matched", 0)}
    return metrics


def _run_resolve_ra() -> PhaseMetrics:
    from application.pipeline.publishers_journals.resolve_doi_prefixes import run_resolve_ra
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.repositories import doi_prefix_repository
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )
    from infrastructure.sources.config import get_polite_pool_email
    from infrastructure.sources.doi_prefixes.clients import build_user_agent, resolve_ra

    log.info("▶ resolve_ra")
    t0 = time.time()
    conn = get_sync_engine().connect()
    # Circuit-breaker sur doi.org/ra : la ContextVar est lue par le helper HTTP,
    # `run_resolve_ra` consulte `breaker.tripped` pour s'arrêter proprement.
    breaker = SourceCircuitBreaker("doi.org/ra")
    token = set_current_breaker(breaker)
    try:
        user_agent = build_user_agent(get_polite_pool_email(conn))
        metrics = run_resolve_ra(
            log,
            repo=doi_prefix_repository(conn),
            resolve_ra_fn=lambda doi: resolve_ra(doi, user_agent=user_agent),
            breaker=breaker,
        )
        conn.commit()
    finally:
        reset_current_breaker(token)
        conn.close()
    log.info("✓ resolve_ra terminé en %.1fs — %s", time.time() - t0, metrics.as_summary())
    return metrics


def _run_resolve_publishers() -> PhaseMetrics:
    from application.pipeline.publishers_journals.resolve_doi_prefixes import (
        run_resolve_publishers,
    )
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.repositories import doi_prefix_repository, publisher_repository
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )
    from infrastructure.sources.config import get_polite_pool_email
    from infrastructure.sources.doi_prefixes.clients import (
        build_user_agent,
        fetch_crossref_prefix,
        fetch_datacite_prefix,
    )

    log.info("▶ resolve_publishers")
    t0 = time.time()
    conn = get_sync_engine().connect()
    breaker = SourceCircuitBreaker("crossref/datacite prefixes")
    token = set_current_breaker(breaker)
    try:
        user_agent = build_user_agent(get_polite_pool_email(conn))
        metrics = run_resolve_publishers(
            log,
            repo=doi_prefix_repository(conn),
            publisher_repo=publisher_repository(conn),
            fetch_crossref_prefix_fn=lambda prefix: fetch_crossref_prefix(
                prefix, user_agent=user_agent
            ),
            fetch_datacite_prefix_fn=lambda prefix: fetch_datacite_prefix(
                prefix, user_agent=user_agent
            ),
            breaker=breaker,
        )
        conn.commit()
    finally:
        reset_current_breaker(token)
        conn.close()
    log.info("✓ resolve_publishers terminé en %.1fs — %s", time.time() - t0, metrics.as_summary())
    return metrics


def phase_affiliations(**kw: Any) -> PhaseMetrics:
    """Résolution des affiliations UCA sur les source_authorships.

    1. refresh_perimeter_structures : rematérialise le périmètre (clôture des tutelles)
    2. resolve_addresses : matche les adresses vers les structures connues
    3. populate_affiliations : pose in_perimeter sur les source_authorships

    Phase source-agnostique : `--sources` n'est pas propagé. Sinon des
    source_authorships d'une source non listée garderaient un `in_perimeter`
    périmé après la résolution d'une nouvelle adresse.
    """
    _run_refresh_perimeter_structures()
    metrics = _run_resolve_addresses()
    metrics.merge(_run_populate_affiliations())
    return metrics


def phase_metadata_correction(**kw: Any) -> PhaseMetrics:
    """Persistance des corrections de métadonnées sur les source_publications.

    Tourne après `publishers_journals` (journaux typés, donc les règles
    journal-dépendantes ont leurs entrées fraîches) et avant `publications`
    (le matching lit les colonnes corrigées). Trois sous-steps, dans l'ordre :
    journal_by_doi (rattachement du journal manquant par préfixe DOI), puis unaire
    (per-record : mapping + règles de correction), puis cluster (group-by-DOI :
    substitution version→concept DataCite, nullage des DOI erronés ouvrage/chapitre).

    journal_by_doi en premier : le `journal_id` qu'il commit est joint par l'unaire
    (`journal_type` depuis la colonne vivante), de sorte que la reclassification
    `doc_type` journal-dépendante a lieu dans le même run, sans feed-forward.
    """
    journal_by_doi = _run_journal_by_doi()
    unary = _run_correct_metadata_unary()
    cluster = _run_correct_by_cluster()
    metrics = PhaseMetrics()
    metrics.add(
        total=journal_by_doi.examined + unary.examined + cluster.examined,
        updated=journal_by_doi.attached + unary.corrected + cluster.corrected,
    )
    # Chiffres plats : `{mode}_{examined,corrected}`. Le frontend les arrange en
    # matrice (mode × examinées/corrigées) — pur agencement de présentation.
    metrics.details["summary"] = {
        "journal_by_doi_examined": journal_by_doi.examined,
        "journal_by_doi_corrected": journal_by_doi.attached,
        "unary_examined": unary.examined,
        "unary_corrected": unary.corrected,
        "cluster_examined": cluster.examined,
        "cluster_corrected": cluster.corrected,
    }
    counts = list(unary.rule_counts.items()) + list(cluster.case_counts.items())
    counts.sort(key=lambda kc: kc[1], reverse=True)
    metrics.details["table"] = {"rows": [{"key": key, "count": count} for key, count in counts]}
    return metrics


def phase_publications(**kw: Any) -> PhaseMetrics:
    """Assignation des `source_publications` aux publications, en une seule passe.

    `reconcile_components` clusterise le voisinage des SP dirty par composante
    connexe des clés de confirmation (DOI/NNT/hal_id/PMID + token thèse
    `title+year`) et assigne chaque SP au pub-ancre de sa partition `(composante ∩
    DOI)`, dans le respect du cannot-link DOI. Assignation (match/create/skip d'un
    orphelin) et réconciliation (merge/split de publications matérialisées) sont
    des facettes du même primitif — un seul `connected_components`, aucun drift.

    Les passes ad-hoc `merge_pubs_by_*` ont été retirées du pipeline : la
    réconciliation les subsume. La dédup thèse passe par le token de confirmation,
    plus de passe métadonnées dédiée.

    Prerequis : `metadata_correction` (en amont) a substitué en colonne le DOI concept
    des versions DataCite, de sorte que le matching regroupe sur le concept.

    `--rebuild-publications` re-dirtie tout le stock avant la réconciliation : celle-ci
    dégénère alors en cluster-then-materialize global (à lancer après une évolution des
    règles de clés, pour matérialiser les fusions/scissions qu'elles impliquent).
    """
    if kw.get("rebuild_publications"):
        _run_redirty_all_publications()
    metrics = _run_reconcile_components()
    # `addresses.pub_count` compte les publications par adresse : recalcul ici,
    # une fois les publications créées et fusionnées — il n'y a rien à compter
    # au stade `normalize`. Un run `--only publications` suffit à le tenir à jour.
    _run_recompute_address_pub_count()
    return metrics


def phase_relations(**kw: Any) -> PhaseMetrics:
    """Population des relations sémantiques entre publications distinctes.

    Tourne après `publications` : les `source_publications` sont rattachées et les DOI
    cibles résolus en `publication_id`. Reconstruit `publication_relations` depuis les
    relations déclarées par les sources (DataCite `meta.related_identifiers`, Crossref
    `meta.relation`). Les relations même-œuvre (versions, variantes, pièces) relèvent de
    la déduplication (`metadata_correction`), pas d'ici.
    """
    return _run_populate_relations()


def phase_persons(**kw: Any) -> PhaseMetrics:
    """Creation et rattachement des personnes.

    Cree des personnes a partir des source_authorships in_perimeter non rattachees,
    et rattache en complement les authorships hors-perimetre ancrees sur une
    personne connue (identifiant fort partage ou cross-source ; pas de matching
    ni creation par nom). Exclut les publications hors-scope doc_type
    (cf domain/publications/scope).
    """
    metrics = _run_create_persons()
    _run_populate_person_name_forms()
    _run_refresh_person_identifier_keys()
    return metrics


def phase_authorships(**kw: Any) -> Any:
    """Construction de la table de verite authorships.

    Consolide les source_authorships en authorships canoniques
    (une entree par couple publication x personne), avec in_perimeter
    consolide ; les structures derivent de la matview authorship_structures.

    Phase source-agnostique : `--sources` n'est pas propagé. Une
    source_authorship peut etre touchee par d'autres voies que sa propre
    normalisation (re-population d'affiliations, refresh_from_sources,
    etc.) — toutes les sources doivent etre reconsolidees a chaque run.

    Le build est incrémental et convergent dans tous les modes (add +
    prune + recompute des attributs en une passe) : aucune purge routinière.
    La purge complète reste disponible en récupération manuelle via la CLI
    `build_authorships --rebuild-full`.

    `build_authorships` pose `publications.in_perimeter` (rollup) ; on purge
    ensuite les publications restées à zéro authorship (orphelines hors-périmètre,
    cf. `purge_orphan_publications`) puis on rafraîchit les `pub_count` (journals +
    publishers) qui dérivent de `in_perimeter`.
    """
    _run_build_authorships()
    _run_purge_orphan_publications()
    _run_refresh_pub_counts()


def phase_countries(mode: Any = "full", **kw: Any) -> PhaseMetrics:
    """Detection des pays des adresses et recalcul sur les publications."""
    metrics = PhaseMetrics()
    initial = _log_countries_summary("Bilan initial")
    metrics.merge(_run_detect_address_countries())
    metrics.merge(_run_detect_place_countries())
    metrics.merge(
        _run_suggest_address_countries(retry_empty=MODES[mode].retry_empty_country_suggestions)
    )
    _run_refresh_publication_countries()
    final = _log_countries_summary("Bilan final")
    metrics.details["summary"] = {
        "addresses_total": final.total,
        "with_country_before": initial.with_country,
        "with_country_after": final.with_country,
        "with_suggestion": final.with_suggestion,
        "without_country": final.none,
    }
    return metrics


def phase_subjects(**kw: Any) -> Any:
    """Sujets / mots-clés : ingestion + recalcul des co-occurrences.

    Deux étapes enchaînées, indissociables :

    1. **Ingestion** (`subjects` + `publication_subjects`) — incrémentale et
       publication-centrée : ne ré-ingère que les publications dont le contenu
       canonique a changé depuis leur dernière ingestion (`publications.updated_at`
       > `max(publication_subjects.created_at)`), à partir des `keywords` /
       `topics` de leurs `source_publications`. Purge en fin les sujets devenus
       orphelins (plus aucun lien). Cf. `application/pipeline/subjects/run.py`.

    2. **Co-occurrences** (`subjects.usage_count` + matview `subject_cooccurrences`)
       — recalcule l'usage de chaque sujet et rafraîchit la matview des
       paires de sujets co-présents sur une même publication.

    Aucun filtre périmètre ici : la phase `authorships` a purgé en amont les
    publications orphelines (zéro authorship), donc `publication_subjects` ne
    porte plus que du périmètre et `usage_count` / `subject_cooccurrences` en
    héritent. Ne pas re-filtrer (cf. `purge_orphan_publications`).

    Idempotente. Pour forcer une ré-ingestion complète (récupération), vider
    `publication_subjects` non rejetés : toutes les publications redeviennent
    « jamais ingérées ».
    """
    _run_ingest_subjects()
    _run_cooccurrences()


def _run_journal_by_doi() -> JournalByDoiStats:
    from application.pipeline.metadata_correction.journal_by_doi import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.metadata_correction import PgMetadataCorrectionQueries

    log.info("▶ metadata_correction (journal_by_doi)")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        stats = run(conn, PgMetadataCorrectionQueries(), log)
    finally:
        conn.close()
    log.info("✓ metadata_correction (journal_by_doi) terminé en %.1fs", time.time() - t0)
    return stats


def _run_correct_metadata_unary() -> UnaryCorrectionStats:
    from application.pipeline.metadata_correction.correct_unary import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.metadata_correction import PgMetadataCorrectionQueries

    log.info("▶ metadata_correction (unaire)")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        stats = run(conn, PgMetadataCorrectionQueries(), log)
    finally:
        conn.close()
    log.info("✓ metadata_correction (unaire) terminé en %.1fs", time.time() - t0)
    return stats


def _run_correct_by_cluster() -> ClusterCorrectionStats:
    from application.pipeline.metadata_correction.correct_by_cluster import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.metadata_correction import PgMetadataCorrectionQueries

    log.info("▶ metadata_correction (cluster)")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        stats = run(conn, PgMetadataCorrectionQueries(), log)
    finally:
        conn.close()
    log.info("✓ metadata_correction (cluster) terminé en %.1fs", time.time() - t0)
    return stats


def _run_redirty_all_publications() -> None:
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.publications_reconciliation import mark_keys_dirty

    log.info("▶ rebuild publications : re-dirty de tout le stock")
    conn = get_sync_engine().connect()
    try:
        n = mark_keys_dirty(conn)
        conn.commit()
    finally:
        conn.close()
    log.info("✓ %d source_publications marquées keys_dirty (rebuild complet)", n)


def _run_reconcile_components() -> PhaseMetrics:
    from application.pipeline.publications.reconcile_components import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.publications_reconciliation import (
        PgPublicationsReconciliationQueries,
    )
    from infrastructure.repositories import audit_repository, publication_repository

    log.info("▶ reconcile_components")
    t0 = time.time()
    queries = PgPublicationsReconciliationQueries()
    conn = get_sync_engine().connect()
    try:
        stats = run(
            conn,
            queries,
            log,
            pub_repo=publication_repository(conn),
            audit_repo=audit_repository(conn),
        )
        _sp_in_perimeter, pub_total = queries.count_dedup_inputs(conn)
    finally:
        conn.close()
    log.info("✓ reconcile_components terminé en %.1fs", time.time() - t0)

    metrics = PhaseMetrics()
    metrics.add(total=stats.processed if stats else 0, new=stats.created if stats else 0)
    # Chiffres du run (SP dirty examinées → publications d'arrivée, mouvements) + le
    # total global des publications (`pub_total`) en « nouveau total ». Le frontend
    # les compose en lignes de texte ; les volumes avant/après auto sont masqués.
    metrics.details["summary"] = {
        "processed": stats.processed if stats else 0,
        "publications": stats.publications if stats else 0,
        "existing": stats.existing if stats else 0,
        "created": stats.created if stats else 0,
        "splits": stats.splits if stats else 0,
        "merges": stats.merges if stats else 0,
        "pub_total": pub_total,
    }
    return metrics


def _run_populate_relations() -> PhaseMetrics:
    from application.pipeline.relations.populate_relations import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.relations import PgPublicationRelationsQueries

    log.info("▶ populate_relations")
    t0 = time.time()
    queries = PgPublicationRelationsQueries()
    conn = get_sync_engine().connect()
    try:
        run(conn, queries, log)
        by_type = queries.count_by_relation_type(conn)
    finally:
        conn.close()
    log.info("✓ populate_relations terminé en %.1fs", time.time() - t0)
    metrics = PhaseMetrics()
    metrics.details["table"] = {
        "rows": [{"key": relation_type, "count": count} for relation_type, count in by_type]
    }
    return metrics


def _run_create_persons() -> PhaseMetrics:
    from application.pipeline.persons.create_persons_from_source_authorships import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.persons_create import PgPersonsCreateQueries
    from infrastructure.repositories import person_repository

    log.info("▶ create_persons_from_source_authorships")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        metrics = run(
            conn,
            PgPersonsCreateQueries(),
            log,
            person_repo=person_repository(conn),
        )
        conn.commit()
    finally:
        conn.close()
    log.info("✓ create_persons_from_source_authorships terminé en %.1fs", time.time() - t0)
    return metrics


def _run_build_authorships() -> None:
    from application.pipeline.authorships.build_authorships import build
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.authorships_build import PgAuthorshipsBuildQueries

    log.info("▶ build_authorships")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        build(conn, PgAuthorshipsBuildQueries(), log)
        conn.commit()
    finally:
        conn.close()
    log.info("✓ build_authorships terminé en %.1fs", time.time() - t0)


# Taille de chunk du DELETE de purge : un commit par chunk étale le WAL et rend
# la progression durable si le run est interrompu (le premier run, ou un full
# rebuild, peut supprimer ~118k publications d'un coup).
_PURGE_BATCH_SIZE = 5000


def _run_purge_orphan_publications() -> None:
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.purge_orphan_publications import (
        purge_orphan_publications,
        vacuum_analyze_churned,
    )

    log.info("▶ purge publications orphelines (zéro authorship)")
    t0 = time.time()
    conn = get_sync_engine().connect()
    n = 0
    try:
        while True:
            deleted = purge_orphan_publications(conn, limit=_PURGE_BATCH_SIZE)
            if deleted == 0:
                break
            conn.commit()
            n += deleted
    finally:
        conn.close()
    # VACUUM hors transaction (autocommit) : récupère l'espace des tuples morts
    # pour réutilisation au run suivant (pas de FULL — cf. module).
    vac = get_sync_engine().connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        vacuum_analyze_churned(vac)
    finally:
        vac.close()
    log.info(
        "✓ purge : %d publication(s) supprimée(s) + VACUUM ANALYZE en %.1fs",
        n,
        time.time() - t0,
    )


def _run_refresh_pub_counts() -> None:
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.pub_counts import refresh_pub_counts

    log.info("▶ refresh pub_count (journals + publishers)")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        n_journals, n_publishers = refresh_pub_counts(conn)
        conn.commit()
    finally:
        conn.close()
    log.info(
        "✓ pub_count : %d revues, %d éditeurs mis à jour en %.1fs",
        n_journals,
        n_publishers,
        time.time() - t0,
    )


def _run_refresh_perimeter_structures() -> None:
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.perimeter import refresh_perimeter_structures

    log.info("▶ refresh perimeter_structures")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        n = refresh_perimeter_structures(conn)
        conn.commit()
    finally:
        conn.close()
    log.info("✓ perimeter_structures : %d liens en %.1fs", n, time.time() - t0)


def _run_populate_affiliations() -> PhaseMetrics:
    from application.pipeline.affiliations.populate_affiliations import run_populate
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.perimeter import get_persons_structure_ids
    from infrastructure.queries.pipeline.affiliations import PgAffiliationsQueries

    log.info("▶ populate_affiliations")
    t0 = time.time()
    queries = PgAffiliationsQueries()
    conn = get_sync_engine().connect()
    rows: list[dict[str, object]] = []
    try:
        perimeter_ids = get_persons_structure_ids(conn)
        run_populate(conn, queries, log, perimeter_ids)
        conn.commit()
        # Bilan in_perimeter par source, une fois la propagation committée.
        for source in ("hal", "openalex", "wos", "scanr", "theses"):
            total, in_perimeter = queries.count_source_authorships_stats(conn, source)
            pct = round(100 * in_perimeter / total, 1) if total else 0.0
            rows.append({"key": source, "total": total, "in_perimeter": in_perimeter, "pct": pct})
    finally:
        conn.close()
    log.info("✓ populate_affiliations terminé en %.1fs", time.time() - t0)
    metrics = PhaseMetrics()
    metrics.details["table"] = {"rows": rows}
    return metrics


def _run_refresh_person_identifier_keys() -> None:
    """Rafraîchit la matview `person_identifier_keys` (substrat de la file « conflits
    d'identifiant » du hub admin). En CONCURRENTLY (index unique sur la clé) : pas de verrou
    exclusif. Hors transaction, donc connexion en autocommit."""
    from sqlalchemy import text

    from infrastructure.db.engine import get_sync_engine

    log.info("▶ refresh person_identifier_keys")
    t0 = time.time()
    with get_sync_engine().connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY person_identifier_keys"))
    log.info("✓ person_identifier_keys rafraîchie en %.1fs", time.time() - t0)


def _run_populate_person_name_forms() -> None:
    from application.pipeline.persons.populate_person_name_forms import populate
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.name_forms import PgNameFormsQueries

    log.info("▶ populate_person_name_forms")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        populate(conn, PgNameFormsQueries(), log)
    finally:
        conn.close()
    log.info("✓ populate_person_name_forms terminé en %.1fs", time.time() - t0)


def _normalize_row(source: str, stats: NormalizeStats, duration_s: float) -> dict[str, object]:
    """Ligne « par source » de la table d'observabilité de la phase normalize."""
    return {
        "key": source,
        "processed": stats.processed,
        "skipped": stats.skipped,
        "errors": stats.errors,
        "duration_s": round(duration_s, 1),
    }


def _run_normalize_hal() -> dict[str, object]:
    from application.pipeline.normalize.normalize_hal import HalNormalizer
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.normalize.authorships import PgAuthorshipsBatchQueries
    from infrastructure.queries.pipeline.normalize.hal import PgHalNormalizeQueries
    from infrastructure.queries.pipeline.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )

    log.info("▶ normalize_hal")
    t0 = time.time()
    conn = get_sync_engine().connect()
    stats = HalNormalizer(
        conn,
        log,
        PgStagingQueries(),
        PgHalNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
        authorship_queries=PgAuthorshipsBatchQueries(),
    ).run([])
    duration = time.time() - t0
    log.info("✓ normalize_hal terminé en %.1fs", duration)
    return _normalize_row("hal", stats, duration)


def _run_normalize_wos() -> dict[str, object]:
    from application.pipeline.normalize.normalize_wos import WosNormalizer
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.normalize.authorships import PgAuthorshipsBatchQueries
    from infrastructure.queries.pipeline.normalize.wos import PgWosNormalizeQueries
    from infrastructure.queries.pipeline.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )

    log.info("▶ normalize_wos")
    t0 = time.time()
    conn = get_sync_engine().connect()
    stats = WosNormalizer(
        conn,
        log,
        PgStagingQueries(),
        PgWosNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
        authorship_queries=PgAuthorshipsBatchQueries(),
    ).run([])
    duration = time.time() - t0
    log.info("✓ normalize_wos terminé en %.1fs", duration)
    return _normalize_row("wos", stats, duration)


def _run_normalize_openalex() -> dict[str, object]:
    from application.pipeline.normalize.normalize_openalex import OpenalexNormalizer
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.normalize.authorships import PgAuthorshipsBatchQueries
    from infrastructure.queries.pipeline.normalize.openalex import PgOpenalexNormalizeQueries
    from infrastructure.queries.pipeline.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )

    log.info("▶ normalize_openalex")
    t0 = time.time()
    conn = get_sync_engine().connect()
    stats = OpenalexNormalizer(
        conn,
        log,
        PgStagingQueries(),
        PgOpenalexNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
        authorship_queries=PgAuthorshipsBatchQueries(),
    ).run([])
    duration = time.time() - t0
    log.info("✓ normalize_openalex terminé en %.1fs", duration)
    return _normalize_row("openalex", stats, duration)


def _run_normalize_scanr() -> dict[str, object]:
    from application.pipeline.normalize.normalize_scanr import ScanrNormalizer
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.normalize.authorships import PgAuthorshipsBatchQueries
    from infrastructure.queries.pipeline.normalize.scanr import PgScanrNormalizeQueries
    from infrastructure.queries.pipeline.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )

    log.info("▶ normalize_scanr")
    t0 = time.time()
    conn = get_sync_engine().connect()
    stats = ScanrNormalizer(
        conn,
        log,
        PgStagingQueries(),
        PgScanrNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
        authorship_queries=PgAuthorshipsBatchQueries(),
    ).run([])
    duration = time.time() - t0
    log.info("✓ normalize_scanr terminé en %.1fs", duration)
    return _normalize_row("scanr", stats, duration)


def _run_normalize_theses() -> dict[str, object]:
    from application.pipeline.normalize.normalize_theses import ThesesNormalizer
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.normalize.theses import PgThesesNormalizeQueries
    from infrastructure.queries.pipeline.staging import PgStagingQueries
    from infrastructure.repositories import publication_repository
    from infrastructure.repositories.address_linker import PgAddressLinker

    log.info("▶ normalize_theses")
    t0 = time.time()
    conn = get_sync_engine().connect()
    stats = ThesesNormalizer(
        conn,
        log,
        PgStagingQueries(),
        PgThesesNormalizeQueries(),
        pub_repo_factory=publication_repository,
        address_linker=PgAddressLinker(),
    ).run([])
    duration = time.time() - t0
    log.info("✓ normalize_theses terminé en %.1fs", duration)
    return _normalize_row("theses", stats, duration)


def _run_normalize_crossref() -> dict[str, object]:
    from application.pipeline.normalize.normalize_crossref import CrossrefNormalizer
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.normalize.authorships import PgAuthorshipsBatchQueries
    from infrastructure.queries.pipeline.normalize.crossref import PgCrossrefNormalizeQueries
    from infrastructure.queries.pipeline.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )

    log.info("▶ normalize_crossref")
    t0 = time.time()
    conn = get_sync_engine().connect()
    stats = CrossrefNormalizer(
        conn,
        log,
        PgStagingQueries(),
        PgCrossrefNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
        authorship_queries=PgAuthorshipsBatchQueries(),
    ).run([])
    duration = time.time() - t0
    log.info("✓ normalize_crossref terminé en %.1fs", duration)
    return _normalize_row("crossref", stats, duration)


def _run_normalize_datacite() -> dict[str, object]:
    from application.pipeline.normalize.normalize_datacite import DataciteNormalizer
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.normalize.authorships import PgAuthorshipsBatchQueries
    from infrastructure.queries.pipeline.normalize.datacite import PgDataciteNormalizeQueries
    from infrastructure.queries.pipeline.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )

    log.info("▶ normalize_datacite")
    t0 = time.time()
    conn = get_sync_engine().connect()
    stats = DataciteNormalizer(
        conn,
        log,
        PgStagingQueries(),
        PgDataciteNormalizeQueries(),
        journal_repo_factory=journal_repository,
        publisher_repo_factory=publisher_repository,
        pub_repo_factory=publication_repository,
        authorship_queries=PgAuthorshipsBatchQueries(),
    ).run([])
    duration = time.time() - t0
    log.info("✓ normalize_datacite terminé en %.1fs", duration)
    return _normalize_row("datacite", stats, duration)


def _run_enrich_oa_status() -> PhaseMetrics:
    import asyncio

    import httpx

    from application.pipeline.oa_status.run import run_enrich_oa_status
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.enrich import PgEnrichQueries
    from infrastructure.repositories import publication_repository
    from infrastructure.sources.config import get_api_base_urls, get_polite_pool_email
    from infrastructure.sources.unpaywall import fetch_oa_status

    log.info("▶ enrich_oa_status")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        base_url = get_api_base_urls()["unpaywall"]
        email = get_polite_pool_email(conn)

        async def fetcher(client: httpx.AsyncClient, doi: str) -> str | None:
            return await fetch_oa_status(client, doi, base_url=base_url, email=email, logger=log)

        metrics = asyncio.run(
            run_enrich_oa_status(
                conn,
                PgEnrichQueries(),
                log,
                pub_repo=publication_repository(conn),
                fetcher=fetcher,
            )
        )
    finally:
        conn.close()
    log.info("✓ enrich_oa_status terminé en %.1fs", time.time() - t0)
    return metrics


def _run_enrich_journals_from_openalex() -> PhaseMetrics:
    from application.pipeline.publishers_journals.enrich_journals_from_openalex import (
        run_enrich_journals_from_openalex,
    )
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.enrich import PgEnrichQueries
    from infrastructure.repositories import journal_repository
    from infrastructure.sources.api_limits import DOAJ_DELAY
    from infrastructure.sources.config import (
        get_api_base_urls,
        get_openalex_api_key,
        get_polite_pool_email,
    )

    log.info("▶ enrich_journals_from_openalex")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        metrics = run_enrich_journals_from_openalex(
            conn,
            PgEnrichQueries(),
            log,
            journal_repo=journal_repository(conn),
            api_key=get_openalex_api_key(conn),
            mailto=get_polite_pool_email(conn),
            openalex_sources_api=get_api_base_urls()["openalex_sources"],
            rate_delay=DOAJ_DELAY,
        )
    finally:
        conn.close()
    log.info("✓ enrich_journals_from_openalex terminé en %.1fs", time.time() - t0)
    return metrics


# DOAJ : le dump CSV (source de vérité) est ré-importé au plus une fois tous les
# N jours (DOAJ publie ~hebdo) ; le dump téléchargé est conservé dans data/doaj/.
_DOAJ_STALE_DAYS = 30
_DOAJ_DUMP_PATH = Path(__file__).parent / "data" / "doaj" / "doaj_dump.csv"


def _run_enrich_journals_from_doaj() -> PhaseMetrics:
    from application.pipeline.publishers_journals.import_journals_from_doaj_dump import (
        run_import_doaj_dump,
    )
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.enrich import PgEnrichQueries
    from infrastructure.repositories import journal_repository
    from infrastructure.sources.config import get_polite_pool_email
    from infrastructure.sources.doaj import (
        build_doaj_user_agent,
        fetch_doaj_dump,
        read_doaj_dump_rows,
    )

    log.info("▶ enrich_journals_from_doaj")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        queries = PgEnrichQueries()
        last = queries.doaj_last_import_at(conn)
        threshold = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=_DOAJ_STALE_DAYS)
        if last is not None and last > threshold:
            log.info(
                "✓ enrich_journals_from_doaj : dump importé il y a < %d jours (%s), skip",
                _DOAJ_STALE_DAYS,
                last.date(),
            )
            return PhaseMetrics(extras={"skipped": 1})

        _DOAJ_DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)
        user_agent = build_doaj_user_agent(get_polite_pool_email(conn))
        fetch_doaj_dump(str(_DOAJ_DUMP_PATH), user_agent=user_agent, logger=log)
        stats = run_import_doaj_dump(
            conn,
            queries,
            log,
            journal_repo=journal_repository(conn),
            rows=read_doaj_dump_rows(str(_DOAJ_DUMP_PATH)),
        )
    finally:
        conn.close()
    log.info("✓ enrich_journals_from_doaj terminé en %.1fs", time.time() - t0)
    return PhaseMetrics(extras={"matched": stats.matched})


def _run_resolve_addresses() -> PhaseMetrics:
    from application.pipeline.affiliations.resolve_addresses import run_resolution
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.perimeter import get_persons_structure_ids
    from infrastructure.queries.pipeline.address_resolution import PgAddressResolutionQueries

    log.info("▶ resolve_addresses")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        perimeter_ids = get_persons_structure_ids(conn)
        processed, in_perimeter, _affil = run_resolution(
            conn, PgAddressResolutionQueries(), perimeter_ids, log
        )
    finally:
        conn.close()
    log.info("✓ resolve_addresses terminé en %.1fs", time.time() - t0)
    metrics = PhaseMetrics()
    metrics.details["summary"] = {"adresses": processed, "in_perimeter": in_perimeter}
    return metrics


def _run_refresh_publication_countries() -> None:
    from application.pipeline.countries.refresh_publication_countries import refresh
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.countries import PgCountryQueries

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
    from infrastructure.queries.subjects import PgSubjectsQueries

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
    from infrastructure.queries.subjects import PgSubjectsQueries

    log.info("▶ cooccurrences")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        run(conn, PgSubjectsQueries(), log)
        conn.commit()
    finally:
        conn.close()
    log.info("✓ cooccurrences terminé en %.1fs", time.time() - t0)


# ── Extracteurs sources (Volet 0 — sweep subprocess → imports) ──


def _extractor_args(
    *, start_year: int | None = None, year: int | None = None, since: str | None = None
) -> argparse.Namespace:
    """Construit le Namespace `args` consommé par `SourceExtractor.run_as_phase`.

    Les extracteurs lisent `dry_run, start_year, year, since`. HAL et OpenAlex
    exploitent `since` (incrémental) ; theses ignore `start_year` (ramène tout
    l'historique des PPN).
    """
    return argparse.Namespace(dry_run=False, start_year=start_year, year=year, since=since)


def _run_extractor(extractor: Any, args: Any) -> PhaseMetrics:
    """Exécute un extracteur avec un circuit-breaker de source (seuil 5).

    Pose le breaker dans la ContextVar (lu par le helper HTTP sync) et le passe à
    `run_as_phase` (consulté par les boucles `extract_all` pour stopper une source
    à bout de budget). Seuil 5 : extracteurs séquentiels, pas de batch concurrent
    comme le cross-import (qui est à 10).
    """
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )

    breaker = SourceCircuitBreaker(extractor.SOURCE, threshold=5)
    token = set_current_breaker(breaker)
    try:
        return extractor.run_as_phase(args, breaker=breaker)
    finally:
        reset_current_breaker(token)


def _run_extract_hal(
    *, start_year: int | None = None, year: int | None = None, since: str | None = None
) -> PhaseMetrics:
    from application.pipeline.extract.extract_hal import HalExtractor
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.config import get_api_base_urls
    from infrastructure.sources.hal.extract_hal import PgHalExtractAdapter

    log.info("▶ extract_hal")
    t0 = time.time()
    source_log = setup_logger("hal", str(BASE / "logs"))
    engine = get_sync_engine()
    hal_url = get_api_base_urls()["hal"]
    conn = engine.connect()
    adapter = PgHalExtractAdapter(base_url=hal_url)
    try:
        metrics = _run_extractor(
            HalExtractor(conn, source_log, adapter),
            _extractor_args(start_year=start_year, year=year, since=since),
        )
    finally:
        conn.close()
    log.info("✓ extract_hal terminé en %.1fs — %s", time.time() - t0, metrics.as_summary())
    return metrics


def _run_extract_openalex(
    *, start_year: int | None = None, year: int | None = None, since: str | None = None
) -> PhaseMetrics:
    from application.pipeline.extract.extract_openalex import OpenalexExtractor
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.config import get_api_base_urls
    from infrastructure.sources.openalex.extract_openalex import PgOpenalexExtractAdapter

    log.info("▶ extract_openalex")
    t0 = time.time()
    source_log = setup_logger("openalex", str(BASE / "logs"))
    engine = get_sync_engine()
    base_url = get_api_base_urls()["openalex"]
    conn = engine.connect()
    adapter = PgOpenalexExtractAdapter(base_url=base_url)
    try:
        metrics = _run_extractor(
            OpenalexExtractor(conn, source_log, adapter),
            _extractor_args(start_year=start_year, year=year, since=since),
        )
    finally:
        conn.close()
    log.info("✓ extract_openalex terminé en %.1fs — %s", time.time() - t0, metrics.as_summary())
    return metrics


def _run_extract_wos(*, start_year: int | None = None, year: int | None = None) -> PhaseMetrics:
    from application.pipeline.extract.extract_wos import WosExtractor
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.config import get_api_base_urls, get_wos_api_key
    from infrastructure.sources.wos.extract_wos import PgWosExtractAdapter

    log.info("▶ extract_wos")
    t0 = time.time()
    source_log = setup_logger("wos", str(BASE / "logs"))
    engine = get_sync_engine()
    with engine.connect() as bootstrap:
        base_url = get_api_base_urls()["wos"]
        api_key = get_wos_api_key(bootstrap)
    conn = engine.connect()
    adapter = PgWosExtractAdapter(base_url=base_url, api_key=api_key)
    try:
        metrics = _run_extractor(
            WosExtractor(conn, source_log, adapter),
            _extractor_args(start_year=start_year, year=year),
        )
    finally:
        conn.close()
    log.info("✓ extract_wos terminé en %.1fs — %s", time.time() - t0, metrics.as_summary())
    return metrics


def _run_extract_scanr(*, start_year: int | None = None, year: int | None = None) -> PhaseMetrics:
    from application.pipeline.extract.extract_scanr import ScanrExtractor
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.config import get_api_base_urls
    from infrastructure.sources.scanr.extract_scanr import (
        PgScanrExtractAdapter,
        get_scanr_credentials_from_db,
    )

    log.info("▶ extract_scanr")
    t0 = time.time()
    source_log = setup_logger("scanr", str(BASE / "logs"))
    engine = get_sync_engine()
    with engine.connect() as bootstrap:
        base_url = get_api_base_urls()["scanr"]
        credentials = get_scanr_credentials_from_db(bootstrap)
    conn = engine.connect()
    adapter = PgScanrExtractAdapter(base_url=base_url, credentials=credentials)
    try:
        metrics = _run_extractor(
            ScanrExtractor(conn, source_log, adapter),
            _extractor_args(start_year=start_year, year=year),
        )
    finally:
        conn.close()
    log.info("✓ extract_scanr terminé en %.1fs — %s", time.time() - t0, metrics.as_summary())
    return metrics


def _run_extract_theses(*, year: int | None = None) -> PhaseMetrics:
    from application.pipeline.extract.extract_theses import ThesesExtractor
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.config import get_api_base_urls
    from infrastructure.sources.theses.extract_theses import PgThesesExtractAdapter

    log.info("▶ extract_theses")
    t0 = time.time()
    source_log = setup_logger("theses", str(BASE / "logs"))
    engine = get_sync_engine()
    base_url = get_api_base_urls()["theses"]
    conn = engine.connect()
    adapter = PgThesesExtractAdapter(base_url=base_url)
    try:
        metrics = _run_extractor(
            ThesesExtractor(conn, source_log, adapter),
            _extractor_args(year=year),
        )
    finally:
        conn.close()
    log.info("✓ extract_theses terminé en %.1fs — %s", time.time() - t0, metrics.as_summary())
    return metrics


def _run_refetch_truncated() -> PhaseMetrics:
    import asyncio

    from application.pipeline.extract.refetch_truncated import refetch
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.openalex.refetch_truncated import PgOpenalexRefetchAdapter

    log.info("▶ refetch_truncated")
    t0 = time.time()
    conn = get_sync_engine().connect()
    adapter = PgOpenalexRefetchAdapter()
    try:
        metrics = asyncio.run(refetch(conn, adapter, log))
    finally:
        conn.close()
    log.info("✓ refetch_truncated terminé en %.1fs — %s", time.time() - t0, metrics.as_summary())
    return metrics


def _run_fetch_missing_hal_id(*, mode: str = "full") -> PhaseMetrics:
    from application.pipeline.extract.fetch_missing_hal_id import fetch_missing_hal_ids
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.hal.fetch_missing_hal_id import PgHalFetchMissingAdapter

    log.info("▶ fetch_missing_hal_id --mode %s", mode)
    t0 = time.time()
    conn = get_sync_engine().connect()
    adapter = PgHalFetchMissingAdapter()
    try:
        metrics = asyncio.run(fetch_missing_hal_ids(conn, adapter, log, mode=mode))
    finally:
        conn.close()
    log.info(
        "✓ fetch_missing_hal_id terminé en %.1fs — %s",
        time.time() - t0,
        metrics.as_summary(),
    )
    return metrics


def _make_fetch_missing_doi_adapter(target: str) -> "AsyncFetchMissingDoiAdapter":
    """Construit l'adapter `fetch_missing_doi` d'une source cible.

    Partagé par le cross-import (`_run_fetch_missing_doi`) et le refresh
    (`_run_refresh_stale_doi`), qui consomment les mêmes adapters.
    """
    from typing import cast

    from application.ports.pipeline.extract.fetch_missing_doi import (
        AsyncFetchMissingDoiAdapter,
    )
    from infrastructure.sources.crossref.fetch_missing_doi import CrossrefFetchMissingDoiAdapter
    from infrastructure.sources.datacite.fetch_missing_doi import DataciteFetchMissingDoiAdapter
    from infrastructure.sources.hal.fetch_missing_doi import HalFetchMissingDoiAdapter
    from infrastructure.sources.openalex.fetch_missing_doi import OpenalexFetchMissingDoiAdapter
    from infrastructure.sources.scanr.fetch_missing_doi import ScanrFetchMissingDoiAdapter
    from infrastructure.sources.wos.fetch_missing_doi import WosFetchMissingDoiAdapter

    # Cast : mypy ne reconnaît pas la conformité structurelle d'une classe
    # concrète à un Protocol via `type[Protocol]` (cf. même pattern dans
    # interfaces/cli/pipeline/fetch_missing_doi.py).
    adapter_classes: dict[str, type[AsyncFetchMissingDoiAdapter]] = cast(
        "dict[str, type[AsyncFetchMissingDoiAdapter]]",
        {
            "hal": HalFetchMissingDoiAdapter,
            "openalex": OpenalexFetchMissingDoiAdapter,
            "wos": WosFetchMissingDoiAdapter,
            "scanr": ScanrFetchMissingDoiAdapter,
            "crossref": CrossrefFetchMissingDoiAdapter,
            "datacite": DataciteFetchMissingDoiAdapter,
        },
    )
    return adapter_classes[target]()


def _run_fetch_missing_doi(target: str) -> PhaseMetrics:
    from application.pipeline.extract.fetch_missing_doi import run_async
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )
    from infrastructure.sources.common import get_cross_import_dois

    adapter = _make_fetch_missing_doi_adapter(target)

    log.info("▶ fetch_missing_doi --target %s", target)
    t0 = time.time()
    conn = get_sync_engine().connect()
    # Circuit-breaker par source : la ContextVar est posée ici (composition root) ;
    # le helper HTTP infra la lit, run_async ne consulte que `breaker.tripped`.
    breaker = SourceCircuitBreaker(target)
    token = set_current_breaker(breaker)
    try:
        metrics = asyncio.run(
            run_async(
                conn,
                adapter,
                log,
                cross_import_dois_reader=get_cross_import_dois,
                breaker=breaker,
            )
        )
    finally:
        reset_current_breaker(token)
        conn.close()
    log.info(
        "✓ fetch_missing_doi (%s) terminé en %.1fs — %s",
        target,
        time.time() - t0,
        metrics.as_summary(),
    )
    return metrics


def _run_refresh_stale_doi(target: str) -> PhaseMetrics:
    """Refetch des DOI stale d'une source : trouvé → bump, 404 → disappeared_at."""
    from application.pipeline.extract.fetch_missing_doi import run_async
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )
    from infrastructure.sources.common import get_stale_dois, set_disappeared_by_doi

    adapter = _make_fetch_missing_doi_adapter(target)

    def _mark_disappeared(conn: Any, doi: str) -> None:
        set_disappeared_by_doi(conn, target, doi)
        conn.commit()

    log.info("▶ refresh_stale --target %s", target)
    t0 = time.time()
    conn = get_sync_engine().connect()
    # Circuit-breaker par source (cf. `_run_fetch_missing_doi`) : coupe le refetch
    # d'une source à bout de budget (429 répétés) au lieu de la marteler. La
    # ContextVar est posée ici, le helper HTTP infra la lit, run_async ne consulte
    # que `breaker.tripped`.
    breaker = SourceCircuitBreaker(target)
    token = set_current_breaker(breaker)
    try:
        metrics = asyncio.run(
            run_async(
                conn,
                adapter,
                log,
                cross_import_dois_reader=get_stale_dois,
                marker_handler=_mark_disappeared,
                breaker=breaker,
            )
        )
    finally:
        reset_current_breaker(token)
        conn.close()
    log.info(
        "✓ refresh_stale (%s) terminé en %.1fs — %s",
        target,
        time.time() - t0,
        metrics.as_summary(),
    )
    return metrics


def _run_detect_address_countries() -> PhaseMetrics:
    from infrastructure.db.engine import get_sync_engine
    from interfaces.cli.pipeline.detect_address_countries import detect_countries

    log.info("▶ detect_address_countries --direct --apply")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        metrics = detect_countries(conn, apply=True, direct=True)
    finally:
        conn.close()
    log.info(
        "✓ detect_address_countries terminé en %.1fs — %s",
        time.time() - t0,
        metrics.as_summary(),
    )
    return metrics


def _log_countries_summary(label: str) -> "AddressCountryStatus":
    """Bilan global de l'état pays des adresses, en début et fin de phase countries."""
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.countries import count_address_country_status

    conn = get_sync_engine().connect()
    try:
        s = count_address_country_status(conn)
    finally:
        conn.close()
    log.info(
        "%s — adresses (pub_count > 0) : %d total | %d avec pays | %d avec suggestion | %d sans rien",
        label,
        s.total,
        s.with_country,
        s.with_suggestion,
        s.none,
    )
    return s


def _run_detect_place_countries() -> PhaseMetrics:
    from infrastructure.db.engine import get_sync_engine
    from interfaces.cli.pipeline.detect_place_countries import detect_place_countries

    log.info("▶ detect_place_countries")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        metrics = detect_place_countries(conn, direct=True)
    finally:
        conn.close()
    log.info(
        "✓ detect_place_countries terminé en %.1fs — %s",
        time.time() - t0,
        metrics.as_summary(),
    )
    return metrics


def _run_suggest_address_countries(*, retry_empty: bool = False) -> PhaseMetrics:
    from infrastructure.db.engine import get_sync_engine
    from interfaces.cli.pipeline.suggest_address_countries import suggest_countries

    log.info("▶ suggest_address_countries%s", " (retry-vides)" if retry_empty else "")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        metrics = suggest_countries(conn, retry_empty=retry_empty)
    finally:
        conn.close()
    log.info(
        "✓ suggest_address_countries terminé en %.1fs — %s",
        time.time() - t0,
        metrics.as_summary(),
    )
    return metrics


def phase_oa_status(**kw: Any) -> PhaseMetrics:
    """Enrichissement `publications.oa_status` via Unpaywall (per-publication).

    Incrémentale et auto-bornée (staleness + cap `MAX_PER_RUN`) : le backlog des
    jamais-vérifiées s'écoule run après run. Tourne dans tous les modes.
    """
    return _run_enrich_oa_status()


# Registre des phases : l'implémentation de chacune. L'ordre d'exécution vient du
# graphe des phases (`PHASE_ORDER`), source de vérité unique ; ce registre ne fournit
# que les fonctions, validées comme couvrant exactement le graphe.
_PHASE_FUNCTIONS: dict[str, Callable[..., PhaseMetrics]] = {
    "extract": phase_extract,
    "resolve_ra": phase_resolve_ra,
    "cross_imports": phase_cross_imports,
    "refresh_stale": phase_refresh_stale,
    "refetch_truncated": phase_refetch_truncated,
    "normalize": phase_normalize,
    "affiliations": phase_affiliations,
    "publishers_journals": phase_publishers_journals,
    "metadata_correction": phase_metadata_correction,
    "publications": phase_publications,
    "relations": phase_relations,
    "persons": phase_persons,
    "authorships": phase_authorships,
    "countries": phase_countries,
    "subjects": phase_subjects,
    "oa_status": phase_oa_status,
}

if set(_PHASE_FUNCTIONS) != set(PHASE_ORDER):
    raise RuntimeError(
        "Le registre des phases de l'orchestrateur et le graphe des phases divergent : "
        f"{set(_PHASE_FUNCTIONS) ^ set(PHASE_ORDER)}"
    )

PHASES: list[tuple[str, Callable[..., PhaseMetrics]]] = [
    (name, _PHASE_FUNCTIONS[name]) for name in PHASE_ORDER
]

PHASE_NAMES = list(PHASE_ORDER)


# ---------------------------------------------------------------------------
# Helpers d'exécution
# ---------------------------------------------------------------------------


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


def main() -> None:  # noqa: C901 — orchestrateur CLI : refactor en helpers séparé du scope actuel
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
        "--start-year",
        type=int,
        help="Année de début du range d'extraction (mode full ; défaut: config "
        "pipeline_start_year_full)",
    )
    parser.add_argument(
        "--include-wos",
        action="store_true",
        help="Inclure WoS dans l'extraction et le cross-import (opt-in : source en fin de vie, "
        "crédit API limité ; exclue par défaut).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Tuer un éventuel pipeline déjà en cours avant de démarrer (SIGTERM puis SIGKILL).",
    )
    parser.add_argument(
        "--rebuild-publications",
        action="store_true",
        help="Avant la phase publications, re-dirtie tout le stock (rebuild complet : "
        "cluster-then-materialize global). À utiliser après une évolution des règles de clés.",
    )
    args = parser.parse_args()

    if args.list:
        print("Phases disponibles :")
        for i, (name, fn) in enumerate(PHASES, 1):
            doc = fn.__doc__.strip().split("\n")[0] if fn.__doc__ else ""
            print(f"  {i}. {name:15s} — {doc}")
        return

    # Mutex pipeline (évite deadlocks cron vs lancement manuel).
    try:
        acquire_pipeline_lock(force=args.force)
    except PipelineAlreadyRunningError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

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
    # Sources effectivement interrogées : wos est opt-in (`--include-wos`).
    effective_sources = sorted(sources - {"wos"}) if not args.include_wos else sorted(sources)
    log.info("Sources : %s", ", ".join(effective_sources))

    # Métriques pipeline
    from infrastructure.observability.phase_executions import start_run

    phase_results = []  # [(name, duration)] — pour le récapitulatif de fin

    # Observabilité par phase : run_id de séquence, capture entrée/sortie + statut.
    recorder = start_run(mode=args.mode, sources=effective_sources)
    if recorder.run_id is not None:
        log.info("Run pipeline #%d", recorder.run_id)

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

        phase_started_at = datetime.datetime.now(datetime.UTC)
        before_volumes = recorder.before_volumes(watched_tables(name))
        t0_phase = time.time()
        try:
            result = fn(
                mode=args.mode,
                sources=sources,
                year=args.year,
                start_year=args.start_year,
                include_wos=args.include_wos,
                rebuild_publications=args.rebuild_publications,
            )
        except KeyboardInterrupt:
            log.warning("Pipeline interrompu par l'utilisateur à la phase '%s'", name)
            log.info("Pour reprendre : python run_pipeline.py --from %s", name)
            recorder.record(
                phase=name,
                started_at=phase_started_at,
                status="warning",
                metrics=PhaseMetrics().to_payload(time.time() - t0_phase),
                signals=[
                    {
                        "level": "warning",
                        "code": "interrupted",
                        "message": "Interrompu par l'utilisateur (action contrôlée)",
                    }
                ],
                details={},
                before_volumes=before_volumes,
            )
            phase_results.append((name + " (INTERROMPU)", time.time() - t0_phase))
            clear_status()
            sys.exit(130)
        except RuntimeError as e:
            log.error("Pipeline interrompu à la phase '%s' : %s", name, e)
            log.error("Pour reprendre : python run_pipeline.py --from %s", name)
            recorder.record(
                phase=name,
                started_at=phase_started_at,
                status="error",
                metrics=PhaseMetrics().to_payload(time.time() - t0_phase),
                signals=[{"level": "error", "code": "exception", "message": str(e)}],
                details={},
                before_volumes=before_volumes,
            )
            phase_results.append((name + " (ERREUR)", time.time() - t0_phase))
            clear_status()
            sys.exit(1)

        duration = time.time() - t0_phase
        phase_results.append((name, duration))
        metrics = result if isinstance(result, PhaseMetrics) else PhaseMetrics()
        if isinstance(result, PhaseMetrics):
            log.info("Total phase %s : %s", name, result.as_summary())
        recorder.record(
            phase=name,
            started_at=phase_started_at,
            status="warning" if metrics.signals else "ok",
            metrics=metrics.to_payload(duration),
            signals=metrics.signals,
            details=metrics.details,
            before_volumes=before_volumes,
        )

    elapsed_total = time.time() - t0_total

    recorder.close()

    clear_status()
    log.info("=" * 60)
    log.info("PIPELINE TERMINÉ en %.0fs (%.1f min)", elapsed_total, elapsed_total / 60)
    if recorder.run_id is not None:
        log.info("Run #%d — récapitulatif par phase :", recorder.run_id)
        for phase_name, phase_duration in phase_results:
            log.info("  %-22s %7.1fs", phase_name, phase_duration)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
