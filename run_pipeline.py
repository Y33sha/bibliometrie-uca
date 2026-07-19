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
import datetime
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from sqlalchemy import Connection

    from application.ports.pipeline.cross_imports.fetch_missing_doi import (
        AsyncFetchMissingDoiAdapter,
    )
    from application.ports.pipeline.extract.refresh_stale import RefreshStaleAdapter

from application.pipeline.metrics import PhaseMetrics
from application.pipeline.modes import MODE_NAMES, MODES
from application.pipeline.normalize.base import NormalizeStats
from application.pipeline.phase_order import PHASE_ORDER
from domain.sources.registry import ALL_SOURCES_SET
from infrastructure.observability.log import (
    PHASE_MARKER,
    RUN_END_MARKER,
    RUN_MARKER,
    reset_log_phase,
    set_log_phase,
    setup_logger,
)
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


def _open_tx() -> "AbstractContextManager[Connection]":
    """Fabrique de transaction gérée (port `OpenTransaction`) injectée aux orchestrateurs de
    phase : commit-sur-succès / rollback / close, tolérant les commits par lots. Concentrée au
    composition-root pour que `application/` reste sans dépendance à l'engine."""
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.transaction import managed_transaction

    return managed_transaction(get_sync_engine())


def phase_extract(
    mode: Any = "full",
    sources: Any = None,
    year: Any = None,
    start_year: Any = None,
    include_wos: bool = False,
    **kw: Any,
) -> PhaseMetrics:
    """Phase 1 : Extraction des sources vers staging.

    La policy du mode (sources, stratégie d'années) vit dans `application/pipeline/modes.py`.
    Le refetch des works OpenAlex tronqués est une phase distincte (`refetch_truncated`), placée
    après `refresh_stale` et avant `normalize`.

    Séquence, parallélisme et métriques dans `application/pipeline/extract/phase.py` ; ici, le
    câblage : registre des adapters, primitif de parallélisme, lecture de la dernière extraction.
    """
    from application.pipeline.extract.phase import run
    from infrastructure.observability.phase_executions import get_last_extract_date
    from infrastructure.parallel import run_parallel

    registry = _extractors()

    def extract_one(source: str, args: argparse.Namespace) -> PhaseMetrics:
        return _run_extract(source, registry[source], args)

    return run(
        mode=mode,
        sources=set(sources) if sources else None,
        year=year,
        start_year=start_year,
        include_wos=include_wos,
        extract_one=extract_one,
        run_parallel=run_parallel,
        get_last_extract_date=get_last_extract_date,
        logger=log,
    )


def phase_resolve_ra(**kw: Any) -> PhaseMetrics:
    """Résout la Registration Agency des préfixes DOI (`doi.org/ra`) avant cross_imports.

    Permet à `cross_imports` de router les fetches par RA (Crossref vs DataCite) dès le
    run courant, au lieu de tenter chaque DOI contre les deux APIs (ensembles disjoints).
    Le volet publisher (phase `publishers_journals`) complète ensuite les rows via les
    API `/prefixes`.

    Séquence et métriques dans `run` ; ici, le câblage (connexion, breaker, user-agent).
    """
    from application.pipeline.resolve_ra.phase import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.repositories import doi_prefix_repository
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )
    from infrastructure.sources.config import get_polite_pool_email_optional
    from infrastructure.sources.doi_prefixes.clients import build_user_agent, resolve_ra

    conn = get_sync_engine().connect()
    # Circuit-breaker sur doi.org/ra : la ContextVar est lue par le helper HTTP,
    # `run` consulte `breaker.tripped` pour s'arrêter proprement.
    breaker = SourceCircuitBreaker("doi.org/ra")
    token = set_current_breaker(breaker)
    try:
        # doi.org/ra est une API publique (aucun credential) : l'email polite pool
        # est facultatif, on ne saute pas la résolution s'il manque.
        user_agent = build_user_agent(get_polite_pool_email_optional(conn) or "")
        metrics = run(
            log,
            repo=doi_prefix_repository(conn),
            resolve_ra_fn=lambda doi: resolve_ra(doi, user_agent=user_agent),
            breaker=breaker,
        )
        conn.commit()
    finally:
        reset_current_breaker(token)
        conn.close()
    _signal_if_tripped(metrics, breaker)
    return metrics


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

    Séquence, parallélisme et métriques dans `application/pipeline/cross_imports/phase.py`.
    """
    from application.pipeline.cross_imports.phase import run
    from infrastructure.parallel import run_parallel

    return run(
        mode=mode,
        sources=set(sources) if sources else None,
        include_wos=include_wos,
        fetch_hal_by_id=_run_fetch_missing_hal_by_id,
        fetch_hal_by_nnt=_run_fetch_missing_hal_by_nnt,
        fetch_doi_one=_run_fetch_missing_doi,
        run_parallel=run_parallel,
        credentials_missing=_credentials_missing,
        logger=log,
    )


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

    Séquence et métriques dans `application/pipeline/extract/refresh_stale.py::run_phase`.
    """
    from application.pipeline.extract.refresh_stale import run_phase

    return run_phase(
        sources=set(sources) if sources else None,
        include_wos=include_wos,
        year=year,
        start_year=start_year,
        refresh_one=_run_refresh_stale,
        credentials_missing=_credentials_missing,
        get_years_for_window=_get_years_for_window,
        logger=log,
    )


def _credentials_missing(source: str) -> str | None:
    """Motif d'absence de credentials d'une source (None si configurée). Ouvre une connexion
    courte pour consulter le détecteur central. Injecté aux orchestrateurs des phases API."""
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.config import source_credentials_missing

    with get_sync_engine().connect() as conn:
        return source_credentials_missing(conn, source)


def _get_years_for_window(start_year: int | None) -> list[int] | None:
    """Années de la fenêtre du run `[start_year … courante]` (défaut config). Injecté aux
    orchestrateurs qui bornent leurs requêtes par année."""
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.config import get_years

    with get_sync_engine().connect() as conn:
        return get_years(conn, start_year)


def phase_refetch_truncated(**kw: Any) -> PhaseMetrics:
    """Re-télécharge les works OpenAlex tronqués à 100 auteurs.

    L'API OpenAlex plafonne la liste des auteurs à 100 par réponse. Cette phase
    repère les lignes staging openalex `processed=FALSE` à 100 auteurs et les
    re-télécharge intégralement (pagination des auteurs).

    Placée après `refresh_stale` (pour capter aussi les works tronqués ramenés
    par `cross_imports` et `refresh_stale`) et avant `normalize` (qui passe les
    lignes à `processed=TRUE`, après quoi elles sont invisibles à la détection).

    Séquence et métriques dans `application/pipeline/extract/refetch_truncated.py`.
    """
    import asyncio

    from application.pipeline.extract.refetch_truncated import refetch
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.openalex.refetch_truncated import PgOpenalexRefetchAdapter

    sources = kw.get("sources", set(ALL_SOURCES_SET))
    # Toujours actif (incrémental : ne repère que les lignes openalex processed=FALSE
    # à 100 auteurs) ; ne dépend que de la présence d'openalex dans les sources.
    if "openalex" not in sources:
        return PhaseMetrics()
    conn = get_sync_engine().connect()
    try:
        return asyncio.run(refetch(conn, PgOpenalexRefetchAdapter(), log))
    finally:
        conn.close()


def phase_normalize(**kw: Any) -> PhaseMetrics:
    """Normalisation staging -> tables sources.

    Écrit les `source_publications` avec `publication_id = NULL` (aucun
    rattachement ici : l'assignation aux publications canoniques est faite plus
    tard par la phase `publications`). Stocke les metadonnees (abstract, keywords,
    topics, biblio, etc.) sur source_publications. Vide le raw_data du staging
    apres traitement. Pour HAL : enrichit les structures et extrait ORCID/IdRef
    depuis le TEI.

    Séquence, nettoyage et VACUUM dans `application/pipeline/normalize/phase.py`.
    """
    from application.pipeline.normalize.phase import run

    # Ordre d'exécution : source la plus autoritative en premier (cf. SOURCE_PRIORITY).
    # Les suivantes n'écrasent pas les métadonnées déjà posées lors de `refresh_from_sources`.
    registry = _normalize_builders()

    def normalize_one(source: str) -> dict[str, object]:
        return _run_normalize(source, registry[source])

    return run(
        sources=kw.get("sources", set(ALL_SOURCES_SET)),
        mode=kw.get("mode", "full"),
        ordered_sources=list(registry),
        normalize_one=normalize_one,
        cleanup_orphan_identities=_run_cleanup_orphan_identities,
        vacuum_staging=_vacuum_staging,
        logger=log,
    )


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

    1. `resolve_publishers` : préfixe DOI → éditeur Crossref / repository DataCite
       via `/prefixes`. Ne traite que les rows en attente de publisher ; la
       Registration Agency est posée en amont par la phase `resolve_ra`.
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

    Séquence, gardes de config et métriques dans `application/pipeline/publishers_journals/phase.py`.
    """
    from application.pipeline.publishers_journals.phase import run

    return run(
        resolve_publishers=_run_resolve_publishers,
        enrich_from_openalex=_run_enrich_journals_from_openalex,
        enrich_from_doaj=_run_enrich_journals_from_doaj,
        credentials_missing=_credentials_missing,
        logger=log,
    )


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


def _run_resolve_publishers() -> PhaseMetrics:
    from application.pipeline.publishers_journals.resolve_publishers import (
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

    Séquence, transactions et métriques dans `application/pipeline/affiliations/phase.py`.
    """
    from application.pipeline.affiliations.phase import run
    from infrastructure.queries.perimeter import PgPerimeterQueries
    from infrastructure.queries.pipeline.address_resolution import PgAddressResolutionQueries
    from infrastructure.queries.pipeline.affiliations import PgAffiliationsQueries

    return run(
        _open_tx,
        PgAddressResolutionQueries(),
        PgAffiliationsQueries(),
        PgPerimeterQueries(),
        log,
    )


def phase_metadata_correction(**kw: Any) -> PhaseMetrics:
    """Persistance des corrections de métadonnées sur les source_publications.

    Séquence, transactions et métriques dans `application/pipeline/metadata_correction/phase.py`.
    """
    from application.pipeline.metadata_correction.phase import run
    from infrastructure.queries.pipeline.metadata_correction import PgMetadataCorrectionQueries

    return run(_open_tx, PgMetadataCorrectionQueries(), log)


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

    Séquence, transactions et métriques dans `application/pipeline/publications/phase.py`.
    """
    from application.pipeline.publications.phase import run
    from infrastructure.queries.pipeline.address_pub_count import PgAddressPubCountQueries
    from infrastructure.queries.pipeline.publications_reconciliation import (
        PgPublicationsReconciliationQueries,
    )
    from infrastructure.repositories import publication_repository

    return run(
        _open_tx,
        PgPublicationsReconciliationQueries(),
        PgAddressPubCountQueries(),
        log,
        publication_repo_factory=publication_repository,
        rebuild_publications=bool(kw.get("rebuild_publications")),
    )


def phase_relations(**kw: Any) -> PhaseMetrics:
    """Population des relations sémantiques entre publications distinctes.

    Tourne après `publications` : les `source_publications` sont rattachées et les DOI
    cibles résolus en `publication_id`. Reconstruit `publication_relations` depuis les
    relations déclarées par les sources (DataCite `meta.related_identifiers`, Crossref
    `meta.relation`). Les relations même-œuvre (versions, variantes, pièces) relèvent de
    la déduplication (`metadata_correction`), pas d'ici.
    """
    from application.pipeline.relations.phase import run
    from infrastructure.queries.pipeline.relations import PgPublicationRelationsQueries

    return run(_open_tx, PgPublicationRelationsQueries(), log)


def phase_persons(**kw: Any) -> PhaseMetrics:
    """Rattachement et création des personnes, phase ordre-indépendante.

    L'orchestrateur enchaîne, sur une seule transaction : `enforce` (réapplique les épinglages
    admin), `reset` (réinitialise les attributions dérivées — arbitrage des conflits d'identifiant,
    recompute cross-source), `match` (rattache sans créer), `create` (crée les signatures restées
    non liées, cross-source rejoué d'abord), `populate` (régénère les formes de nom canoniques),
    `purge` (re-orpheline les formes devenues ambiguës et supprime les personnes vidées). Exclut les
    publications hors-scope (cf domain/publications/scope).

    Séquence, transaction et métriques dans `application/pipeline/persons/phase.py`.
    """
    from application.pipeline.persons.phase import run
    from infrastructure.queries.pipeline.person_name_forms import PgPersonNameFormsQueries
    from infrastructure.queries.pipeline.persons_matching import PgPersonsMatchingQueries
    from infrastructure.repositories import authorship_repository, person_repository

    return run(
        _open_tx,
        PgPersonsMatchingQueries(),
        PgPersonNameFormsQueries(),
        log,
        person_repo_factory=person_repository,
        authorship_repo_factory=authorship_repository,
    )


def phase_authorships(**kw: Any) -> PhaseMetrics:
    """Construction de la table de vérité `authorships`.

    Consolide les `source_authorships` en authorships canoniques (une entrée par couple publication × personne), avec `in_perimeter` consolidé ; les structures dérivent de la matview `authorship_structures`.

    Phase source-agnostique : `--sources` n'est pas propagé. Une source_authorship peut être touchée par d'autres voies que sa propre normalisation (re-population d'affiliations, refresh_from_sources, etc.) — toutes les sources doivent être reconsolidées à chaque run.

    Le build est incrémental et convergent dans tous les modes (add + prune + recompute des attributs en une passe) : aucune purge routinière. La purge complète de la table est disponible en récupération via `run_pipeline --rebuild-authorships`.

    Séquence, transactions et métriques dans `application/pipeline/authorships/phase.py`.
    """
    from application.pipeline.authorships.phase import run
    from infrastructure.queries.pipeline.authorships_build import PgAuthorshipsBuildQueries
    from infrastructure.queries.pipeline.pub_counts import PgPubCountsQueries
    from infrastructure.queries.pipeline.purge_orphan_publications import (
        PgPurgeOrphanPublicationsQueries,
    )

    return run(
        _open_tx,
        PgAuthorshipsBuildQueries(),
        PgPurgeOrphanPublicationsQueries(),
        PgPubCountsQueries(),
        log,
        rebuild_authorships=bool(kw.get("rebuild_authorships")),
    )


def phase_countries(mode: Any = "full", **kw: Any) -> PhaseMetrics:
    """Detection des pays des adresses et recalcul sur les publications.

    Séquence, transactions et métriques dans `application/pipeline/countries/phase.py`.
    """
    from application.pipeline.countries.phase import run
    from infrastructure.queries.pipeline.countries import PgCountryQueries

    return run(
        _open_tx,
        PgCountryQueries(),
        log,
        retry_empty=MODES[mode].retry_empty_country_suggestions,
    )


def phase_subjects(**kw: Any) -> PhaseMetrics:
    """Sujets / mots-clés : ingestion + recalcul des co-occurrences.

    Deux étapes enchaînées, indissociables :

    1. **Ingestion** (`subjects` + `publication_subjects`) — incrémentale et
       publication-centrée : ne ré-ingère que les publications dont le contenu
       canonique a changé depuis leur dernière ingestion (`publications.updated_at`
       > `max(publication_subjects.created_at)`), à partir des `topics` de leurs
       `source_publications`. Purge en fin les sujets devenus orphelins (plus aucun
       lien). Cf. `application/pipeline/subjects/ingestion.py`.

    2. **Co-occurrences** (`subjects.usage_count` + matview `subject_cooccurrences`)
       — recalcule l'usage de chaque sujet et rafraîchit la matview des
       paires de sujets co-présents sur une même publication.

    Aucun filtre périmètre ici : la phase `authorships` a purgé en amont les
    publications orphelines (zéro authorship), donc `publication_subjects` ne
    porte plus que du périmètre et `usage_count` / `subject_cooccurrences` en
    héritent. Ne pas re-filtrer (cf. `purge_orphan_publications`).

    Idempotente. `--rebuild-subjects` force une ré-ingestion complète (toutes les
    publications, pas seulement les modifiées), pour propager une évolution des
    règles d'ingestion sur tout le stock.

    Séquence, transactions et métriques dans `application/pipeline/subjects/phase.py`.
    """
    from application.pipeline.subjects.phase import run
    from infrastructure.queries.pipeline.subjects import PgSubjectsIngestionQueries

    return run(_open_tx, PgSubjectsIngestionQueries(), log, rebuild=bool(kw.get("rebuild_subjects")))


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
    `_biblio` ; `theses` a le sien (sans repos journal/publisher)."""
    from application.pipeline.normalize.normalize_crossref import CrossrefNormalizer
    from application.pipeline.normalize.normalize_datacite import DataciteNormalizer
    from application.pipeline.normalize.normalize_hal import HalNormalizer
    from application.pipeline.normalize.normalize_openalex import OpenalexNormalizer
    from application.pipeline.normalize.normalize_scanr import ScanrNormalizer
    from application.pipeline.normalize.normalize_theses import ThesesNormalizer
    from application.pipeline.normalize.normalize_wos import WosNormalizer
    from infrastructure.queries.pipeline.normalize.authorships import PgAuthorshipsBatchQueries
    from infrastructure.queries.pipeline.normalize.source_publications import (
        PgSourcePublicationQueries,
    )
    from infrastructure.queries.pipeline.staging import PgStagingQueries
    from infrastructure.repositories import (
        journal_repository,
        publication_repository,
        publisher_repository,
    )

    def _biblio(cls: Any) -> Callable[[Any], Any]:
        return lambda conn: cls(
            conn,
            log,
            PgStagingQueries(),
            PgSourcePublicationQueries(),
            journal_repo_factory=journal_repository,
            publisher_repo_factory=publisher_repository,
            publication_repo_factory=publication_repository,
            authorship_queries=PgAuthorshipsBatchQueries(),
        )

    return {
        "theses": lambda conn: ThesesNormalizer(
            conn,
            log,
            PgStagingQueries(),
            PgSourcePublicationQueries(),
            publication_repo_factory=publication_repository,
            batch_queries=PgAuthorshipsBatchQueries(),
        ),
        "crossref": _biblio(CrossrefNormalizer),
        "datacite": _biblio(DataciteNormalizer),
        "scanr": _biblio(ScanrNormalizer),
        "hal": _biblio(HalNormalizer),
        "openalex": _biblio(OpenalexNormalizer),
        "wos": _biblio(WosNormalizer),
    }


def _run_normalize(source: str, build: Callable[[Any], Any]) -> dict[str, object]:
    from infrastructure.db.engine import get_sync_engine

    log.info("▶ normalize_%s", source)
    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        stats = build(conn).run()
    finally:
        conn.close()
    duration = time.time() - t0
    log.info("✓ normalize_%s terminé en %.1fs", source, duration)
    return _normalize_row(source, stats, duration)


def _run_enrich_journals_from_openalex() -> PhaseMetrics:
    from application.pipeline.publishers_journals.enrich_journals_from_openalex import (
        run_enrich_journals_from_openalex,
    )
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.repositories import journal_repository
    from infrastructure.sources.api_limits import DOAJ_DELAY
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )
    from infrastructure.sources.config import (
        get_api_base_urls,
        get_openalex_api_key,
        get_polite_pool_email_optional,
    )
    from infrastructure.sources.openalex.journal_enrichment import fetch_sources_batch

    log.info("▶ enrich_journals_from_openalex")
    t0 = time.time()
    conn = get_sync_engine().connect()
    # Seuil 3 : trois batches consécutifs à bout de budget (429) suffisent à conclure
    # que le quota OpenAlex quotidien est épuisé et à reporter le reste au prochain run.
    breaker = SourceCircuitBreaker("openalex sources", threshold=3)
    token = set_current_breaker(breaker)
    try:
        api_key = get_openalex_api_key(conn)
        mailto = get_polite_pool_email_optional(conn) or ""
        sources_api = get_api_base_urls()["openalex_sources"]
        metrics = run_enrich_journals_from_openalex(
            conn,
            log,
            journal_repo=journal_repository(conn),
            fetch_batch=lambda oa_ids: fetch_sources_batch(
                oa_ids, openalex_sources_api=sources_api, api_key=api_key, mailto=mailto
            ),
            breaker=breaker,
            rate_delay=DOAJ_DELAY,
        )
    finally:
        reset_current_breaker(token)
        conn.close()
    log.info("✓ enrich_journals_from_openalex terminé en %.1fs", time.time() - t0)
    _signal_if_tripped(metrics, breaker)
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
        journal_repo = journal_repository(conn)
        last = journal_repo.doaj_last_import_at()
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
            log,
            journal_repo=journal_repo,
            rows=read_doaj_dump_rows(str(_DOAJ_DUMP_PATH)),
        )
    finally:
        conn.close()
    log.info("✓ enrich_journals_from_doaj terminé en %.1fs", time.time() - t0)
    return PhaseMetrics(extras={"matched": stats.matched})


# ── Extracteurs sources (Volet 0 — sweep subprocess → imports) ──


def _run_extractor(extractor: Any, args: Any) -> PhaseMetrics:
    """Exécute un extracteur avec un circuit-breaker de source (seuil 5).

    Pose le breaker dans la ContextVar (lu par le helper HTTP sync) et le passe à
    `run` (consulté par les boucles `extract_all` pour stopper une source à bout de
    budget). Seuil 5 : extracteurs séquentiels, pas de batch concurrent comme le
    cross-import (qui est à 10).
    """
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )

    breaker = SourceCircuitBreaker(extractor.SOURCE, threshold=5)
    token = set_current_breaker(breaker)
    try:
        metrics = extractor.run(args, breaker=breaker)
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


def _run_fetch_missing_hal_by_id() -> PhaseMetrics:
    """Cross-import HAL par hal-id (OpenAlex/ScanR) : documents absents du staging."""
    from application.pipeline.cross_imports.fetch_missing_hal import fetch_missing_hal_by_id
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
    from application.pipeline.cross_imports.fetch_missing_hal import fetch_missing_hal_by_nnt
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

    from application.ports.pipeline.cross_imports.fetch_missing_doi import (
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
    from application.pipeline.cross_imports.fetch_missing_doi import run_async
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


def phase_oa_status(**kw: Any) -> PhaseMetrics:
    """Enrichissement `publications.oa_status` via Unpaywall (per-publication).

    Incrémentale et auto-bornée (staleness + cap `MAX_PER_RUN`) : le backlog des
    jamais-vérifiées s'écoule run après run. Tourne dans tous les modes.

    Unpaywall exige l'email polite pool : sans lui, la phase est sautée proprement.

    Séquence et métriques dans `application/pipeline/oa_status/phase.py` ; ici, le câblage.
    """
    import asyncio

    import httpx

    from application.pipeline.oa_status.phase import run
    from application.pipeline.signals import filter_configured
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.pipeline.oa_status import PgOaStatusQueries
    from infrastructure.repositories import publication_repository
    from infrastructure.sources.config import get_api_base_urls, get_polite_pool_email_optional
    from infrastructure.sources.unpaywall import fetch_oa_status

    metrics = PhaseMetrics()
    if not filter_configured(
        ["unpaywall"],
        metrics,
        credentials_missing=_credentials_missing,
        logger=log,
        phase="oa_status",
    ):
        return metrics

    conn = get_sync_engine().connect()
    try:
        base_url = get_api_base_urls()["unpaywall"]
        email = get_polite_pool_email_optional(conn) or ""

        async def fetcher(client: httpx.AsyncClient, doi: str) -> str | None:
            return await fetch_oa_status(client, doi, base_url=base_url, email=email, logger=log)

        metrics.merge(
            asyncio.run(
                run(
                    conn,
                    PgOaStatusQueries(),
                    log,
                    publication_repo=publication_repository(conn),
                    fetcher=fetcher,
                )
            )
        )
    finally:
        conn.close()
    return metrics


# Registre des phases : l'implémentation de chacune. L'ordre d'exécution vient de
# `PHASE_ORDER`, source de vérité unique ; ce registre ne fournit que les fonctions,
# validées comme couvrant exactement cet ordre.
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
        "Le registre des phases de l'orchestrateur et `PHASE_ORDER` divergent : "
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


def _build_arg_parser() -> argparse.ArgumentParser:
    """Parseur des arguments de la CLI pipeline."""
    parser = argparse.ArgumentParser(description="Orchestrateur pipeline bibliométrique")
    parser.add_argument(
        "--from", dest="from_phase", metavar="PHASE", help="Reprendre depuis cette phase"
    )
    parser.add_argument("--only", metavar="PHASE", help="Exécuter uniquement cette phase")
    parser.add_argument("--list", action="store_true", help="Lister les phases disponibles")
    parser.add_argument("--dry-run", action="store_true", help="Afficher les étapes sans exécuter")
    parser.add_argument(
        "--mode", choices=list(MODE_NAMES), default="full", help="Mode d'exécution (défaut: full)"
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
    parser.add_argument(
        "--rebuild-authorships",
        action="store_true",
        help="Avant la phase authorships, purge complète de la table puis reconstruction "
        "depuis zéro (filet anti-divergence, en récupération).",
    )
    parser.add_argument(
        "--rebuild-subjects",
        action="store_true",
        help="À la phase subjects, ré-ingère toutes les publications (pas seulement les "
        "modifiées) pour propager une évolution des règles d'ingestion sur tout le stock.",
    )
    return parser


def _print_phase_list() -> None:
    """Affiche les phases disponibles (`--list`)."""
    print("Phases disponibles :")
    for i, (name, fn) in enumerate(PHASES, 1):
        doc = fn.__doc__.strip().split("\n")[0] if fn.__doc__ else ""
        print(f"  {i}. {name:15s} — {doc}")


def _select_phases_to_run(
    args: argparse.Namespace,
) -> list[tuple[str, Callable[..., PhaseMetrics]]]:
    """Phases à exécuter selon `--only` / `--from` (sinon toutes). Sort en erreur sur phase inconnue."""
    if args.only:
        if args.only not in PHASE_NAMES:
            print(f"Phase inconnue : {args.only}. Phases : {', '.join(PHASE_NAMES)}")
            sys.exit(1)
        return [(n, fn) for n, fn in PHASES if n == args.only]
    if args.from_phase:
        if args.from_phase not in PHASE_NAMES:
            print(f"Phase inconnue : {args.from_phase}. Phases : {', '.join(PHASE_NAMES)}")
            sys.exit(1)
        return PHASES[PHASE_NAMES.index(args.from_phase) :]
    return list(PHASES)


def _print_dry_run(phases_to_run: list[tuple[str, Callable[..., PhaseMetrics]]]) -> None:
    """Affiche les phases qui seraient exécutées (`--dry-run`), sans rien lancer."""
    for name, fn in phases_to_run:
        doc = fn.__doc__.strip().split("\n")[0] if fn.__doc__ else ""
        print(f"  [{name}] {doc}")
    print("\n(dry-run : rien n'a été exécuté)")


def _run_one_phase(
    name: str,
    fn: Callable[..., PhaseMetrics],
    *,
    index: int,
    total: int,
    args: argparse.Namespace,
    sources: set[str],
    recorder: Any,
    pipeline_started_at: str,
) -> tuple[str, float]:
    """Exécute une phase : statut, appel, capture d'observabilité. Rend `(nom, durée)`.

    Une interruption utilisateur ou une `RuntimeError` est enregistrée puis termine le process
    (reprise possible via `--from <phase>`)."""
    # Injecte le nom de phase dans tous les records émis pendant `fn` (logger `normalize:` plutôt
    # que `pipeline:`), y compris depuis les extracteurs threadés qui héritent du contexte.
    phase_token = set_log_phase(name)
    try:
        log.info("─" * 40)
        log.info("%s%s", PHASE_MARKER, name)
        log.info("─" * 40)
        write_status(
            mode=args.mode,
            phase=name,
            started_at=pipeline_started_at,
            phases_done=index,
            phases_total=total,
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
                rebuild_authorships=args.rebuild_authorships,
                rebuild_subjects=args.rebuild_subjects,
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
            clear_status()
            sys.exit(1)

        duration = time.time() - t0_phase
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
        return (name, duration)
    finally:
        reset_log_phase(phase_token)


def _execute_phases(
    args: argparse.Namespace, phases_to_run: list[tuple[str, Callable[..., PhaseMetrics]]]
) -> None:
    """Déroule la séquence des phases avec observabilité par run, puis le récapitulatif de fin."""
    from infrastructure.observability.phase_executions import start_run

    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    # Sources effectivement interrogées : wos est opt-in (`--include-wos`).
    effective_sources = sorted(sources - {"wos"}) if not args.include_wos else sorted(sources)
    log.info("Sources : %s", ", ".join(effective_sources))

    # Observabilité par phase : run_id de séquence, capture entrée/sortie + statut.
    recorder = start_run(mode=args.mode, sources=effective_sources)
    if recorder.run_id is not None:
        log.info("%s%d", RUN_MARKER, recorder.run_id)

    # Matérialise `perimeter_structures` avant toute phase : l'extraction lit le périmètre
    # d'extraction dès la première phase ; `affiliations` la rematérialise ensuite, à son démarrage.
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.queries.perimeter import refresh_perimeter_structures

    with get_sync_engine().connect() as perimeter_conn:
        refresh_perimeter_structures(perimeter_conn)
        perimeter_conn.commit()
    log.info("perimeter_structures matérialisées")

    t0_total = time.time()
    pipeline_started_at = datetime.datetime.now().isoformat(timespec="seconds")
    total = len(phases_to_run)
    phase_results = [
        _run_one_phase(
            name,
            fn,
            index=i,
            total=total,
            args=args,
            sources=sources,
            recorder=recorder,
            pipeline_started_at=pipeline_started_at,
        )
        for i, (name, fn) in enumerate(phases_to_run)
    ]

    elapsed_total = time.time() - t0_total
    recorder.close()
    clear_status()
    log.info("=" * 60)
    log.info("%s en %.0fs (%.1f min)", RUN_END_MARKER, elapsed_total, elapsed_total / 60)
    if recorder.run_id is not None:
        log.info("Run #%d — récapitulatif par phase :", recorder.run_id)
        for phase_name, phase_duration in phase_results:
            log.info("  %-22s %7.1fs", phase_name, phase_duration)
    log.info("=" * 60)


def main() -> None:
    _install_sigterm_handler()
    # Nettoie un status.json orphelin (PID mort : SIGKILL, crash, OOM) laissé par un run précédent —
    # sinon le prochain lecteur verrait un statut fantôme jusqu'à notre premier write_status().
    read_status()
    args = _build_arg_parser().parse_args()

    if args.list:
        _print_phase_list()
        return

    # Mutex pipeline (évite deadlocks cron vs lancement manuel).
    try:
        acquire_pipeline_lock(force=args.force)
    except PipelineAlreadyRunningError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    phases_to_run = _select_phases_to_run(args)
    log.info("=" * 60)
    log.info("PIPELINE BIBLIOMÉTRIQUE — mode %s", args.mode)
    log.info("Phases : %s", " → ".join(n for n, _ in phases_to_run))
    log.info("=" * 60)

    if args.dry_run:
        _print_dry_run(phases_to_run)
        return

    _execute_phases(args, phases_to_run)


if __name__ == "__main__":
    main()
