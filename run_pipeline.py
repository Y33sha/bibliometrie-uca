#!/usr/bin/env python3
"""
Orchestrateur du pipeline bibliométrique.

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
    refresh_stale       Refetch par identifiant natif des rows à last_seen_at ancien
                        (> STALE_REFRESH_AFTER_DAYS) : trouvé -> bump last_seen_at + refresh ;
                        absence confirmée -> disappeared_at. Marque seulement, aucun effet aval.
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
import contextvars
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
    from application.ports.pipeline.extract.refresh_stale import RefreshStaleAdapter
    from infrastructure.queries.pipeline.countries import AddressCountryStatus

from application.pipeline.graph import PHASE_ORDER
from application.pipeline.metadata_correction.correct_by_cluster import ClusterCorrectionStats
from application.pipeline.metadata_correction.correct_unary import UnaryCorrectionStats
from application.pipeline.metadata_correction.journal_by_doi import JournalByDoiStats
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.modes import MODE_NAMES, MODES
from application.pipeline.normalize.base import NormalizeStats
from domain.sources.registry import ALL_SOURCES, ALL_SOURCES_SET, DOI_SEARCHABLE_SOURCES
from infrastructure.observability.log import reset_log_phase, set_log_phase, setup_logger
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


def _signal_source_unconfigured(
    metrics: PhaseMetrics, source: str, reason: str, *, phase: str = "extract"
) -> None:
    """Marque un accès à une API tierce non configuré comme sauté (avertissement).

    Un accès dont la configuration manque (credentials, ou pour l'extraction bulk le
    périmètre d'interrogation) n'interrompt pas le run : la phase se termine avec les
    accès configurés, son point passe en ambre et le motif s'affiche au détail. Même
    canal de signaux que le circuit-breaker. `reason` est le motif d'absence, `phase`
    le contexte pour le log (extract, cross_imports, refresh_stale, oa_status…)."""
    log.warning("%s : source %s non configurée — sautée : %s", phase, source, reason)
    metrics.signals.append(
        {
            "level": "warning",
            "code": "source_unconfigured",
            "message": f"{source} non configurée — sautée : {reason}",
        }
    )


def _configured_api_targets(targets: list[str], metrics: PhaseMetrics, *, phase: str) -> list[str]:
    """Filtre les sources dont les credentials d'API manquent avant toute requête.

    Chaque source non configurée est sautée avec un signal `source_unconfigured`
    (même canal que l'extraction) ; seules les sources configurées sont retournées.
    Ouvre une connexion courte pour consulter le détecteur central. Utilisé par les
    phases qui interrogent une API par identifiant (cross-import, refresh stale)."""
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.config import source_credentials_missing

    configured: list[str] = []
    with get_sync_engine().connect() as conn:
        for target in targets:
            reason = source_credentials_missing(conn, target)
            if reason:
                _signal_source_unconfigured(metrics, target, reason, phase=phase)
            else:
                configured.append(target)
    return configured


def _extract_source_summary(source_metrics: PhaseMetrics, duration_s: float) -> dict[str, float]:
    """Récapitulatif par source pour la table de la phase `extract`."""
    return {
        "found": source_metrics.total,
        "new": source_metrics.new,
        "updated": source_metrics.updated,
        "unchanged": source_metrics.unchanged,
        "errors": source_metrics.errors,
        "duration_s": round(duration_s, 1),
    }


def _run_parallel_extractors(
    tasks: list[tuple[str, Callable[[], PhaseMetrics]]], metrics: PhaseMetrics
) -> dict[str, dict[str, float]]:
    """Exécute les extracteurs en parallèle et agrège leurs métriques.

    Chaque `_run_extract_*` ouvre sa propre connexion DB et écrit dans des tables
    `staging.*` distinctes : aucun état partagé, parallélisme thread-safe. La merge
    des `PhaseMetrics` reste séquentielle (non thread-safe) dans le thread principal.
    Une source non configurée (`ExtractionConfigError`) est sautée avec un
    avertissement, les autres aboutissent. Retourne le récap par source ; une source
    sautée n'y produit aucune ligne (distincte d'une source à zéro résultat)."""
    from application.pipeline.extract.base import ExtractionConfigError

    by_source: dict[str, dict[str, float]] = {}
    log.info("▶ extracteurs en parallèle (%d) : %s", len(tasks), ", ".join(n for n, _ in tasks))
    # Les threads n'héritent pas de la ContextVar de phase : chaque worker rejoue sa
    # tâche dans une copie du contexte courant (phase `extract`), pour que ses logs
    # restent estampillés `extract:` et non du nom du logger source. Une copie par
    # worker — un même Context ne peut pas être entré par deux threads à la fois.
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {
            pool.submit(contextvars.copy_context().run, _timed_metrics, fn): name
            for name, fn in tasks
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                source_metrics, duration = future.result()
            except ExtractionConfigError as exc:
                _signal_source_unconfigured(metrics, source, str(exc))
                continue
            metrics.merge(source_metrics)
            by_source[source] = _extract_source_summary(source_metrics, duration)
    return by_source


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
    from application.pipeline.extract.base import ExtractionConfigError

    policy = MODES[mode]
    allowed = set(policy.extract_sources) | ({"wos"} if include_wos else set())
    effective = (set(sources) if sources else allowed) & allowed
    metrics = PhaseMetrics()
    by_source: dict[str, dict[str, float]] = {}
    extractors = _extractors()

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
            try:
                hal_metrics, hal_duration = _timed_metrics(
                    partial(_run_extract, "hal", extractors["hal"], _extractor_args(since=since))
                )
            except ExtractionConfigError as exc:
                _signal_source_unconfigured(metrics, "hal", str(exc))
            else:
                metrics.merge(hal_metrics)
                by_source["hal"] = _extract_source_summary(hal_metrics, hal_duration)
    else:
        tasks: list[tuple[str, Callable[[], PhaseMetrics]]] = []

        def task(source: str, **arg_kwargs: Any) -> tuple[str, Callable[[], PhaseMetrics]]:
            fn = partial(_run_extract, source, extractors[source], _extractor_args(**arg_kwargs))
            return (source, fn)

        if "openalex" in effective:
            tasks.append(task("openalex", start_year=start_year, year=year))
        if "hal" in effective:
            tasks.append(task("hal", start_year=start_year, year=year))
        if "wos" in effective:
            tasks.append(task("wos", start_year=start_year, year=year))
        if "scanr" in effective:
            tasks.append(task("scanr", start_year=start_year, year=year))
        if "theses" in effective:
            tasks.append(task("theses", year=year))
        if tasks:
            by_source = _run_parallel_extractors(tasks, metrics)

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

    1. **Cross-import HAL** (`fetch_missing_hal`), en deux pistes distinctes :
       par hal-id (repéré dans OpenAlex/ScanR, tourne systématiquement) et par
       NNT (thèses soutenues sans HAL, mode `full` uniquement — volume trop large
       en incrémental). Pour chaque référence absente du staging HAL, on télécharge
       le document via l'API HAL. Auto-bornée : les hal-ids/NNT introuvables sont
       marqués `not_found_at` dans staging et ne sont jamais re-interrogés.

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

    # Étape 1 : cross-import HAL, deux pistes distinctes (hal-id, NNT).
    if not sources or "hal" in sources:
        id_metrics, id_duration = _timed_metrics(_run_fetch_missing_hal_by_id)
        metrics.merge(id_metrics)
        by_channel["hal-id"] = _summary(id_metrics, id_duration)

        # NNT trop volumineux pour un run incrémental : réservé au mode full.
        if mode == "full":
            nnt_metrics, nnt_duration = _timed_metrics(_run_fetch_missing_hal_by_nnt)
            metrics.merge(nnt_metrics)
            by_channel["NNT"] = _summary(nnt_metrics, nnt_duration)

    # Étape 2 : par DOI. WoS opt-in (cf. docstring).
    targets = set(DOI_SEARCHABLE_SOURCES)
    if not include_wos:
        targets -= {"wos"}
    effective = (set(sources) if sources else set(targets)) & targets

    doi_targets = [t for t in DOI_SEARCHABLE_SOURCES if t in effective]
    doi_targets = _configured_api_targets(doi_targets, metrics, phase="cross_imports")
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


def phase_refresh_stale(
    sources: Any = None,
    include_wos: bool = False,
    start_year: Any = None,
    year: Any = None,
    **kw: Any,
) -> PhaseMetrics:
    """Rafraîchit les rows à `last_seen_at` ancien et marque les disparues.

    Tourne à **chaque run** : le seuil `STALE_REFRESH_AFTER_DAYS` étale la
    charge (chaque passe ne ramasse que ce qui vient de franchir le délai).

    Pour chaque source, refetch des rows stale **par leur identifiant natif**
    (`staging.source_id`, jamais NULL) : trouvé → bump `last_seen_at` + refresh
    `raw_data` ; absence confirmée par la source → `disappeared_at` ; échec
    transitoire → no-op. Toute row est ainsi re-vérifiée directement, avec ou
    sans DOI. WoS est opt-in (`--include-wos`) : exclu par défaut, comme
    `extract` et `cross_imports`.

    Le refresh est **couplé à la fenêtre d'années du run** (`start_year`/`year`,
    via `source_publications.pub_year`) : un run sur une période glissante ne
    refetche que le stale de ses propres années, sans requêtes unitaires inutiles
    sur des années qu'il ne moissonne plus en bulk. `theses` fait exception, comme
    à l'extraction : elle ramène tout l'historique (aucune borne), sauf `--year`.

    Conservateur : on **marque seulement** (`disappeared_at`), aucun effet
    aval. Placée après `cross_imports` (qui a fini de peupler `staging` et
    `last_seen_at`) et avant `normalize` (qui consomme le `raw_data` rafraîchi).
    """
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.config import get_years

    metrics = PhaseMetrics()
    by_source: dict[str, dict[str, float]] = {}
    allowed = set(ALL_SOURCES)
    if not include_wos:
        allowed -= {"wos"}
    effective = (set(sources) if sources else allowed) & allowed
    targets = [t for t in ALL_SOURCES if t in effective]
    targets = _configured_api_targets(targets, metrics, phase="refresh_stale")

    # Fenêtre d'années du run, alignée sur l'extraction : `--year` cible une seule
    # année, sinon `[start_year … courante]` (défaut config). `theses` ignore la
    # borne large (elle moissonne tout l'historique), mais suit `--year` s'il est posé.
    if year:
        years_default: list[int] | None = [int(year)]
    else:
        with get_sync_engine().connect() as conn:
            years_default = get_years(conn, start_year)
    years_theses = [int(year)] if year else None

    for target in targets:
        row_years = years_theses if target == "theses" else years_default
        source_metrics, duration = _timed_metrics(partial(_run_refresh_stale, target, row_years))
        metrics.merge(source_metrics)
        by_source[target] = {
            "interrogated": source_metrics.total,
            "refreshed": source_metrics.updated,
            "unchanged": source_metrics.unchanged,
            "disappeared": source_metrics.extras.get("disappeared", 0),
            "duration_s": round(duration, 1),
        }

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
    for source, build in _normalize_builders().items():
        if source in sources:
            rows.append(_run_normalize(source, build))
    # Balayage des identités orphelines : les writers ont pu re-pointer des
    # signatures vers d'autres identités, laissant des `author_identifying_keys`
    # que plus aucune signature ne référence.
    _run_cleanup_orphan_identities()
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


def _run_cleanup_orphan_identities() -> None:
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.normalize.authorships import delete_orphan_identities

    log.info("▶ nettoyage des identités orphelines")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        n = delete_orphan_identities(conn)
        conn.commit()
    finally:
        conn.close()
    log.info("✓ %d identités orphelines supprimées en %.1fs", n, time.time() - t0)


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
    nouveaux DOIs via `fetch_missing_hal`, (b) `normalize` crée les
    `publishers`/`journals` qu'on veut enrichir.
    """
    metrics = PhaseMetrics()

    # resolve_publishers interroge Crossref et DataCite (email polite pool requis) ;
    # enrich_journals_from_openalex interroge OpenAlex (clé ou email). Chaque accès
    # non configuré est sauté ; DOAJ (dump public) tourne toujours.
    publishers = PhaseMetrics()
    if _configured_api_targets(["crossref", "datacite"], metrics, phase="publishers_journals"):
        publishers = _run_resolve_publishers()

    openalex = PhaseMetrics()
    if _configured_api_targets(["openalex"], metrics, phase="publishers_journals"):
        openalex = _run_enrich_journals_from_openalex()

    doaj = _run_enrich_journals_from_doaj()

    # Les compteurs et signaux des sous-étapes remontent à la phase : sans ce merge,
    # `as_summary()` (log) et `to_payload()` (observabilité) rapporteraient « no-op »
    # malgré le travail effectué, et un circuit-breaker tripé ne passerait pas la
    # phase en avertissement. Les `details` sur-mesure sont posés juste après.
    for sub in (publishers, openalex, doaj):
        metrics.merge(sub)

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


def _signal_if_tripped(metrics: PhaseMetrics, breaker: Any) -> None:
    """Quand un circuit-breaker source a coupé (série de 429/5xx), marque la phase en
    avertissement : son point passe ambre et le motif s'affiche au drill-down. Les items
    non traités sont repris au run suivant (phases de rattrapage idempotentes)."""
    if breaker.tripped:
        metrics.signals.append(
            {
                "level": "warning",
                "code": "source_unavailable",
                "message": (
                    f"{breaker.source} : arrêt après une série d'échecs (429/5xx), "
                    "items reportés au prochain run"
                ),
            }
        )


def _run_resolve_ra() -> PhaseMetrics:
    from application.pipeline.publishers_journals.resolve_doi_prefixes import run_resolve_ra
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.repositories import doi_prefix_repository
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )
    from infrastructure.sources.config import get_polite_pool_email_optional
    from infrastructure.sources.doi_prefixes.clients import build_user_agent, resolve_ra

    log.info("▶ resolve_ra")
    t0 = time.time()
    conn = get_sync_engine().connect()
    # Circuit-breaker sur doi.org/ra : la ContextVar est lue par le helper HTTP,
    # `run_resolve_ra` consulte `breaker.tripped` pour s'arrêter proprement.
    breaker = SourceCircuitBreaker("doi.org/ra")
    token = set_current_breaker(breaker)
    try:
        # doi.org/ra est une API publique (aucun credential) : l'email polite pool
        # est facultatif, on ne saute pas la résolution s'il manque.
        user_agent = build_user_agent(get_polite_pool_email_optional(conn) or "")
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
    _signal_if_tripped(metrics, breaker)
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
    from infrastructure.sources.config import get_polite_pool_email_optional
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
        user_agent = build_user_agent(get_polite_pool_email_optional(conn) or "")
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
    _signal_if_tripped(metrics, breaker)
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
    from application.pipeline.relations.populate_relations import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.relations import PgPublicationRelationsQueries

    return run(get_sync_engine().begin, PgPublicationRelationsQueries(), log)


def phase_persons(**kw: Any) -> PhaseMetrics:
    """Rattachement et création des personnes, phase ordre-indépendante.

    L'orchestrateur enchaîne, sur une seule transaction : `enforce` (réapplique les épinglages
    admin), `reset` (réinitialise les attributions dérivées — arbitrage des conflits d'identifiant,
    recompute cross-source), `match` (rattache sans créer), `create` (crée les signatures restées
    non liées, cross-source rejoué d'abord), `populate` (régénère les formes de nom canoniques),
    `purge` (re-orpheline les formes devenues ambiguës et supprime les personnes vidées). Exclut les
    publications hors-scope (cf domain/publications/scope).
    """
    return _run_persons_phase()


def phase_authorships(**kw: Any) -> PhaseMetrics:
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
    metrics = _run_build_authorships()
    _run_purge_orphan_publications()
    _run_refresh_pub_counts()
    return metrics


def phase_countries(mode: Any = "full", **kw: Any) -> PhaseMetrics:
    """Detection des pays des adresses et recalcul sur les publications."""
    metrics = PhaseMetrics()
    initial = _log_countries_summary("Bilan initial")
    metrics.merge(_run_detect_by_country_name())
    metrics.merge(_run_detect_by_place_name())
    metrics.merge(
        _run_suggest_address_countries(retry_empty=MODES[mode].retry_empty_country_suggestions)
    )
    _run_refresh_publication_countries()
    final = _log_countries_summary("Bilan final")
    # Entonnoir : du manque initial (adresses sans pays avant la détection du run) aux
    # pays rattachés par le run, puis au reste (dont une part porte une suggestion).
    total = final.total
    without_initial = total - initial.with_country
    metrics.details["summary"] = {
        "total": total,
        "without_initial": without_initial,
        "without_pct": round(100 * without_initial / total, 1) if total else 0,
        "newly_attached": final.with_country - initial.with_country,
        "remaining": total - final.with_country,
        "with_suggestion": final.with_suggestion,
    }
    return metrics


def phase_subjects(**kw: Any) -> PhaseMetrics:
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
    metrics = _run_ingest_subjects()
    _run_cooccurrences()
    return metrics


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


def _run_persons_phase() -> PhaseMetrics:
    from application.pipeline.persons.phase import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.name_forms import PgNameFormsQueries
    from infrastructure.queries.pipeline.persons_create import PgPersonsCreateQueries
    from infrastructure.repositories import authorship_repository, person_repository

    log.info("▶ persons")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        metrics = run(
            conn,
            PgPersonsCreateQueries(),
            PgNameFormsQueries(),
            log,
            person_repo=person_repository(conn),
            authorship_repo=authorship_repository(conn),
        )
        conn.commit()
    finally:
        conn.close()
    log.info("✓ persons terminé en %.1fs", time.time() - t0)
    return metrics


def _run_build_authorships() -> PhaseMetrics:
    from application.pipeline.authorships.build_authorships import build
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.authorships_build import PgAuthorshipsBuildQueries

    log.info("▶ build_authorships")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        metrics = build(conn, PgAuthorshipsBuildQueries(), log)
        conn.commit()
    finally:
        conn.close()
    log.info("✓ build_authorships terminé en %.1fs", time.time() - t0)
    return metrics


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


def _normalize_row(source: str, stats: NormalizeStats, duration_s: float) -> dict[str, object]:
    """Ligne « par source » de la table d'observabilité de la phase normalize."""
    return {
        "key": source,
        "processed": stats.processed,
        "skipped": stats.skipped,
        "errors": stats.errors,
        "duration_s": round(duration_s, 1),
    }


def _normalize_builders() -> dict[str, Callable[[Any], Any]]:
    """Constructeur du normalizer par source, dans l'ordre de priorité (source la plus
    autoritative en premier — cf. SOURCE_PRIORITY) : les suivantes n'écrasent pas les
    métadonnées déjà posées. Les six sources bibliographiques partagent le câblage
    `_biblio` ; `theses` a le sien (`address_linker`, sans repos journal/publisher)."""
    from application.pipeline.normalize.normalize_crossref import CrossrefNormalizer
    from application.pipeline.normalize.normalize_datacite import DataciteNormalizer
    from application.pipeline.normalize.normalize_hal import HalNormalizer
    from application.pipeline.normalize.normalize_openalex import OpenalexNormalizer
    from application.pipeline.normalize.normalize_scanr import ScanrNormalizer
    from application.pipeline.normalize.normalize_theses import ThesesNormalizer
    from application.pipeline.normalize.normalize_wos import WosNormalizer
    from infrastructure.queries.pipeline.normalize.authorships import PgAuthorshipsBatchQueries
    from infrastructure.queries.pipeline.normalize.crossref import PgCrossrefNormalizeQueries
    from infrastructure.queries.pipeline.normalize.datacite import PgDataciteNormalizeQueries
    from infrastructure.queries.pipeline.normalize.hal import PgHalNormalizeQueries
    from infrastructure.queries.pipeline.normalize.openalex import PgOpenalexNormalizeQueries
    from infrastructure.queries.pipeline.normalize.scanr import PgScanrNormalizeQueries
    from infrastructure.queries.pipeline.normalize.theses import PgThesesNormalizeQueries
    from infrastructure.queries.pipeline.normalize.wos import PgWosNormalizeQueries
    from infrastructure.queries.pipeline.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )
    from infrastructure.repositories.address_linker import PgAddressLinker

    def _biblio(cls: Any, queries_cls: Any) -> Callable[[Any], Any]:
        return lambda conn: cls(
            conn,
            log,
            PgStagingQueries(),
            queries_cls(),
            journal_repo_factory=journal_repository,
            publisher_repo_factory=publisher_repository,
            pub_repo_factory=publication_repository,
            authorship_queries=PgAuthorshipsBatchQueries(),
        )

    return {
        "theses": lambda conn: ThesesNormalizer(
            conn,
            log,
            PgStagingQueries(),
            PgThesesNormalizeQueries(),
            pub_repo_factory=publication_repository,
            address_linker=PgAddressLinker(),
        ),
        "crossref": _biblio(CrossrefNormalizer, PgCrossrefNormalizeQueries),
        "datacite": _biblio(DataciteNormalizer, PgDataciteNormalizeQueries),
        "scanr": _biblio(ScanrNormalizer, PgScanrNormalizeQueries),
        "hal": _biblio(HalNormalizer, PgHalNormalizeQueries),
        "openalex": _biblio(OpenalexNormalizer, PgOpenalexNormalizeQueries),
        "wos": _biblio(WosNormalizer, PgWosNormalizeQueries),
    }


def _run_normalize(source: str, build: Callable[[Any], Any]) -> dict[str, object]:
    from infrastructure.db.engine import get_sync_engine

    log.info("▶ normalize_%s", source)
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        stats = build(conn).run([])
    finally:
        conn.close()
    duration = time.time() - t0
    log.info("✓ normalize_%s terminé en %.1fs", source, duration)
    return _normalize_row(source, stats, duration)


def _run_enrich_oa_status() -> PhaseMetrics:
    import asyncio

    import httpx

    from application.pipeline.oa_status.run import run_enrich_oa_status
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.enrich import PgEnrichQueries
    from infrastructure.repositories import publication_repository
    from infrastructure.sources.config import get_api_base_urls, get_polite_pool_email_optional
    from infrastructure.sources.unpaywall import fetch_oa_status

    log.info("▶ enrich_oa_status")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        base_url = get_api_base_urls()["unpaywall"]
        email = get_polite_pool_email_optional(conn) or ""

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
        get_polite_pool_email_optional,
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
            mailto=get_polite_pool_email_optional(conn) or "",
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
    from infrastructure.sources.config import get_polite_pool_email_optional
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
        # DOAJ : dump CSV public (aucun credential) ; l'email polite pool est facultatif.
        user_agent = build_doaj_user_agent(get_polite_pool_email_optional(conn) or "")
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


def _run_ingest_subjects() -> PhaseMetrics:
    from application.pipeline.subjects.run import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.subjects import PgSubjectsQueries

    log.info("▶ subjects")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        metrics = run(conn, PgSubjectsQueries(), log)
        conn.commit()
    finally:
        conn.close()
    log.info("✓ subjects terminé en %.1fs", time.time() - t0)
    return metrics


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
        metrics = extractor.run_as_phase(args, breaker=breaker)
    finally:
        reset_current_breaker(token)
    _signal_if_tripped(metrics, breaker)
    return metrics


def _extractors() -> dict[str, Callable[[Any, Any], Any]]:
    """Constructeur de l'extracteur par source : `(conn, source_log)` → extracteur câblé.

    `wos` et `scanr` ouvrent une connexion d'amorçage pour lire leur clé / identifiants
    avant l'extraction ; les autres n'ont besoin que de l'URL de base (lue en config)."""
    from application.pipeline.extract.extract_hal import HalExtractor
    from application.pipeline.extract.extract_openalex import OpenalexExtractor
    from application.pipeline.extract.extract_scanr import ScanrExtractor
    from application.pipeline.extract.extract_theses import ThesesExtractor
    from application.pipeline.extract.extract_wos import WosExtractor
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.config import get_api_base_urls, get_wos_api_key
    from infrastructure.sources.hal.extract_hal import PgHalExtractAdapter
    from infrastructure.sources.openalex.extract_openalex import PgOpenalexExtractAdapter
    from infrastructure.sources.scanr.extract_scanr import (
        PgScanrExtractAdapter,
        get_scanr_credentials_from_db,
    )
    from infrastructure.sources.theses.extract_theses import PgThesesExtractAdapter
    from infrastructure.sources.wos.extract_wos import PgWosExtractAdapter

    def hal(conn: Any, source_log: Any) -> Any:
        adapter = PgHalExtractAdapter(base_url=get_api_base_urls()["hal"])
        return HalExtractor(conn, source_log, adapter)

    def openalex(conn: Any, source_log: Any) -> Any:
        adapter = PgOpenalexExtractAdapter(base_url=get_api_base_urls()["openalex"])
        return OpenalexExtractor(conn, source_log, adapter)

    def wos(conn: Any, source_log: Any) -> Any:
        with get_sync_engine().connect() as bootstrap:
            api_key = get_wos_api_key(bootstrap)
        adapter = PgWosExtractAdapter(base_url=get_api_base_urls()["wos"], api_key=api_key)
        return WosExtractor(conn, source_log, adapter)

    def scanr(conn: Any, source_log: Any) -> Any:
        with get_sync_engine().connect() as bootstrap:
            credentials = get_scanr_credentials_from_db(bootstrap)
        adapter = PgScanrExtractAdapter(
            base_url=get_api_base_urls()["scanr"], credentials=credentials
        )
        return ScanrExtractor(conn, source_log, adapter)

    def theses(conn: Any, source_log: Any) -> Any:
        adapter = PgThesesExtractAdapter(base_url=get_api_base_urls()["theses"])
        return ThesesExtractor(conn, source_log, adapter)

    return {"hal": hal, "openalex": openalex, "wos": wos, "scanr": scanr, "theses": theses}


def _run_extract(
    source: str, make_extractor: Callable[[Any, Any], Any], args: argparse.Namespace
) -> PhaseMetrics:
    """Squelette commun d'une extraction : logs `▶`/`✓`, connexion, circuit-breaker
    (`_run_extractor`), fermeture. Le câblage propre à la source vit dans `make_extractor`."""
    from infrastructure.db.engine import get_sync_engine

    log.info("▶ extract_%s", source)
    t0 = time.time()
    source_log = setup_logger(source, str(BASE / "logs"))
    conn = get_sync_engine().connect()
    try:
        metrics = _run_extractor(make_extractor(conn, source_log), args)
    finally:
        conn.close()
    log.info("✓ extract_%s terminé en %.1fs — %s", source, time.time() - t0, metrics.as_summary())
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


def _run_fetch_missing_hal_by_id() -> PhaseMetrics:
    """Cross-import HAL par hal-id (OpenAlex/ScanR) : documents absents du staging."""
    from application.pipeline.extract.fetch_missing_hal import fetch_missing_hal_by_id
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.hal.fetch_missing_hal import PgHalFetchMissingAdapter

    log.info("▶ fetch_missing_hal (par hal-id)")
    t0 = time.time()
    conn = get_sync_engine().connect()
    adapter = PgHalFetchMissingAdapter()
    try:
        metrics = asyncio.run(fetch_missing_hal_by_id(conn, adapter, log))
    finally:
        conn.close()
    log.info(
        "✓ fetch_missing_hal (par hal-id) terminé en %.1fs — %s",
        time.time() - t0,
        metrics.as_summary(),
    )
    return metrics


def _run_fetch_missing_hal_by_nnt() -> PhaseMetrics:
    """Cross-import HAL par NNT (theses.fr) : thèses soutenues sans document HAL."""
    from application.pipeline.extract.fetch_missing_hal import fetch_missing_hal_by_nnt
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.hal.fetch_missing_hal import PgHalFetchMissingAdapter

    log.info("▶ fetch_missing_hal (par NNT)")
    t0 = time.time()
    conn = get_sync_engine().connect()
    adapter = PgHalFetchMissingAdapter()
    try:
        metrics = asyncio.run(fetch_missing_hal_by_nnt(conn, adapter, log))
    finally:
        conn.close()
    log.info(
        "✓ fetch_missing_hal (par NNT) terminé en %.1fs — %s",
        time.time() - t0,
        metrics.as_summary(),
    )
    return metrics


def _make_fetch_missing_doi_adapter(target: str) -> "AsyncFetchMissingDoiAdapter":
    """Construit l'adapter `fetch_missing_doi` d'une source cible.

    Consommé par le cross-import (`_run_fetch_missing_doi`).
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
    # concrète à un Protocol via `type[Protocol]`.
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
    _signal_if_tripped(metrics, breaker)
    return metrics


def _make_refresh_stale_adapter(source: str) -> "RefreshStaleAdapter":
    """Construit l'adapter `refresh_stale` d'une source (refetch par id natif)."""
    from infrastructure.sources.crossref.refresh_stale import CrossrefRefreshStaleAdapter
    from infrastructure.sources.datacite.refresh_stale import DataciteRefreshStaleAdapter
    from infrastructure.sources.hal.refresh_stale import HalRefreshStaleAdapter
    from infrastructure.sources.openalex.refresh_stale import OpenalexRefreshStaleAdapter
    from infrastructure.sources.scanr.refresh_stale import ScanrRefreshStaleAdapter
    from infrastructure.sources.theses.refresh_stale import ThesesRefreshStaleAdapter
    from infrastructure.sources.wos.refresh_stale import WosRefreshStaleAdapter

    # Cast : mypy ne reconnaît pas la conformité structurelle d'une classe concrète
    # à un Protocol via `type[Protocol]` (cf. `_make_fetch_missing_doi_adapter`).
    adapter_classes: dict[str, type[RefreshStaleAdapter]] = cast(
        "dict[str, type[RefreshStaleAdapter]]",
        {
            "hal": HalRefreshStaleAdapter,
            "openalex": OpenalexRefreshStaleAdapter,
            "wos": WosRefreshStaleAdapter,
            "scanr": ScanrRefreshStaleAdapter,
            "theses": ThesesRefreshStaleAdapter,
            "crossref": CrossrefRefreshStaleAdapter,
            "datacite": DataciteRefreshStaleAdapter,
        },
    )
    return adapter_classes[source]()


def _run_refresh_stale(target: str, years: list[int] | None) -> PhaseMetrics:
    """Refetch par id natif des rows stale d'une source : trouvé → bump, absence → disappeared.

    `years` borne le refresh à la fenêtre d'années du run (None = tout le stale).
    """
    from application.pipeline.extract.refresh_stale import refresh
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )

    adapter = _make_refresh_stale_adapter(target)

    log.info("▶ refresh_stale --target %s", target)
    t0 = time.time()
    conn = get_sync_engine().connect()
    # Circuit-breaker par source (cf. `_run_fetch_missing_doi`) : coupe le refetch
    # d'une source à bout de budget (429 répétés) au lieu de la marteler. La
    # ContextVar est posée ici, le helper HTTP infra la lit, l'orchestrateur ne
    # consulte que `breaker.tripped`.
    breaker = SourceCircuitBreaker(target)
    token = set_current_breaker(breaker)
    try:
        metrics = asyncio.run(refresh(conn, adapter, log, years=years, breaker=breaker))
    finally:
        reset_current_breaker(token)
        conn.close()
    log.info(
        "✓ refresh_stale (%s) terminé en %.1fs — %s",
        target,
        time.time() - t0,
        metrics.as_summary(),
    )
    _signal_if_tripped(metrics, breaker)
    return metrics


def _run_detect_by_country_name() -> PhaseMetrics:
    from application.pipeline.countries.detect_by_country_name import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.countries import PgCountryQueries

    log.info("▶ detect_by_country_name")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        metrics = run(conn, PgCountryQueries(), log)
        conn.commit()
    finally:
        conn.close()
    log.info(
        "✓ detect_by_country_name terminé en %.1fs — %s",
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


def _run_detect_by_place_name() -> PhaseMetrics:
    from application.pipeline.countries.detect_by_place_name import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.countries import PgCountryQueries

    log.info("▶ detect_by_place_name")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        metrics = run(conn, PgCountryQueries(), log)
        conn.commit()
    finally:
        conn.close()
    log.info(
        "✓ detect_by_place_name terminé en %.1fs — %s",
        time.time() - t0,
        metrics.as_summary(),
    )
    return metrics


def _run_suggest_address_countries(*, retry_empty: bool = False) -> PhaseMetrics:
    from application.pipeline.countries.suggest_countries import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.countries import PgCountryQueries

    log.info("▶ suggest_address_countries%s", " (retry-vides)" if retry_empty else "")
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        # `run` commite par batch (progression durable, WAL borné) : pas de commit final ici.
        metrics = run(conn, PgCountryQueries(), log, retry_empty=retry_empty)
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

    Unpaywall exige l'email polite pool : sans lui, la phase est sautée proprement.
    """
    metrics = PhaseMetrics()
    if _configured_api_targets(["unpaywall"], metrics, phase="oa_status"):
        metrics.merge(_run_enrich_oa_status())
    return metrics


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
    parser = argparse.ArgumentParser(description="Orchestrateur pipeline bibliométrique")
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
    log.info("PIPELINE BIBLIOMÉTRIQUE — mode %s", args.mode)
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
        # Injecte le nom de phase dans tous les records émis pendant `fn` (nom de
        # logger `normalize:` plutôt que `pipeline:`), y compris depuis les
        # extracteurs threadés qui héritent du contexte via `copy_context`.
        phase_token = set_log_phase(name)
        try:
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
            )
        finally:
            reset_log_phase(phase_token)

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
