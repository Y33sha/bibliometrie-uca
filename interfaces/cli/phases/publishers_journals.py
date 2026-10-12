"""Câblage de la phase `publishers_journals` et de ses sous-étapes."""

from __future__ import annotations

import asyncio

from interfaces.cli.phases.execution import credentials_missing, log, open_tx, under_circuit_breaker
from pipeline.context import Phase
from pipeline.metrics import PhaseMetrics


def build() -> Phase:
    """Enrichissement du référentiel `journals`.

    `resolve_publishers` rattache chaque préfixe DOI à son éditeur Crossref ou à son repository DataCite, via les API `/prefixes`, pour les préfixes en attente d'éditeur. `enrich_journals_from_openalex` lit dans OpenAlex Sources les frais de publication et le type des revues encore typées `unknown`. `check_journals_in_sudoc` vérifie dans le Sudoc les ISSN des revues jamais vérifiées, les corrige et les range par support. `enrich_journals_from_doaj` importe le dump CSV du DOAJ, qui fait autorité sur `is_in_doaj`, quand le dernier import date de plus que le délai `doaj_refresh_after_days`.

    La phase suit `normalize`, qui crée les éditeurs et les revues à enrichir. L'enrichissement des éditeurs eux-mêmes — pays, ROR, type — se lance à la demande, par `interfaces/cli/maintenance/enrich_publishers.py`.

    Séquence, gardes de configuration et métriques dans `pipeline/containers/publishers_journals.py`.
    """
    from pipeline.containers.publishers_journals import PublishersJournalsPhase

    return PublishersJournalsPhase(
        resolve_publishers=_run_resolve_publishers,
        enrich_journals_from_openalex=_run_enrich_journals_from_openalex,
        check_journals_in_sudoc=_run_check_journals_in_sudoc,
        merge_duplicate_journals=_run_merge_duplicate_journals,
        type_proceedings_journals=_run_type_proceedings_journals,
        learn_journal_doi_namespaces=_run_learn_journal_doi_namespaces,
        enrich_journals_from_doaj=_run_enrich_journals_from_doaj,
        merge_duplicate_monographs=_run_merge_duplicate_monographs,
        link_monographs_to_collections=_run_link_monographs_to_collections,
        type_proceedings_volumes=_run_type_proceedings_volumes,
        credentials_missing=credentials_missing,
    )


def _run_resolve_publishers() -> PhaseMetrics:
    from infrastructure.sources.config import get_polite_pool_email_optional
    from infrastructure.sources.polite_pool import build_user_agent
    from pipeline.containers.doi_prefixes import DoiPrefixesQueries
    from pipeline.containers.publishers import PublisherGatewayQueries
    from pipeline.containers.resolve_publishers import (
        run_resolve_publishers,
    )
    from pipeline.sources.crossref.prefixes import fetch_crossref_prefix
    from pipeline.sources.datacite.prefixes import fetch_datacite_prefix

    user_agent = build_user_agent(get_polite_pool_email_optional() or "")
    with open_tx() as conn:
        return under_circuit_breaker(
            "crossref/datacite prefixes",
            lambda breaker: run_resolve_publishers(
                conn,
                log,
                repo=DoiPrefixesQueries(conn),
                publisher_repo=PublisherGatewayQueries(conn),
                fetch_crossref_prefix_fn=lambda client, prefix, sample_doi: fetch_crossref_prefix(
                    client, prefix, sample_doi, user_agent=user_agent
                ),
                fetch_datacite_prefix_fn=lambda client, prefix: fetch_datacite_prefix(
                    client, prefix, user_agent=user_agent
                ),
                breaker=breaker,
            ),
            phase="publishers_journals",
            logger=log,
        )


def _run_enrich_journals_from_openalex() -> PhaseMetrics:
    from infrastructure.sources.api_params import API_BASE_URLS, DOAJ_DELAY
    from pipeline.containers.enrich_journals_from_openalex import (
        run_enrich_journals_from_openalex,
    )
    from pipeline.containers.journals import JournalGatewayQueries
    from pipeline.sources.openalex.journal_enrichment import fetch_sources_batch

    sources_api = API_BASE_URLS["openalex_sources"]
    with open_tx() as conn:
        # Trois lots consécutifs en 429 disent le quota OpenAlex du jour épuisé : le reste attend
        # le run suivant.
        return under_circuit_breaker(
            "openalex sources",
            lambda breaker: run_enrich_journals_from_openalex(
                conn,
                log,
                journal_repo=JournalGatewayQueries(conn),
                fetch_batch=lambda oa_ids: fetch_sources_batch(
                    oa_ids, openalex_sources_api=sources_api
                ),
                breaker=breaker,
                rate_delay=DOAJ_DELAY,
            ),
            phase="publishers_journals",
            logger=log,
            threshold=3,
        )


def _run_check_journals_in_sudoc() -> PhaseMetrics:
    from infrastructure.sources.api_params import (
        API_BASE_URLS,
        SUDOC_MAX_CONCURRENT,
        SUDOC_MAX_PER_SECOND,
    )
    from pipeline.containers.check_journals_in_sudoc import (
        run_check_journals_in_sudoc,
    )
    from pipeline.containers.journals import JournalGatewayQueries
    from pipeline.sources.sudoc import fetch_ppns, fetch_serial_record

    base_url = API_BASE_URLS["sudoc"]
    with open_tx() as conn:
        # `asyncio.run` transmet aux coroutines la ContextVar du circuit-breaker.
        return under_circuit_breaker(
            "sudoc",
            lambda breaker: asyncio.run(
                run_check_journals_in_sudoc(
                    conn,
                    log,
                    journal_repo=JournalGatewayQueries(conn),
                    fetch_ppns=lambda client, issns: fetch_ppns(client, issns, base_url=base_url),
                    fetch_record=lambda client, ppn: fetch_serial_record(
                        client, ppn, base_url=base_url
                    ),
                    breaker=breaker,
                    max_concurrent=SUDOC_MAX_CONCURRENT,
                    max_per_second=SUDOC_MAX_PER_SECOND,
                )
            ),
            phase="publishers_journals",
            logger=log,
            threshold=3,
        )


def _run_merge_duplicate_journals() -> PhaseMetrics:
    from application.services.journals.commands import merge_journals
    from infrastructure.repositories.journal_repository import PgJournalRepository
    from infrastructure.repositories.publication_repository import PgPublicationRepository
    from pipeline.containers.journals import JournalGatewayQueries
    from pipeline.containers.merge_duplicate_journals import (
        run_merge_duplicate_journals,
    )
    from pipeline.publications.metadata_correction_queries import PgMetadataCorrectionQueries

    with open_tx() as conn:
        corrections = PgMetadataCorrectionQueries()
        journal_repository = PgJournalRepository(conn)
        publication_repository = PgPublicationRepository(conn)

        def merge(target_id: int, source_id: int) -> None:
            merge_journals(
                conn,
                target_id,
                source_id,
                correction_queries=corrections,
                repo=journal_repository,
                publication_repo=publication_repository,
            )

        return run_merge_duplicate_journals(
            log, journal_repo=JournalGatewayQueries(conn), merge=merge
        )


def _run_merge_duplicate_monographs() -> PhaseMetrics:
    from pipeline.containers.merge_duplicate_monographs import (
        run_merge_duplicate_monographs,
    )
    from pipeline.containers.monographs import MonographGatewayQueries

    with open_tx() as conn:
        return run_merge_duplicate_monographs(log, monograph_repo=MonographGatewayQueries(conn))


def _run_link_monographs_to_collections() -> PhaseMetrics:
    from pipeline.containers.containers import ContainerGatewayQueries
    from pipeline.containers.link_monographs_to_collections import (
        run_link_monographs_to_collections,
    )

    with open_tx() as conn:
        return run_link_monographs_to_collections(log, monograph_repo=ContainerGatewayQueries(conn))


def _run_type_proceedings_volumes() -> PhaseMetrics:
    from pipeline.containers.monographs import MonographGatewayQueries
    from pipeline.containers.type_proceedings_volumes import (
        run_type_proceedings_volumes,
    )

    with open_tx() as conn:
        return run_type_proceedings_volumes(log, monograph_repo=MonographGatewayQueries(conn))


def _run_type_proceedings_journals() -> PhaseMetrics:
    from pipeline.containers.journals import JournalGatewayQueries
    from pipeline.containers.type_proceedings_journals import (
        run_type_proceedings_journals,
    )

    with open_tx() as conn:
        return run_type_proceedings_journals(log, journal_repo=JournalGatewayQueries(conn))


def _run_learn_journal_doi_namespaces() -> PhaseMetrics:
    from pipeline.containers.journals import JournalGatewayQueries
    from pipeline.containers.learn_journal_doi_namespaces import (
        run_learn_journal_doi_namespaces,
    )

    with open_tx() as conn:
        return run_learn_journal_doi_namespaces(log, journal_repo=JournalGatewayQueries(conn))


def _run_enrich_journals_from_doaj() -> PhaseMetrics:
    from infrastructure.sources.config import (
        get_doaj_refresh_after_days,
        get_polite_pool_email_optional,
    )
    from infrastructure.sources.polite_pool import build_user_agent
    from pipeline.containers.import_journals_from_doaj_dump import (
        run_enrich_journals_from_doaj,
    )
    from pipeline.containers.journals import JournalGatewayQueries
    from pipeline.sources.doaj import downloaded_doaj_dump

    # Le dump du DOAJ est public : l'adresse du polite pool y est facultative.
    user_agent = build_user_agent(get_polite_pool_email_optional() or "")
    with open_tx() as conn:
        return run_enrich_journals_from_doaj(
            conn,
            log,
            journal_repo=JournalGatewayQueries(conn),
            refresh_after_days=get_doaj_refresh_after_days(conn),
            download_dump=lambda: downloaded_doaj_dump(user_agent=user_agent, logger=log),
        )
