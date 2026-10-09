"""Câblage de la phase `publishers_journals` et de ses sous-étapes."""

from __future__ import annotations

import asyncio
import datetime
import tempfile
from pathlib import Path

from application.pipeline.context import Phase
from application.pipeline.libelles import etape
from application.pipeline.metrics import PhaseMetrics
from domain.dates import date_to_french
from interfaces.cli.phases.execution import credentials_missing, log, open_tx, under_circuit_breaker


def build() -> Phase:
    """Enrichissement du référentiel `journals`.

    `resolve_publishers` rattache chaque préfixe DOI à son éditeur Crossref ou à son repository DataCite, via les API `/prefixes`, pour les préfixes en attente d'éditeur. `enrich_journals_from_openalex` lit dans OpenAlex Sources les frais de publication et le type des revues encore typées `unknown`. `check_journals_in_sudoc` vérifie dans le Sudoc les ISSN des revues jamais vérifiées, les corrige et les range par support. `enrich_journals_from_doaj` importe le dump CSV du DOAJ, qui fait autorité sur `is_in_doaj`, quand le dernier import date de plus que le délai `doaj_refresh_after_days`.

    La phase suit `normalize`, qui crée les éditeurs et les revues à enrichir. L'enrichissement des éditeurs eux-mêmes — pays, ROR, type — se lance à la demande, par `interfaces/cli/maintenance/enrich_publishers.py`.

    Séquence, gardes de configuration et métriques dans `application/pipeline/publishers_journals/phase.py`.
    """
    from application.pipeline.publishers_journals.phase import PublishersJournalsPhase

    return PublishersJournalsPhase(
        resolve_publishers=_run_resolve_publishers,
        enrich_from_openalex=_run_enrich_journals_from_openalex,
        check_in_sudoc=_run_check_journals_in_sudoc,
        merge_duplicates=_run_merge_duplicate_journals,
        delete_empty=_run_delete_empty_journals,
        merge_duplicate_monographs=_run_merge_duplicate_monographs,
        delete_empty_monographs=_run_delete_empty_monographs,
        link_monographs_to_collections=_run_link_monographs_to_collections,
        delete_empty_publishers=_run_delete_empty_publishers,
        type_proceedings=_run_type_proceedings_journals,
        type_proceedings_volumes=_run_type_proceedings_volumes,
        learn_doi_namespaces=_run_learn_journal_doi_namespaces,
        enrich_from_doaj=_run_enrich_journals_from_doaj,
        credentials_missing=credentials_missing,
    )


def _run_resolve_publishers() -> PhaseMetrics:
    from application.pipeline.publishers_journals.resolve_publishers import (
        run_resolve_publishers,
    )
    from infrastructure.pipeline.doi_prefixes import PgDoiPrefixesQueries
    from infrastructure.pipeline.publishers import PgPublisherGatewayQueries
    from infrastructure.sources.config import get_polite_pool_email_optional
    from infrastructure.sources.crossref.prefixes import fetch_crossref_prefix
    from infrastructure.sources.datacite.prefixes import fetch_datacite_prefix
    from infrastructure.sources.polite_pool import build_user_agent

    user_agent = build_user_agent(get_polite_pool_email_optional() or "")
    with open_tx() as conn:
        return under_circuit_breaker(
            "crossref/datacite prefixes",
            lambda breaker: run_resolve_publishers(
                log,
                repo=PgDoiPrefixesQueries(conn),
                publisher_repo=PgPublisherGatewayQueries(conn),
                fetch_crossref_prefix_fn=lambda prefix, sample_doi: fetch_crossref_prefix(
                    prefix, sample_doi, user_agent=user_agent
                ),
                fetch_datacite_prefix_fn=lambda prefix: fetch_datacite_prefix(
                    prefix, user_agent=user_agent
                ),
                breaker=breaker,
            ),
            phase="publishers_journals",
            logger=log,
        )


def _run_enrich_journals_from_openalex() -> PhaseMetrics:
    from application.pipeline.publishers_journals.enrich_journals_from_openalex import (
        run_enrich_journals_from_openalex,
    )
    from infrastructure.pipeline.journals import PgJournalGatewayQueries
    from infrastructure.sources.api_params import API_BASE_URLS, DOAJ_DELAY
    from infrastructure.sources.config import (
        get_openalex_api_key,
        get_polite_pool_email_optional,
    )
    from infrastructure.sources.openalex.journal_enrichment import fetch_sources_batch

    api_key = get_openalex_api_key()
    mailto = get_polite_pool_email_optional() or ""
    sources_api = API_BASE_URLS["openalex_sources"]
    with open_tx() as conn:
        # Trois lots consécutifs en 429 disent le quota OpenAlex du jour épuisé : le reste attend
        # le run suivant.
        return under_circuit_breaker(
            "openalex sources",
            lambda breaker: run_enrich_journals_from_openalex(
                conn,
                log,
                journal_repo=PgJournalGatewayQueries(conn),
                fetch_batch=lambda oa_ids: fetch_sources_batch(
                    oa_ids, openalex_sources_api=sources_api, api_key=api_key, mailto=mailto
                ),
                breaker=breaker,
                rate_delay=DOAJ_DELAY,
            ),
            phase="publishers_journals",
            logger=log,
            threshold=3,
        )


def _run_check_journals_in_sudoc() -> PhaseMetrics:
    from application.pipeline.publishers_journals.check_journals_in_sudoc import (
        run_check_journals_in_sudoc,
    )
    from infrastructure.pipeline.journals import PgJournalGatewayQueries
    from infrastructure.sources.api_params import (
        API_BASE_URLS,
        SUDOC_MAX_CONCURRENT,
        SUDOC_MAX_PER_SECOND,
    )
    from infrastructure.sources.sudoc.client import fetch_ppns, fetch_serial_record

    base_url = API_BASE_URLS["sudoc"]
    with open_tx() as conn:
        # `asyncio.run` transmet aux coroutines la ContextVar du circuit-breaker.
        return under_circuit_breaker(
            "sudoc",
            lambda breaker: asyncio.run(
                run_check_journals_in_sudoc(
                    conn,
                    log,
                    journal_repo=PgJournalGatewayQueries(conn),
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
    from application.pipeline.publishers_journals.merge_duplicate_journals import (
        run_merge_duplicate_journals,
    )
    from application.services.journals.commands import merge_journals
    from infrastructure.pipeline.journals import PgJournalGatewayQueries
    from infrastructure.pipeline.metadata_correction import PgMetadataCorrectionQueries
    from infrastructure.repositories.journal_repository import PgJournalRepository
    from infrastructure.repositories.publication_repository import PgPublicationRepository

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
            log, journal_repo=PgJournalGatewayQueries(conn), merge=merge
        )


def _run_delete_empty_journals() -> PhaseMetrics:
    from application.pipeline.publishers_journals.delete_empty_journals import (
        run_delete_empty_journals,
    )
    from infrastructure.pipeline.journals import PgJournalGatewayQueries

    with open_tx() as conn:
        return run_delete_empty_journals(log, journal_repo=PgJournalGatewayQueries(conn))


def _run_merge_duplicate_monographs() -> PhaseMetrics:
    from application.pipeline.publishers_journals.merge_duplicate_monographs import (
        run_merge_duplicate_monographs,
    )
    from infrastructure.pipeline.monographs import PgMonographGatewayQueries

    with open_tx() as conn:
        return run_merge_duplicate_monographs(log, monograph_repo=PgMonographGatewayQueries(conn))


def _run_link_monographs_to_collections() -> PhaseMetrics:
    from application.pipeline.publishers_journals.link_monographs_to_collections import (
        run_link_monographs_to_collections,
    )
    from infrastructure.pipeline.containers import PgContainerGatewayQueries

    with open_tx() as conn:
        return run_link_monographs_to_collections(
            log, monograph_repo=PgContainerGatewayQueries(conn)
        )


def _run_delete_empty_monographs() -> PhaseMetrics:
    from application.pipeline.publishers_journals.delete_empty_monographs import (
        run_delete_empty_monographs,
    )
    from infrastructure.pipeline.monographs import PgMonographGatewayQueries

    with open_tx() as conn:
        return run_delete_empty_monographs(log, monograph_repo=PgMonographGatewayQueries(conn))


def _run_delete_empty_publishers() -> PhaseMetrics:
    from application.pipeline.publishers_journals.delete_empty_publishers import (
        run_delete_empty_publishers,
    )
    from infrastructure.pipeline.publishers import PgPublisherGatewayQueries

    with open_tx() as conn:
        return run_delete_empty_publishers(log, publisher_repo=PgPublisherGatewayQueries(conn))


def _run_type_proceedings_volumes() -> PhaseMetrics:
    from application.pipeline.publishers_journals.type_proceedings_volumes import (
        run_type_proceedings_volumes,
    )
    from infrastructure.pipeline.monographs import PgMonographGatewayQueries

    with open_tx() as conn:
        return run_type_proceedings_volumes(log, monograph_repo=PgMonographGatewayQueries(conn))


def _run_type_proceedings_journals() -> PhaseMetrics:
    from application.pipeline.publishers_journals.type_proceedings_journals import (
        run_type_proceedings_journals,
    )
    from infrastructure.pipeline.journals import PgJournalGatewayQueries

    with open_tx() as conn:
        return run_type_proceedings_journals(log, journal_repo=PgJournalGatewayQueries(conn))


def _run_learn_journal_doi_namespaces() -> PhaseMetrics:
    from application.pipeline.publishers_journals.learn_journal_doi_namespaces import (
        run_learn_journal_doi_namespaces,
    )
    from infrastructure.pipeline.journals import PgJournalGatewayQueries

    with open_tx() as conn:
        return run_learn_journal_doi_namespaces(log, journal_repo=PgJournalGatewayQueries(conn))


def _run_enrich_journals_from_doaj() -> PhaseMetrics:
    from application.pipeline.publishers_journals.import_journals_from_doaj_dump import (
        run_import_doaj_dump,
    )
    from infrastructure.pipeline.journals import PgJournalGatewayQueries
    from infrastructure.sources.config import (
        get_doaj_refresh_after_days,
        get_polite_pool_email_optional,
    )
    from infrastructure.sources.doaj.client import fetch_doaj_dump, read_doaj_dump_rows
    from infrastructure.sources.polite_pool import build_user_agent

    with open_tx() as conn:
        journal_repo = PgJournalGatewayQueries(conn)
        last = journal_repo.doaj_last_import_at()
        delai = datetime.timedelta(days=get_doaj_refresh_after_days(conn))
        if last is not None and last > datetime.datetime.now(datetime.UTC) - delai:
            prochain = last + delai
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
        # peut contenir des sauts de ligne dans ses champs. Le répertoire temporaire est le seul
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
    return PhaseMetrics(extras={"matched": stats.matched})
