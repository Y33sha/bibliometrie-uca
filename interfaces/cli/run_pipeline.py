#!/usr/bin/env python
"""Orchestrateur du pipeline bibliométrique : câblage des phases et séquence d'exécution.

Chaque phase est une fonction `phase_<nom>` qui construit ses adaptateurs, ouvre ses connexions et délègue la séquence à `application/pipeline/<phase>/`. `PHASE_ORDER` fixe l'ordre d'exécution et `_PHASE_FUNCTIONS` associe chaque nom à sa fonction.

`run_pipeline --help` donne les options et la liste des phases.
"""

import argparse
import asyncio
import contextlib
import datetime
import faulthandler
import io
import logging
import signal
import sys
import tempfile
import textwrap
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from sqlalchemy import Connection

    from application.ports.pipeline.extract.fetch_stale import FetchStaleAdapter
    from application.ports.pipeline.fetch_missing.doi import (
        AsyncFetchMissingDoiAdapter,
    )

from application.pipeline.libelles import accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.modes import MODE_NAMES, MODES
from application.pipeline.normalize.base import NormalizeStats, SourceNormalizer
from application.pipeline.normalize.bibliographic import BibliographicNormalizer
from application.pipeline.phase_order import EXTRA_PHASES, PHASE_LIBELLES, PHASE_ORDER
from application.pipeline.progression import ecrire_hors_barre, set_flux_barres
from application.pipeline.signals import signal_source_unavailable
from application.ports.pipeline.circuit_breaker import CircuitBreaker, SourceUnavailableError
from domain.dates import date_to_french
from domain.sources.registry import ALL_SOURCES_SET
from infrastructure import PROJECT_ROOT
from infrastructure.observability.log import (
    PHASE_MARKER,
    RUN_END_MARKER,
    RUN_MARKER,
    configure_root_logging,
    console_stream,
    reset_log_phase,
    set_console_writer,
    set_log_phase,
    setup_logger,
)
from infrastructure.observability.phase_executions import PhaseExecutionRecorder
from infrastructure.pipeline_lock import PipelineAlreadyRunningError, pipeline_lock
from infrastructure.sources.circuit_breaker import SourceCircuitBreaker

# `setup_logger` attache un FileHandler sur `logs/pipeline.log` quand `LOG_TO_FILE=true`.
log = setup_logger("pipeline", str(PROJECT_ROOT / "logs"))

set_console_writer(ecrire_hors_barre)
set_flux_barres(console_stream())

# Seuil du root logger, où émettent les modules qui appellent `logging.getLogger(__name__)` :
# les bibliothèques tierces y écrivent trop d'information pour la laisser passer.
configure_root_logging(logging.WARNING)


# Un normaliseur se construit sur la connexion de sa phase, dont ses adaptateurs dépendent.
type ConstructeurNormalizer = Callable[[Connection], SourceNormalizer]


class Extracteur(Protocol):
    """Point d'entrée commun des extracteurs, seul que l'orchestrateur appelle.

    Chaque source a son type de configuration et son type d'adapter ; ce protocole les laisse aux extracteurs.
    """

    def run(
        self,
        args: argparse.Namespace,
        *,
        breaker: CircuitBreaker | None = None,
    ) -> PhaseMetrics: ...


# Une phase reçoit les options du run et rend ses métriques.
type Phase = Callable[[RunOptions], PhaseMetrics]

# Un extracteur se construit sur la connexion de sa phase et le journal scopé à sa source.
type ConstructeurExtracteur = Callable[[Connection, logging.Logger], Extracteur]


@dataclass(frozen=True, slots=True)
class RunOptions:
    """Options d'un run, telles que la ligne de commande les pose, remises à chaque phase.

    Toutes les phases reçoivent les mêmes options et lisent celles qui les concernent.

    `sources` vaut `None` quand le run n'en restreint aucune ; les phases qui attendent une liste explicite y substituent l'ensemble des sources connues.
    """

    mode: str = "full"
    sources: set[str] | None = None
    year: int | None = None
    start_year: int | None = None
    include_wos: bool = False
    rebuild_publications: bool = False
    rebuild_authorships: bool = False
    rebuild_subjects: bool = False
    raw_store: bool = False


def _open_tx() -> "AbstractContextManager[Connection]":
    """Fabrique de transaction gérée (port `OpenTransaction`) : commit sur succès, rollback sur erreur, fermeture, et tolérance aux commits par lots."""
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.db.transaction import managed_transaction

    return managed_transaction(get_sync_engine())


def phase_extract(options: RunOptions) -> PhaseMetrics:
    """Extraction des sources vers staging.

    `application/pipeline/modes.py` porte la policy du mode : sources retenues et stratégie d'années. Séquence, parallélisme et métriques dans `application/pipeline/extract/phase.py` ; ici, le câblage : registre des adaptateurs, primitif de parallélisme, lecture de la date de dernière extraction.
    """
    from application.pipeline.extract.phase import run
    from infrastructure.observability.phase_executions import get_last_extract_date
    from infrastructure.parallel import run_parallel

    registry = _extractors()

    def extract_one(source: str, args: argparse.Namespace) -> PhaseMetrics:
        return _run_extract(source, registry[source], args)

    return run(
        mode=options.mode,
        sources=set(options.sources) if options.sources else None,
        year=options.year,
        start_year=options.start_year,
        include_wos=options.include_wos,
        extract_one=extract_one,
        run_parallel=run_parallel,
        get_last_extract_date=get_last_extract_date,
        logger=log,
    )


def phase_resolve_ra(options: RunOptions) -> PhaseMetrics:
    """Résout la Registration Agency des préfixes DOI (`doi.org/ra`) avant `fetch_missing`.

    La Registration Agency dit laquelle des deux API connaît un DOI, Crossref ou DataCite : `fetch_missing` adresse ensuite chaque DOI à la bonne. La phase `publishers_journals` reprend les préfixes restants via les API `/prefixes`.

    Séquence et métriques dans `application/pipeline/resolve_ra/phase.py` ; ici, le câblage : connexion, circuit-breaker, user-agent.
    """
    from application.pipeline.resolve_ra.phase import run
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.pipeline.doi_prefixes import PgDoiPrefixesQueries
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )
    from infrastructure.sources.config import get_polite_pool_email_optional
    from infrastructure.sources.doi_org.registration_agency import resolve_ra
    from infrastructure.sources.polite_pool import build_user_agent

    conn = get_sync_engine().connect()
    # Circuit-breaker de doi.org/ra : le client HTTP lit la ContextVar, `run` consulte
    # `breaker.tripped` pour s'arrêter.
    breaker = SourceCircuitBreaker("doi.org/ra")
    token = set_current_breaker(breaker)
    try:
        # doi.org/ra est une API publique : l'adresse du polite pool y est facultative.
        user_agent = build_user_agent(get_polite_pool_email_optional() or "")
        metrics = run(
            log,
            repo=PgDoiPrefixesQueries(conn),
            resolve_ra_fn=lambda doi: resolve_ra(doi, user_agent=user_agent),
            breaker=breaker,
        )
        conn.commit()
    except SourceUnavailableError:
        conn.commit()  # préserve les préfixes résolus avant l'indisponibilité (erreur HTTP, pas SQL)
        metrics = PhaseMetrics()
        signal_source_unavailable(metrics, "doi.org/ra", logger=log, phase="resolve_ra")
    finally:
        reset_current_breaker(token)
        conn.close()
    _signal_if_tripped(metrics, breaker)
    return metrics


def phase_fetch_missing(options: RunOptions) -> PhaseMetrics:
    """Rattrapage des documents repérés dans une source mais absents d'une autre.

    Le cross-import HAL télécharge les documents que HAL détient et que le staging n'a pas, repérés par leur hal-id dans OpenAlex et ScanR, ou par le NNT d'une thèse soutenue. Le cross-import par DOI cherche ensuite, pour chaque source cible, les DOI vus dans les autres sources et absents de la sienne. WoS est opt-in (`--include-wos`) : crédit API limité, source exclue par défaut.

    Les deux se bornent d'eux-mêmes : un identifiant introuvable est marqué `not_found_at` dans le staging, un DOI absent d'une source reçoit un délai avant nouvelle tentative dans `doi_lookups`.

    Séquence, parallélisme et métriques dans `application/pipeline/fetch_missing/phase.py`.
    """
    from application.pipeline.fetch_missing.phase import run
    from infrastructure.parallel import run_parallel

    return run(
        mode=options.mode,
        sources=set(options.sources) if options.sources else None,
        include_wos=options.include_wos,
        fetch_hal_by_id=_run_fetch_missing_hal_by_id,
        fetch_hal_by_nnt=_run_fetch_missing_hal_by_nnt,
        fetch_doi_one=_run_fetch_missing_doi,
        run_parallel=run_parallel,
        credentials_missing=_credentials_missing,
        logger=log,
    )


def phase_fetch_stale(options: RunOptions) -> PhaseMetrics:
    """Rafraîchit les rows à `last_seen_at` ancien et marque les disparues.

    Chaque row est réinterrogée par son identifiant natif (`staging.source_id`), avec ou sans DOI : trouvée, son `last_seen_at` et son `raw_data` sont rafraîchis ; absente de sa source, elle reçoit un `disappeared_at` ; sur échec réseau, elle attend le run suivant. Le seuil `STALE_REFRESH_AFTER_DAYS` étale la charge, chaque passe ne ramassant que les rows qui viennent de franchir le délai.

    La fenêtre d'années du run (`start_year`/`year`, via `source_publications.pub_year`) borne le rafraîchissement aux années que le run moissonne. `theses` ramène tout son historique, comme à l'extraction, sauf sous `--year`. WoS est opt-in (`--include-wos`).

    Séquence et métriques dans `application/pipeline/extract/fetch_stale.py::run_phase`.
    """
    from application.pipeline.extract.fetch_stale import run_phase

    return run_phase(
        sources=set(options.sources) if options.sources else None,
        include_wos=options.include_wos,
        year=options.year,
        start_year=options.start_year,
        refresh_one=_run_fetch_stale,
        credentials_missing=_credentials_missing,
        get_years_for_window=_get_years_for_window,
        logger=log,
    )


def _credentials_missing(source: str) -> str | None:
    """Motif d'absence des identifiants d'une source, ou `None` si elle est configurée. Injecté aux phases qui interrogent une API tierce."""
    from infrastructure.sources.config import source_credentials_missing

    return source_credentials_missing(source)


def _get_years_for_window(start_year: int | None) -> list[int] | None:
    """Années de la fenêtre du run, de `start_year` à l'année courante. Injecté aux phases qui bornent leurs requêtes par année."""
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.config import get_years

    with get_sync_engine().connect() as conn:
        return get_years(conn, start_year)


def phase_fetch_truncated(options: RunOptions) -> PhaseMetrics:
    """Re-télécharge les works OpenAlex tronqués à 100 auteurs.

    L'API OpenAlex plafonne la liste des auteurs à 100 par réponse. La phase repère les lignes staging openalex à 100 auteurs restées `processed=FALSE`, et les re-télécharge en paginant leurs auteurs. Sa position, après `fetch_stale` et avant `normalize`, lui donne à voir les works tronqués que les phases de rattrapage viennent de ramener.

    Séquence et métriques dans `application/pipeline/extract/fetch_truncated.py`.
    """
    import asyncio

    from application.pipeline.extract.fetch_truncated import refetch
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.openalex.fetch_truncated import PgOpenalexFetchTruncatedAdapter

    sources = options.sources if options.sources is not None else set(ALL_SOURCES_SET)
    # La phase repère les seules lignes openalex à 100 auteurs restées à traiter : elle tourne
    # dans tous les modes, dès qu'openalex fait partie des sources.
    if "openalex" not in sources:
        return PhaseMetrics()
    conn = get_sync_engine().connect()
    try:
        return asyncio.run(refetch(conn, PgOpenalexFetchTruncatedAdapter(), log))
    finally:
        conn.close()


def phase_normalize(options: RunOptions) -> PhaseMetrics:
    """Normalisation du staging vers les tables sources.

    Écrit les `source_publications` avec leurs métadonnées — résumé, mots-clés, sujets, références — et leurs signatures, en laissant `publication_id` à NULL : la phase `publications` assigne le document à sa publication. Le `raw_data` du staging est vidé après traitement. Pour HAL, les structures sont enrichies et les ORCID et IdRef extraits du TEI.

    Séquence, nettoyage et VACUUM dans `application/pipeline/normalize/phase.py`.
    """
    from application.pipeline.normalize.phase import run

    registry = _normalize_builders(archive=options.raw_store)

    def normalize_one(source: str) -> dict[str, object]:
        return _run_normalize(source, registry[source])

    return run(
        sources=options.sources if options.sources is not None else set(ALL_SOURCES_SET),
        mode=options.mode,
        ordered_sources=list(registry),
        normalize_one=normalize_one,
        prune_disappeared=_run_prune_disappeared,
        cleanup_orphan_identities=_run_cleanup_orphan_identities,
        vacuum_staging=_vacuum_staging,
        logger=log,
    )


def _run_prune_disappeared() -> int:
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.pipeline.normalize.staging import delete_disappeared_source_publications

    conn = get_sync_engine().connect()
    try:
        n = delete_disappeared_source_publications(conn)
        conn.commit()
    finally:
        conn.close()
    if n:
        log.info(
            "%s (disparus de leur source)", accord(n, "document supprimé", "documents supprimés")
        )
    return n


def _run_cleanup_orphan_identities() -> None:
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.pipeline.normalize.authorships import delete_orphan_identities

    conn = get_sync_engine().connect()
    try:
        delete_orphan_identities(conn)
        conn.commit()
    finally:
        conn.close()


def _vacuum_staging(full: bool = False) -> None:
    """VACUUM du staging, complet en mode `full` et simple sinon.

    La normalisation vide `staging.raw_data`, un JSONB volumineux. Le VACUUM simple marque l'espace réutilisable, le VACUUM complet réécrit la table et le rend au système. Ce dernier prend un verrou exclusif sur le staging, le temps de son exécution.
    """
    from sqlalchemy import text

    from infrastructure.db.engine import get_sync_engine

    sql = "VACUUM FULL staging" if full else "VACUUM staging"
    with get_sync_engine().connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(sql))


def phase_publishers_journals(options: RunOptions) -> PhaseMetrics:
    """Enrichissement du référentiel `journals`.

    `resolve_publishers` rattache chaque préfixe DOI à son éditeur Crossref ou à son repository DataCite, via les API `/prefixes`, pour les préfixes en attente d'éditeur. `enrich_journals_from_openalex` lit dans OpenAlex Sources les frais de publication et le type des revues encore typées `unknown`. `enrich_journals_from_doaj` importe le dump CSV du DOAJ, qui fait autorité sur `is_in_doaj`, quand le dernier import date de plus de trente jours.

    La phase suit `normalize`, qui crée les éditeurs et les revues à enrichir. L'enrichissement des éditeurs eux-mêmes — pays, ROR, type — se lance à la demande, par `interfaces/cli/maintenance/enrich_publishers.py`.

    Séquence, gardes de configuration et métriques dans `application/pipeline/publishers_journals/phase.py`.
    """
    from application.pipeline.publishers_journals.phase import run

    return run(
        resolve_publishers=_run_resolve_publishers,
        enrich_from_openalex=_run_enrich_journals_from_openalex,
        enrich_from_doaj=_run_enrich_journals_from_doaj,
        credentials_missing=_credentials_missing,
        logger=log,
    )


def _signal_if_tripped(metrics: PhaseMetrics, breaker: SourceCircuitBreaker) -> None:
    """Marque la phase en avertissement quand le circuit-breaker d'une source a coupé, après une série de 429 ou de 5xx. Les phases de rattrapage étant idempotentes, le run suivant reprend les documents non traités."""
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
    from infrastructure.pipeline.doi_prefixes import PgDoiPrefixesQueries
    from infrastructure.pipeline.publishers import PgPublisherGatewayQueries
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )
    from infrastructure.sources.config import get_polite_pool_email_optional
    from infrastructure.sources.crossref.prefixes import fetch_crossref_prefix
    from infrastructure.sources.datacite.prefixes import fetch_datacite_prefix
    from infrastructure.sources.polite_pool import build_user_agent

    conn = get_sync_engine().connect()
    breaker = SourceCircuitBreaker("crossref/datacite prefixes")
    token = set_current_breaker(breaker)
    try:
        user_agent = build_user_agent(get_polite_pool_email_optional() or "")
        metrics = run_resolve_publishers(
            log,
            repo=PgDoiPrefixesQueries(conn),
            publisher_repo=PgPublisherGatewayQueries(conn),
            fetch_crossref_prefix_fn=lambda prefix: fetch_crossref_prefix(
                prefix, user_agent=user_agent
            ),
            fetch_datacite_prefix_fn=lambda prefix: fetch_datacite_prefix(
                prefix, user_agent=user_agent
            ),
            breaker=breaker,
        )
        conn.commit()
    except SourceUnavailableError:
        conn.commit()  # préserve les préfixes résolus avant l'indisponibilité (erreur HTTP, pas SQL)
        metrics = PhaseMetrics()
        signal_source_unavailable(
            metrics, "crossref/datacite prefixes", logger=log, phase="publishers_journals"
        )
    finally:
        reset_current_breaker(token)
        conn.close()
    _signal_if_tripped(metrics, breaker)
    return metrics


def phase_affiliations(options: RunOptions) -> PhaseMetrics:
    """Rattachement des signatures aux structures du périmètre, par leurs adresses.

    Séquence, transactions et métriques dans `application/pipeline/affiliations/phase.py`.
    """
    from application.pipeline.affiliations.phase import run
    from infrastructure.pipeline.affiliations.address_resolution import (
        PgAddressResolutionQueries,
    )
    from infrastructure.pipeline.affiliations.in_perimeter import PgAffiliationsQueries
    from infrastructure.pipeline.perimeter import PgPerimeterStructuresQueries

    return run(
        _open_tx,
        PgAddressResolutionQueries(),
        PgAffiliationsQueries(),
        PgPerimeterStructuresQueries(),
        log,
    )


def phase_metadata_correction(options: RunOptions) -> PhaseMetrics:
    """Correction des métadonnées des documents sources.

    Séquence, transactions et métriques dans `application/pipeline/metadata_correction/phase.py`.
    """
    from application.pipeline.metadata_correction.phase import run
    from infrastructure.pipeline.metadata_correction import PgMetadataCorrectionQueries

    return run(_open_tx, PgMetadataCorrectionQueries(), log)


def phase_publications(options: RunOptions) -> PhaseMetrics:
    """Assignation des `source_publications` aux publications, en une seule passe.

    Les documents sources modifiés et leur voisinage sont regroupés par composante connexe de leurs clés de confirmation — DOI, NNT, hal_id, PMID, et pour les thèses le couple titre-année. Chaque document rejoint la publication qui ancre sa partition. Rattacher un document, fusionner deux publications ou en scinder une sont trois lectures du même regroupement.

    La phase suit `metadata_correction`, qui a substitué le DOI de concept aux DOI de version DataCite : le regroupement porte alors sur le concept.

    `--rebuild-publications` marque tout le stock à traiter avant le regroupement, qui reprend alors le corpus entier. Sert après une évolution des règles de clés, pour matérialiser les fusions et scissions qu'elles impliquent.

    Séquence, transactions et métriques dans `application/pipeline/publications/phase.py`.
    """
    from application.pipeline.publications.phase import run
    from infrastructure.pipeline.publications.reconciliation import (
        PgPublicationsReconciliationQueries,
    )
    from infrastructure.repositories import publication_repository

    return run(
        _open_tx,
        PgPublicationsReconciliationQueries(),
        log,
        publication_repo_factory=publication_repository,
        rebuild_publications=options.rebuild_publications,
    )


def phase_relations(options: RunOptions) -> PhaseMetrics:
    """Population des relations sémantiques entre publications distinctes.

    La phase suit `publications`, qui a rattaché les documents sources et permet de résoudre les DOI cibles en `publication_id`. Elle reconstruit `publication_relations` depuis les relations que les sources déclarent — `meta.related_identifiers` chez DataCite, `meta.relation` chez Crossref — complétées par les clés partagées et le rapprochement par titre. Les liens entre formes d'une même œuvre relèvent du dédoublonnage, en phase `metadata_correction`.
    """
    from application.pipeline.relations.phase import run
    from infrastructure.pipeline.relations import PgPublicationRelationsQueries

    return run(_open_tx, PgPublicationRelationsQueries(), log)


def phase_persons(options: RunOptions) -> PhaseMetrics:
    """Rattachement des signatures aux personnes, et création des personnes inconnues.

    Une seule transaction enchaîne : la réapplication des épinglages posés par l'administration, la réinitialisation des attributions dérivées, le rattachement des signatures aux personnes connues, la création des personnes pour les signatures restantes, la régénération des formes de nom, puis la purge des formes devenues ambiguës et des personnes vidées. Les publications hors scope sont écartées (`domain/publications/scope`).

    Séquence, transaction et métriques dans `application/pipeline/persons/phase.py`.
    """
    from application.pipeline.persons.phase import run
    from infrastructure.pipeline.persons.matching import PgPersonsMatchingQueries
    from infrastructure.pipeline.persons.name_forms import PgPersonNameFormsQueries
    from infrastructure.repositories import authorship_repository, person_repository

    return run(
        _open_tx,
        PgPersonsMatchingQueries(),
        PgPersonNameFormsQueries(),
        log,
        person_repo_factory=person_repository,
        authorship_repo_factory=authorship_repository,
    )


def phase_authorships(options: RunOptions) -> PhaseMetrics:
    """Construction du référentiel `authorships`.

    Les signatures des sources se consolident en une entrée par couple publication-personne, portant l'appartenance au périmètre ; les structures dérivent de la matview `authorship_structures`.

    La phase reconsolide toutes les sources à chaque run et ignore `--sources` : une signature se trouve modifiée par d'autres voies que sa propre normalisation, comme la repopulation des affiliations ou le recalcul des métadonnées d'une publication.

    Une passe unique ajoute les liens attestés, retire les obsolètes et recalcule les attributs, de sorte que la table converge sans être vidée. `run_pipeline --rebuild-authorships` la purge et la reconstruit depuis zéro, en récupération.

    Séquence, transactions et métriques dans `application/pipeline/authorships/phase.py`.
    """
    from application.pipeline.authorships.phase import run
    from infrastructure.pipeline.authorships.address_pub_count import PgAddressPubCountQueries
    from infrastructure.pipeline.authorships.build import PgAuthorshipsBuildQueries
    from infrastructure.pipeline.authorships.pub_counts import PgPubCountsQueries
    from infrastructure.pipeline.authorships.purge_orphan_publications import (
        PgPurgeOrphanPublicationsQueries,
    )

    return run(
        _open_tx,
        PgAuthorshipsBuildQueries(),
        PgPurgeOrphanPublicationsQueries(),
        PgPubCountsQueries(),
        PgAddressPubCountQueries(),
        log,
        rebuild_authorships=options.rebuild_authorships,
    )


def phase_countries(options: RunOptions) -> PhaseMetrics:
    """Détection des pays des adresses et recalcul sur les publications.

    Séquence, transactions et métriques dans `application/pipeline/countries/phase.py`.
    """
    from application.pipeline.countries.phase import run
    from infrastructure.pipeline.countries import PgCountryQueries

    return run(
        _open_tx,
        PgCountryQueries(),
        log,
        retry_empty=MODES[options.mode].retry_empty_country_suggestions,
    )


def phase_subjects(options: RunOptions) -> PhaseMetrics:
    """Sujets et mots-clés : ingestion, puis recalcul des décomptes.

    L'ingestion reprend les publications dont le contenu a changé depuis leur dernier passage, lit les sujets de leurs documents sources, et purge les sujets restés sans lien. Le recalcul qui suit compte les publications de chaque sujet et rafraîchit la matview des paires de sujets présents sur une même publication.

    La phase `authorships` ayant supprimé les publications sans auteur, `publication_subjects` ne porte que le périmètre, dont les deux décomptes héritent.

    `--rebuild-subjects` reprend toutes les publications, pour propager une évolution des règles d'ingestion sur tout le stock.

    Séquence, transactions et métriques dans `application/pipeline/subjects/phase.py`.
    """
    from application.pipeline.subjects.phase import run
    from infrastructure.pipeline.subjects import PgSubjectsIngestionQueries

    return run(_open_tx, PgSubjectsIngestionQueries(), log, rebuild=options.rebuild_subjects)


def _normalize_row(source: str, stats: NormalizeStats, duration_s: float) -> dict[str, object]:
    """Ligne « par source » de la table d'observabilité de la phase normalize."""
    return {
        "key": source,
        "processed": stats.processed,
        "skipped": stats.skipped,
        "errors": stats.errors,
        "duration_s": round(duration_s, 1),
    }


def _normalize_builders(*, archive: bool = True) -> dict[str, ConstructeurNormalizer]:
    """Constructeur du normaliseur de chaque source, dans l'ordre de `SOURCE_PRIORITY` : la source qui fait le plus autorité passe en premier, les suivantes complètent les métadonnées qu'elle a posées. Les sources bibliographiques partagent le câblage `_biblio` ; `theses` a le sien, sans repository de revue ni d'éditeur."""
    from application.pipeline.normalize.normalize_crossref import CrossrefNormalizer
    from application.pipeline.normalize.normalize_datacite import DataciteNormalizer
    from application.pipeline.normalize.normalize_hal import HalNormalizer
    from application.pipeline.normalize.normalize_openalex import OpenalexNormalizer
    from application.pipeline.normalize.normalize_scanr import ScanrNormalizer
    from application.pipeline.normalize.normalize_theses import ThesesNormalizer
    from application.pipeline.normalize.normalize_wos import WosNormalizer
    from infrastructure.pipeline.journals import PgJournalGatewayQueries
    from infrastructure.pipeline.normalize.authorships import PgAuthorshipsBatchQueries
    from infrastructure.pipeline.normalize.source_publications import (
        PgSourcePublicationQueries,
    )
    from infrastructure.pipeline.normalize.staging import PgStagingQueries
    from infrastructure.pipeline.publishers import PgPublisherGatewayQueries
    from infrastructure.raw_store import NullRawStore, get_raw_store
    from infrastructure.repositories import publication_repository

    raw_store = get_raw_store() if archive else NullRawStore()

    def _biblio(cls: type[BibliographicNormalizer]) -> ConstructeurNormalizer:
        return lambda conn: cls(
            conn,
            log,
            PgStagingQueries(raw_store),
            PgSourcePublicationQueries(),
            journal_repo_factory=PgJournalGatewayQueries,
            publisher_repo_factory=PgPublisherGatewayQueries,
            publication_repo_factory=publication_repository,
            authorship_queries=PgAuthorshipsBatchQueries(),
        )

    return {
        "theses": lambda conn: ThesesNormalizer(
            conn,
            log,
            PgStagingQueries(raw_store),
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


def _run_normalize(source: str, build: ConstructeurNormalizer) -> dict[str, object]:
    from infrastructure.db.engine import get_sync_engine

    t0 = time.time()
    conn = get_sync_engine().connect()
    try:
        stats = build(conn).run()
    finally:
        conn.close()
    return _normalize_row(source, stats, time.time() - t0)


def _run_enrich_journals_from_openalex() -> PhaseMetrics:
    from application.pipeline.publishers_journals.enrich_journals_from_openalex import (
        run_enrich_journals_from_openalex,
    )
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.pipeline.journals import PgJournalGatewayQueries
    from infrastructure.sources.api_params import API_BASE_URLS, DOAJ_DELAY
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )
    from infrastructure.sources.config import (
        get_openalex_api_key,
        get_polite_pool_email_optional,
    )
    from infrastructure.sources.openalex.journal_enrichment import fetch_sources_batch

    conn = get_sync_engine().connect()
    # Trois lots consécutifs en 429 disent le quota OpenAlex du jour épuisé : le reste attend
    # le run suivant.
    breaker = SourceCircuitBreaker("openalex sources", threshold=3)
    token = set_current_breaker(breaker)
    try:
        api_key = get_openalex_api_key()
        mailto = get_polite_pool_email_optional() or ""
        sources_api = API_BASE_URLS["openalex_sources"]
        metrics = run_enrich_journals_from_openalex(
            conn,
            log,
            journal_repo=PgJournalGatewayQueries(conn),
            fetch_batch=lambda oa_ids: fetch_sources_batch(
                oa_ids, openalex_sources_api=sources_api, api_key=api_key, mailto=mailto
            ),
            breaker=breaker,
            rate_delay=DOAJ_DELAY,
        )
    except SourceUnavailableError:
        metrics = PhaseMetrics()
        signal_source_unavailable(
            metrics, "openalex sources", logger=log, phase="publishers_journals"
        )
    finally:
        reset_current_breaker(token)
        conn.close()
    _signal_if_tripped(metrics, breaker)
    return metrics


# Délai minimal entre deux imports du dump CSV du DOAJ, qui fait autorité sur `is_in_doaj`.
_DOAJ_STALE_DAYS = 30


def _run_enrich_journals_from_doaj() -> PhaseMetrics:
    from application.pipeline.publishers_journals.import_journals_from_doaj_dump import (
        run_import_doaj_dump,
    )
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.pipeline.journals import PgJournalGatewayQueries
    from infrastructure.sources.config import get_polite_pool_email_optional
    from infrastructure.sources.doaj.client import fetch_doaj_dump, read_doaj_dump_rows
    from infrastructure.sources.polite_pool import build_user_agent

    conn = get_sync_engine().connect()
    try:
        journal_repo = PgJournalGatewayQueries(conn)
        last = journal_repo.doaj_last_import_at()
        threshold = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=_DOAJ_STALE_DAYS)
        if last is not None and last > threshold:
            prochain = last + datetime.timedelta(days=_DOAJ_STALE_DAYS)
            etape(
                log,
                "Référentiel DOAJ importé le %s : prochain import le %s",
                date_to_french(last.date()),
                date_to_french(prochain.date()),
            )
            return PhaseMetrics(extras={"skipped": 1})

        etape(log, "Import du référentiel DOAJ")

        # Le dump du DOAJ est public : l'adresse du polite pool y est facultative.
        user_agent = build_user_agent(get_polite_pool_email_optional() or "")
        # Le dump transite par un fichier temporaire, que le module CSV relit : un enregistrement
        # peut porter des sauts de ligne dans ses champs. Le répertoire temporaire est le seul
        # emplacement en écriture du conteneur (`tmpfs` sur `/tmp`).
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            dump_path = tmp.name
        try:
            fetch_doaj_dump(dump_path, user_agent=user_agent, logger=log)
            stats = run_import_doaj_dump(
                conn,
                log,
                journal_repo=journal_repo,
                rows=read_doaj_dump_rows(dump_path),
            )
        finally:
            Path(dump_path).unlink(missing_ok=True)
    finally:
        conn.close()
    return PhaseMetrics(extras={"matched": stats.matched})


def _run_extractor(source: str, extractor: Extracteur, args: argparse.Namespace) -> PhaseMetrics:
    """Exécute un extracteur sous circuit-breaker, qui coupe la source après cinq échecs.

    Le circuit-breaker est posé dans la ContextVar que lit le client HTTP synchrone, et passé à `run`, dont les boucles le consultent pour arrêter une source à bout de budget. Le seuil est plus bas qu'au cross-import, les extracteurs travaillant sans lots concurrents.
    """
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )

    breaker = SourceCircuitBreaker(source, threshold=5)
    token = set_current_breaker(breaker)
    try:
        metrics = extractor.run(args, breaker=breaker)
    finally:
        reset_current_breaker(token)
    _signal_if_tripped(metrics, breaker)
    return metrics


def _extractors() -> dict[str, ConstructeurExtracteur]:
    """Constructeur de l'extracteur de chaque source : `(conn, source_log)` → extracteur câblé.

    `wos` et `scanr` ouvrent une connexion d'amorçage pour lire leurs identifiants avant l'extraction ; les autres lisent leur URL de base en configuration.

    Chaque constructeur importe les modules de sa source au moment où il s'exécute. Une source écartée du run ne charge donc pas son code, et un défaut qui l'atteint laisse les autres tourner."""
    from infrastructure.sources.api_params import API_BASE_URLS

    def hal(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from application.pipeline.extract.extract_hal import HalExtractor
        from infrastructure.sources.hal.extract_hal import PgHalExtractAdapter

        adapter = PgHalExtractAdapter(base_url=API_BASE_URLS["hal"])
        return HalExtractor(conn, source_log, adapter)

    def openalex(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from application.pipeline.extract.extract_openalex import OpenalexExtractor
        from infrastructure.sources.openalex.extract_openalex import PgOpenalexExtractAdapter

        adapter = PgOpenalexExtractAdapter(base_url=API_BASE_URLS["openalex"])
        return OpenalexExtractor(conn, source_log, adapter)

    def wos(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from application.pipeline.extract.extract_wos import WosExtractor
        from infrastructure.sources.config import get_wos_api_key
        from infrastructure.sources.wos.extract_wos import PgWosExtractAdapter

        adapter = PgWosExtractAdapter(base_url=API_BASE_URLS["wos"], api_key=get_wos_api_key())
        return WosExtractor(conn, source_log, adapter)

    def scanr(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from application.pipeline.extract.extract_scanr import ScanrExtractor
        from infrastructure.sources.config import get_scanr_credentials
        from infrastructure.sources.scanr.extract_scanr import PgScanrExtractAdapter

        adapter = PgScanrExtractAdapter(
            base_url=API_BASE_URLS["scanr"], credentials=get_scanr_credentials()
        )
        return ScanrExtractor(conn, source_log, adapter)

    def theses(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from application.pipeline.extract.extract_theses import ThesesExtractor
        from infrastructure.sources.theses.extract_theses import PgThesesExtractAdapter

        adapter = PgThesesExtractAdapter(base_url=API_BASE_URLS["theses"])
        return ThesesExtractor(conn, source_log, adapter)

    return {"hal": hal, "openalex": openalex, "wos": wos, "scanr": scanr, "theses": theses}


def _run_extract(
    source: str, make_extractor: ConstructeurExtracteur, args: argparse.Namespace
) -> PhaseMetrics:
    """Déroulé commun d'une extraction : ouverture de la connexion, exécution sous circuit-breaker, fermeture. `make_extractor` porte le câblage propre à la source."""
    from infrastructure.db.engine import get_sync_engine

    source_log = setup_logger(source, str(PROJECT_ROOT / "logs"))
    conn = get_sync_engine().connect()
    try:
        return _run_extractor(source, make_extractor(conn, source_log), args)
    finally:
        conn.close()


def _run_fetch_missing_hal_by_id() -> PhaseMetrics:
    """Cross-import HAL par hal-id (OpenAlex/ScanR) : documents absents du staging."""
    from application.pipeline.fetch_missing.hal import fetch_missing_hal_by_id
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.hal.fetch_missing_hal import PgHalFetchMissingAdapter

    etape(log, "Recherche dans HAL des documents avec hal-id trouvés ailleurs")
    conn = get_sync_engine().connect()
    adapter = PgHalFetchMissingAdapter()
    try:
        metrics = asyncio.run(fetch_missing_hal_by_id(conn, adapter, log))
    finally:
        conn.close()
    return metrics


def _run_fetch_missing_hal_by_nnt() -> PhaseMetrics:
    """Cross-import HAL par NNT (theses.fr) : thèses soutenues sans document HAL."""
    from application.pipeline.fetch_missing.hal import fetch_missing_hal_by_nnt
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.hal.fetch_missing_hal import PgHalFetchMissingAdapter

    etape(log, "Recherche dans HAL des thèses avec NNT trouvées ailleurs")
    conn = get_sync_engine().connect()
    adapter = PgHalFetchMissingAdapter()
    try:
        metrics = asyncio.run(fetch_missing_hal_by_nnt(conn, adapter, log))
    finally:
        conn.close()
    return metrics


def _make_fetch_missing_doi_adapter(target: str) -> "AsyncFetchMissingDoiAdapter":
    """Construit l'adapter `fetch_missing_doi` d'une source cible.

    Consommé par le cross-import (`_run_fetch_missing_doi`).
    """
    from typing import cast

    from application.ports.pipeline.fetch_missing.doi import (
        AsyncFetchMissingDoiAdapter,
    )
    from infrastructure.sources.crossref.fetch_missing_doi import CrossrefFetchMissingDoiAdapter
    from infrastructure.sources.datacite.fetch_missing_doi import DataciteFetchMissingDoiAdapter
    from infrastructure.sources.hal.fetch_missing_doi import HalFetchMissingDoiAdapter
    from infrastructure.sources.openalex.fetch_missing_doi import OpenalexFetchMissingDoiAdapter
    from infrastructure.sources.scanr.fetch_missing_doi import ScanrFetchMissingDoiAdapter
    from infrastructure.sources.wos.fetch_missing_doi import WosFetchMissingDoiAdapter

    # Cast : mypy ne reconnaît pas qu'une classe concrète se conforme à un Protocol quand elle
    # est passée comme `type[Protocol]`.
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
    from application.pipeline.fetch_missing.doi import run_async
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.pipeline.extract.cross_import import get_cross_import_dois
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )
    from infrastructure.sources.config import get_fetch_missing_max_per_source

    adapter = _make_fetch_missing_doi_adapter(target)

    conn = get_sync_engine().connect()
    # Circuit-breaker de la source : le client HTTP lit la ContextVar, l'orchestrateur consulte
    # `breaker.tripped`.
    breaker = SourceCircuitBreaker(target)
    token = set_current_breaker(breaker)
    try:
        metrics = asyncio.run(
            run_async(
                conn,
                adapter,
                log,
                cross_import_dois_reader=get_cross_import_dois,
                limit=get_fetch_missing_max_per_source(conn),
                breaker=breaker,
            )
        )
    except SourceUnavailableError:
        metrics = PhaseMetrics()
        signal_source_unavailable(metrics, target, logger=log, phase="fetch_missing")
    finally:
        reset_current_breaker(token)
        conn.close()
    _signal_if_tripped(metrics, breaker)
    return metrics


def _make_fetch_stale_adapter(source: str) -> "FetchStaleAdapter":
    """Construit l'adapter `fetch_stale` d'une source (refetch par id natif)."""
    from infrastructure.sources.crossref.fetch_stale import CrossrefFetchStaleAdapter
    from infrastructure.sources.datacite.fetch_stale import DataciteFetchStaleAdapter
    from infrastructure.sources.hal.fetch_stale import HalFetchStaleAdapter
    from infrastructure.sources.openalex.fetch_stale import OpenalexFetchStaleAdapter
    from infrastructure.sources.scanr.fetch_stale import ScanrFetchStaleAdapter
    from infrastructure.sources.theses.fetch_stale import ThesesFetchStaleAdapter
    from infrastructure.sources.wos.fetch_stale import WosFetchStaleAdapter

    # Cast : cf. `_make_fetch_missing_doi_adapter`.
    adapter_classes: dict[str, type[FetchStaleAdapter]] = cast(
        "dict[str, type[FetchStaleAdapter]]",
        {
            "hal": HalFetchStaleAdapter,
            "openalex": OpenalexFetchStaleAdapter,
            "wos": WosFetchStaleAdapter,
            "scanr": ScanrFetchStaleAdapter,
            "theses": ThesesFetchStaleAdapter,
            "crossref": CrossrefFetchStaleAdapter,
            "datacite": DataciteFetchStaleAdapter,
        },
    )
    return adapter_classes[source]()


def _run_fetch_stale(target: str, years: list[int] | None) -> PhaseMetrics:
    """Refetch par id natif des rows stale d'une source : trouvé → bump, absence → disappeared.

    `years` borne le refresh à la fenêtre d'années du run (None = tout le stale).
    """
    from application.pipeline.extract.fetch_stale import refresh
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.sources.circuit_breaker import (
        SourceCircuitBreaker,
        reset_current_breaker,
        set_current_breaker,
    )

    adapter = _make_fetch_stale_adapter(target)

    conn = get_sync_engine().connect()
    # Circuit-breaker de la source, comme au cross-import : une série de 429 coupe son
    # rafraîchissement jusqu'au run suivant.
    breaker = SourceCircuitBreaker(target)
    token = set_current_breaker(breaker)
    try:
        metrics = asyncio.run(refresh(conn, adapter, log, years=years, breaker=breaker))
    except SourceUnavailableError:
        metrics = PhaseMetrics()
        signal_source_unavailable(metrics, target, logger=log, phase="fetch_stale")
    finally:
        reset_current_breaker(token)
        conn.close()
    _signal_if_tripped(metrics, breaker)
    return metrics


def phase_oa_status(options: RunOptions) -> PhaseMetrics:
    """Enrichissement de `publications.oa_status`, une publication à la fois, via Unpaywall.

    Le délai de péremption et le plafond par run bornent la phase : le retard des publications jamais vérifiées s'écoule d'un run à l'autre. Unpaywall exige l'adresse électronique du polite pool ; sans elle, la phase est sautée.

    Séquence et métriques dans `application/pipeline/oa_status/phase.py` ; ici, le câblage.
    """
    import asyncio

    import httpx2

    from application.pipeline.oa_status.phase import run
    from application.pipeline.signals import filter_configured
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.pipeline.oa_status import PgOaStatusQueries
    from infrastructure.sources.api_params import API_BASE_URLS
    from infrastructure.sources.config import (
        get_polite_pool_email_optional,
        get_unpaywall_max_per_run,
    )
    from infrastructure.sources.unpaywall.client import fetch_oa_status

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
        base_url = API_BASE_URLS["unpaywall"]
        email = get_polite_pool_email_optional() or ""

        async def fetcher(client: httpx2.AsyncClient, doi: str) -> str | None:
            return await fetch_oa_status(client, doi, base_url=base_url, email=email, logger=log)

        metrics.merge(
            asyncio.run(
                run(
                    conn,
                    PgOaStatusQueries(),
                    log,
                    fetcher=fetcher,
                    max_per_run=get_unpaywall_max_per_run(conn),
                )
            )
        )
    finally:
        conn.close()
    return metrics


# Implémentation de chaque phase. `PHASE_ORDER` fixe l'ordre d'exécution ; un contrôle au
# démarrage vérifie que le registre couvre exactement les phases qu'il nomme.
_PHASE_FUNCTIONS: dict[str, Phase] = {
    "extract": phase_extract,
    "resolve_ra": phase_resolve_ra,
    "fetch_missing": phase_fetch_missing,
    "fetch_stale": phase_fetch_stale,
    "fetch_truncated": phase_fetch_truncated,
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

PHASES: list[tuple[str, Phase]] = [(name, _PHASE_FUNCTIONS[name]) for name in PHASE_ORDER]

PHASE_NAMES = list(PHASE_ORDER)


def _sigterm_raises_keyboard_interrupt(_signum: int, _frame: FrameType | None) -> None:
    raise KeyboardInterrupt


def _install_sigterm_handler() -> None:
    """Convertit SIGTERM en KeyboardInterrupt, traité comme une interruption clavier : ligne de journal, rapport partiel, commande de reprise.

    Un arrêt demandé par systemd, `docker stop` ou `kubectl delete` laisse ainsi la trace du point où le pipeline s'est arrêté. Sur Windows, où `os.kill` ne délivre pas SIGTERM, la fonction reste sans effet.
    """
    signal.signal(signal.SIGTERM, _sigterm_raises_keyboard_interrupt)


def _catalogue_des_phases() -> str:
    """Phases dans l'ordre d'exécution, chacune résumée par la première ligne de sa docstring."""
    largeur = max(len(name) for name, _ in PHASES)
    lignes = ["Phases, dans l'ordre :"]
    for i, (name, fn) in enumerate(PHASES, 1):
        doc = fn.__doc__.strip().split("\n")[0] if fn.__doc__ else ""
        lignes.append(f"  {i:2d}. {name:{largeur}s}  {doc}")
    return "\n".join(lignes)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Parseur des arguments de la CLI pipeline.

    L'aide porte le catalogue des phases : `--from` et `--only` les nomment.
    """
    parser = argparse.ArgumentParser(
        description="Orchestrateur pipeline bibliométrique",
        epilog=_catalogue_des_phases(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--from",
        dest="from_phase",
        metavar="PHASE",
        choices=PHASE_NAMES,
        help="Reprendre depuis cette phase",
    )
    parser.add_argument(
        "--only",
        metavar="PHASE",
        choices=PHASE_NAMES,
        help="Exécuter uniquement cette phase",
    )
    parser.add_argument(
        "--no-extras",
        action="store_true",
        help="Omettre les enrichissements terminaux (relations, subjects, countries, oa_status)",
    )
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
        "--raw-store",
        action="store_true",
        help="Archive les réponses brutes des sources sur disque, sous "
        "`BIBLIO_RAW_STORE_DIR`. Rejouer une normalisation puise alors dans cette archive "
        "au lieu de réinterroger les sources.",
    )
    parser.add_argument(
        "--rebuild-subjects",
        action="store_true",
        help="À la phase subjects, ré-ingère toutes les publications (pas seulement les "
        "modifiées) pour propager une évolution des règles d'ingestion sur tout le stock.",
    )
    return parser


def _select_phases_to_run(
    args: argparse.Namespace,
) -> list[tuple[str, Phase]]:
    """Phases à exécuter selon `--only` / `--from` (sinon toutes), moins les enrichissements si `--no-extras`.

    `--only` nomme une phase explicitement : elle est rendue même si c'est un enrichissement.
    """
    if args.only:
        return [(n, fn) for n, fn in PHASES if n == args.only]
    if args.from_phase:
        retenues = PHASES[PHASE_NAMES.index(args.from_phase) :]
    else:
        retenues = list(PHASES)
    if args.no_extras:
        retenues = [(n, fn) for n, fn in retenues if n not in EXTRA_PHASES]
    return retenues


LARGEUR_TITRE_PHASE = 48
"""Largeur du texte dans le cadre d'un titre, la même pour tous."""


def _encadre(lignes: list[str]) -> list[str]:
    """Encadre `lignes`, chacune repliée à la largeur du cadre.

    Un terminal reçoit un cadre de largeur constante, une sortie capturée deux filets horizontaux.
    """
    if not sys.stdout.isatty():
        return ["─" * 40, *lignes, "─" * 40]

    repliees = [repli for ligne in lignes for repli in textwrap.wrap(ligne, LARGEUR_TITRE_PHASE)]
    largeur = LARGEUR_TITRE_PHASE + 4
    return [
        f"╔{'═' * largeur}╗",
        *[f"║  {ligne.ljust(largeur - 2)}║" for ligne in repliees],
        f"╚{'═' * largeur}╝",
    ]


def _titre_de_phase(name: str) -> list[str]:
    """Lignes ouvrant une phase : son nom, et ce qu'elle produit."""
    # `PHASE_LIBELLES` couvre les phases du pipeline ; les tests en nomment d'autres.
    libelle = PHASE_LIBELLES.get(name)
    return _encadre([f"{PHASE_MARKER}{name}", *([libelle] if libelle else [])])


TITRE_PIPELINE = (
    "┏┓ ╻┏┓ ╻  ╻┏━┓┏┳┓┏━╸╺┳╸┏━┓╻┏━╸",
    "┣┻┓┃┣┻┓┃  ┃┃ ┃┃┃┃┣╸  ┃ ┣┳┛┃┣╸",
    "┗━┛╹┗━┛┗━╸╹┗━┛╹ ╹┗━╸ ╹ ╹┗╸╹┗━╸",
)
"""« BIBLIOMETRIE » en caractères de filets, en tête de la bannière d'une exécution."""

_LARGEUR_CLE_REGLAGE = 9
"""Largeur d'une clé de réglage et de ses points de conduite, dans la bannière."""


def _reglage(cle: str, valeur: str) -> list[str]:
    """Lignes « clé ···· valeur » de la bannière, la valeur repliée sous elle-même."""
    tete = f"{cle} {'·' * (_LARGEUR_CLE_REGLAGE - len(cle))} "
    repliee = textwrap.wrap(valeur, LARGEUR_TITRE_PHASE - len(tete)) or [""]
    return [tete + repliee[0], *(" " * len(tete) + suite for suite in repliee[1:])]


def _banniere(reglages: list[str]) -> list[str]:
    """Encadre le titre et les réglages d'une exécution, avec une ombre.

    Un terminal reçoit le cadre, au moins aussi large que celui d'une phase ; une sortie capturée reçoit deux filets et le titre en texte.
    """
    if not sys.stdout.isatty():
        return ["─" * 40, "PIPELINE BIBLIOMÉTRIQUE", *reglages, "─" * 40]

    corps = ["", *(f"  {ligne}" for ligne in TITRE_PIPELINE), "", *(f"  {r}" for r in reglages), ""]
    onglet = "┤ PIPELINE ├"
    largeur = max(LARGEUR_TITRE_PHASE + 4, *(len(ligne) + 2 for ligne in corps))
    return [
        f"┌───{onglet}{'─' * (largeur - 3 - len(onglet))}┐",
        *(f"│{ligne.ljust(largeur)}│▒" for ligne in corps),
        f"└{'─' * largeur}┘▒",
        f" {'▒' * (largeur + 2)}",
    ]


def _titre_du_run(args: argparse.Namespace, phases: list[tuple[str, Phase]]) -> list[str]:
    """Lignes ouvrant une exécution : son mode, puis ce qui écarte le lancement du courant."""
    reglages = _reglage("mode", args.mode)

    if args.year:
        reglages += _reglage("année", str(args.year))
    elif args.start_year:
        reglages += _reglage("depuis", str(args.start_year))

    if args.only or args.from_phase:
        reglages += _reglage("phases", ", ".join(n for n, _ in phases))
    elif args.no_extras:
        reglages += _reglage("phases", "sans les enrichissements terminaux")

    options = [
        texte
        for drapeau, texte in (
            (args.rebuild_publications, "publications reconstruites"),
            (args.rebuild_authorships, "signatures reconstruites"),
            (args.rebuild_subjects, "sujets reconstruits"),
            (args.raw_store, "réponses des sources archivées"),
        )
        if drapeau
    ]
    if options:
        reglages += _reglage("options", ", ".join(options))

    return _banniere(reglages)


def _run_one_phase(
    name: str,
    fn: Phase,
    *,
    args: argparse.Namespace,
    sources: set[str],
    recorder: PhaseExecutionRecorder,
) -> tuple[str, float]:
    """Exécute une phase et enregistre son observabilité. Rend son nom et sa durée.

    Une interruption clavier, une `RuntimeError` ou une erreur de base est enregistrée, puis termine le processus ; `--from <phase>` reprend la séquence où elle s'est arrêtée."""
    from sqlalchemy.exc import SQLAlchemyError

    # Injecte le nom de phase dans tous les records émis pendant `fn` (logger `normalize:` plutôt
    # que `pipeline:`), y compris depuis les extracteurs threadés qui héritent du contexte.
    phase_token = set_log_phase(name)
    try:
        # Ligne vide devant le cadre : elle le détache de ce que la phase précédente a écrit.
        log.info("")
        for ligne in _titre_de_phase(name):
            log.info("%s", ligne)
        phase_started_at = datetime.datetime.now(datetime.UTC)
        t0_phase = time.time()
        try:
            result = fn(
                RunOptions(
                    mode=args.mode,
                    sources=sources,
                    year=args.year,
                    start_year=args.start_year,
                    include_wos=args.include_wos,
                    rebuild_publications=args.rebuild_publications,
                    rebuild_authorships=args.rebuild_authorships,
                    rebuild_subjects=args.rebuild_subjects,
                    raw_store=args.raw_store,
                )
            )
        except KeyboardInterrupt:
            log.warning("Pipeline interrompu par l'utilisateur à la phase '%s'", name)
            log.info("Pour reprendre : run_pipeline --from %s", name)
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
            sys.exit(130)
        except (RuntimeError, SQLAlchemyError) as e:
            log.error("Pipeline interrompu à la phase '%s' : %s", name, e)
            log.error("Pour reprendre : run_pipeline --from %s", name)
            recorder.record(
                phase=name,
                started_at=phase_started_at,
                status="error",
                metrics=PhaseMetrics().to_payload(time.time() - t0_phase),
                signals=[{"level": "error", "code": "exception", "message": str(e)}],
                details={},
            )
            sys.exit(1)

        duration = time.time() - t0_phase
        metrics = result if isinstance(result, PhaseMetrics) else PhaseMetrics()
        if isinstance(result, PhaseMetrics):
            # Une phase pose `resume = ""` pour se clore sans un mot, ses barres ayant tout dit.
            if (bilan := result.resume if result.resume is not None else result.as_summary()) != "":
                log.info("")
                log.info("Terminé en %.1fs : %s", duration, bilan)
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


def _execute_phases(args: argparse.Namespace, phases_to_run: list[tuple[str, Phase]]) -> None:
    """Déroule la séquence des phases avec observabilité par run, puis le récapitulatif de fin."""
    from infrastructure.observability.phase_executions import start_run

    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    # Sources effectivement interrogées : wos est opt-in (`--include-wos`).
    effective_sources = sorted(sources - {"wos"}) if not args.include_wos else sorted(sources)

    # Enregistre le run et chacune de ses phases : identifiant de séquence, entrées, sorties, statut.
    recorder = start_run(mode=args.mode, sources=effective_sources)
    if recorder.run_id is not None:
        log.info("%s%d", RUN_MARKER, recorder.run_id)

    # Matérialise `perimeter_structures` avant toute phase : l'extraction lit le périmètre
    # d'extraction dès la première phase ; `affiliations` la rematérialise ensuite, à son démarrage.
    from infrastructure.db.engine import get_sync_engine
    from infrastructure.pipeline.perimeter import refresh_perimeter_structures

    with get_sync_engine().connect() as perimeter_conn:
        refresh_perimeter_structures(perimeter_conn)
        perimeter_conn.commit()

    t0_total = time.time()
    phase_results = [
        _run_one_phase(name, fn, args=args, sources=sources, recorder=recorder)
        for name, fn in phases_to_run
    ]

    elapsed_total = time.time() - t0_total
    recorder.close()
    log.info("=" * 60)
    log.info("%s en %.0fs (%.1f min)", RUN_END_MARKER, elapsed_total, elapsed_total / 60)
    if recorder.run_id is not None:
        log.info("Run #%d — récapitulatif par phase :", recorder.run_id)
        for phase_name, phase_duration in phase_results:
            log.info("  %-22s %7.1fs", phase_name, phase_duration)
    log.info("=" * 60)


def main() -> None:
    # Une faute de segmentation vient d'une extension C — pilote de base, client HTTP, automate
    # de matching — et tue le processus sans passer par Python. `faulthandler` écrit alors la pile
    # de chaque thread sur la sortie d'erreur. Il lui faut un vrai descripteur de fichier, que la
    # sortie capturée d'un test ne donne pas.
    with contextlib.suppress(ValueError, io.UnsupportedOperation):
        faulthandler.enable()
    _install_sigterm_handler()
    args = _build_arg_parser().parse_args()

    phases_to_run = _select_phases_to_run(args)
    for ligne in _titre_du_run(args, phases_to_run):
        log.info("%s", ligne)

    # Une seule exécution à la fois sur la base : deux en parallèle s'interbloquent.
    try:
        with pipeline_lock():
            _execute_phases(args, phases_to_run)
    except PipelineAlreadyRunningError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
