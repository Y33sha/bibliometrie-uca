"""Orchestrateur de la phase `publishers_journals` : enrichissement des référentiels d'éditeurs, de revues et de monographies.

Trois groupes de sous-étapes, dans l'ordre :

- **Éditeurs** — `resolve_publishers` : éditeur Crossref ou repository DataCite de chaque préfixe DOI en attente.
- **Revues** — `enrich_journals_from_openalex` (type et frais de publication), `check_journals_in_sudoc` (ISSN vérifiés, corrigés et rangés par support), `merge_duplicate_journals`, `type_proceedings_journals`, `learn_journal_doi_namespaces`, `enrich_journals_from_doaj`.
- **Monographies** — `merge_duplicate_monographs`, `link_monographs_to_collections`, `type_proceedings_volumes`.

Contraintes d'ordre :

- OpenAlex type les revues `unknown` avant le typage en recueil d'actes, qui vise aussi les revues `unknown`.
- La vérification Sudoc précède la fusion des revues, qui lit l'ISSN-L, et l'import DOAJ, qui apparie les revues par ISSN.
- Les espaces de noms DOI suivent la fusion et le typage des revues.
- Le rattachement des monographies suit la fusion des revues. La nature des monographies lit le type de la collection que pose le rattachement.

Chaque sous-étape tient une ligne du journal, sous le titre de son groupe. Un accès non configuré est sauté avec un signal `source_unconfigured`. Les runners de sous-étape (connexion, circuit-breaker, adapters) et la détection de configuration sont injectés par le câblage ; ici, la séquence, les gardes de configuration et l'assemblage des métriques.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

from pipeline.publishing import (
    check_journals_in_sudoc,
    enrich_journals_from_openalex,
    import_journals_from_doaj_dump,
    learn_journal_doi_namespaces,
    link_monographs_to_collections,
    merge_duplicate_journals,
    merge_duplicate_monographs,
    resolve_publishers,
    type_proceedings_journals,
    type_proceedings_volumes,
)
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.execution import credentials_missing, log, open_tx, under_circuit_breaker
from pipeline.runtime.libelles import BRANCHE, DERNIERE_BRANCHE, etape
from pipeline.runtime.metrics import PhaseMetrics
from pipeline.runtime.signals import filter_configured

RunSubstep = Callable[[], PhaseMetrics]
CredentialsMissing = Callable[[str], str | None]


@dataclass(frozen=True)
class _SousEtape:
    """Sous-étape de la phase : le champ de `PublishersJournalsPhase` qui l'exécute, son libellé, et les accès à configurer avant de la lancer."""

    champ: str
    libelle: str
    acces: tuple[str, ...] = ()


_GROUPES: tuple[tuple[str, tuple[_SousEtape, ...]], ...] = (
    (
        "Éditeurs",
        (_SousEtape("resolve_publishers", resolve_publishers.LIBELLE, ("crossref", "datacite")),),
    ),
    (
        "Revues",
        (
            _SousEtape(
                "enrich_journals_from_openalex",
                enrich_journals_from_openalex.LIBELLE,
                ("openalex",),
            ),
            _SousEtape("check_journals_in_sudoc", check_journals_in_sudoc.LIBELLE),
            _SousEtape("merge_duplicate_journals", merge_duplicate_journals.LIBELLE),
            _SousEtape("type_proceedings_journals", type_proceedings_journals.LIBELLE),
            _SousEtape("learn_journal_doi_namespaces", learn_journal_doi_namespaces.LIBELLE),
            _SousEtape("enrich_journals_from_doaj", import_journals_from_doaj_dump.LIBELLE),
        ),
    ),
    (
        "Monographies",
        (
            _SousEtape("merge_duplicate_monographs", merge_duplicate_monographs.LIBELLE),
            _SousEtape("link_monographs_to_collections", link_monographs_to_collections.LIBELLE),
            _SousEtape("type_proceedings_volumes", type_proceedings_volumes.LIBELLE),
        ),
    ),
)


@dataclass(frozen=True)
class PublishersJournalsPhase:
    resolve_publishers: RunSubstep
    enrich_journals_from_openalex: RunSubstep
    check_journals_in_sudoc: RunSubstep
    merge_duplicate_journals: RunSubstep
    type_proceedings_journals: RunSubstep
    learn_journal_doi_namespaces: RunSubstep
    enrich_journals_from_doaj: RunSubstep
    merge_duplicate_monographs: RunSubstep
    link_monographs_to_collections: RunSubstep
    type_proceedings_volumes: RunSubstep
    credentials_missing: CredentialsMissing

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Enchaîne les groupes de sous-étapes, écrit une ligne par sous-étape et assemble les métriques de la phase."""
        logger = ctx.logger
        metrics = PhaseMetrics()
        by_step: dict[str, PhaseMetrics] = {}
        for titre, sous_etapes in _GROUPES:
            etape(logger, titre)
            for indice, sous_etape in enumerate(sous_etapes):
                branche = DERNIERE_BRANCHE if indice == len(sous_etapes) - 1 else BRANCHE
                by_step[sous_etape.champ] = self._run_one(sous_etape, branche, metrics, logger)
        _assemble(metrics, by_step)
        return metrics

    def _run_one(
        self, sous_etape: _SousEtape, branche: str, metrics: PhaseMetrics, logger: logging.Logger
    ) -> PhaseMetrics:
        """Exécute une sous-étape, sauf si aucun de ses accès n'est configuré, et écrit sa ligne de bilan."""
        if sous_etape.acces and not filter_configured(
            list(sous_etape.acces),
            metrics,
            credentials_missing=self.credentials_missing,
            logger=logger,
            phase="publishers_journals",
        ):
            logger.info("%s%s : sautée, accès non configuré", branche, sous_etape.libelle)
            return PhaseMetrics()
        sub: PhaseMetrics = getattr(self, sous_etape.champ)()
        if sub.resume is not None:
            bilan = sub.resume
        elif sub.signals:
            bilan = "interrompue"
        else:
            bilan = "rien à faire"
        logger.info("%s%s : %s", branche, sous_etape.libelle, bilan)
        return sub


# Ligne de la table d'observabilité de chaque sous-étape : son champ, son libellé, et ce qui compte comme identifié.
_TABLE: tuple[tuple[str, str, Callable[[PhaseMetrics], int]], ...] = (
    (
        "resolve_publishers",
        "préfixes DOI → publishers",
        lambda m: m.extras.get("publisher_matched", 0),
    ),
    ("enrich_journals_from_openalex", "revues OpenAlex", lambda m: m.updated),
    (
        "check_journals_in_sudoc",
        "revues vérifiées dans le Sudoc",
        lambda m: m.extras.get("sudoc_found", 0),
    ),
    (
        "merge_duplicate_journals",
        "groupes de revues en double",
        lambda m: m.extras.get("journals_merged", 0),
    ),
    (
        "type_proceedings_journals",
        "revues typées recueils d'actes",
        lambda m: m.extras.get("journals_typed_proceedings", 0),
    ),
    (
        "learn_journal_doi_namespaces",
        "DOI → espaces de noms des revues",
        lambda m: m.extras.get("journal_doi_namespaces", 0),
    ),
    (
        "merge_duplicate_monographs",
        "monographies en double fusionnées",
        lambda m: m.extras.get("monographs_merged", 0),
    ),
    (
        "link_monographs_to_collections",
        "monographies rattachées à leur collection",
        lambda m: m.extras.get("monographs_linked", 0),
    ),
    (
        "type_proceedings_volumes",
        "monographies retypées (actes ou livre)",
        lambda m: m.extras.get("monographs_to_proceedings", 0),
    ),
)


def _assemble(metrics: PhaseMetrics, by_step: dict[str, PhaseMetrics]) -> None:
    """Reporte dans `metrics` les métriques des sous-étapes, dans l'ordre de leur exécution."""
    # Les compteurs et signaux des sous-étapes remontent à la phase : le log (`as_summary()`), l'observabilité (`to_payload()`) et le passage en avertissement sur circuit-breaker tripé en dépendent. Les `details` sur-mesure sont posés juste après.
    for sub in by_step.values():
        metrics.merge(sub)

    publishers = by_step["resolve_publishers"]
    metrics.details["table"] = {
        "rows": [
            {
                "key": key,
                "traités": by_step[champ].total,
                "identifiés": identifies(by_step[champ]),
                "créés": publishers.extras.get("publisher_created", 0)
                if champ == "resolve_publishers"
                else 0,
            }
            for champ, key, identifies in _TABLE
        ]
    }
    # DOAJ : ligne à part (sous-étape conditionnelle, métrique propre).
    metrics.details["summary"] = {
        "doaj_matched": by_step["enrich_journals_from_doaj"].extras.get("matched", 0)
    }
    # Chaque sous-étape a écrit sa ligne ; la table d'observabilité garde le détail.
    metrics.resume = ""


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    """Enrichissement du référentiel `journals`.

    `resolve_publishers` rattache chaque préfixe DOI à son éditeur Crossref ou à son repository DataCite, via les API `/prefixes`, pour les préfixes en attente d'éditeur. `enrich_journals_from_openalex` lit dans OpenAlex Sources les frais de publication et le type des revues encore typées `unknown`. `check_journals_in_sudoc` vérifie dans le Sudoc les ISSN des revues jamais vérifiées, les corrige et les range par support. `enrich_journals_from_doaj` importe le dump CSV du DOAJ, qui fait autorité sur `is_in_doaj`, quand le dernier import date de plus que le délai `doaj_refresh_after_days`.

    La phase suit `normalize`, qui crée les éditeurs et les revues à enrichir. L'enrichissement des éditeurs eux-mêmes — pays, ROR, type — se lance à la demande, par `interfaces/cli/maintenance/enrich_publishers.py`.
    """

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
    from pipeline.ingestion.crossref.prefixes import fetch_crossref_prefix
    from pipeline.ingestion.datacite.prefixes import fetch_datacite_prefix
    from pipeline.ingestion.http.polite_pool import build_user_agent
    from pipeline.publishing.doi_prefixes import DoiPrefixesQueries
    from pipeline.publishing.publishers import PublisherGatewayQueries
    from pipeline.publishing.resolve_publishers import (
        run_resolve_publishers,
    )
    from pipeline.runtime.config import get_polite_pool_email_optional

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
    from pipeline.ingestion.http.api_params import API_BASE_URLS, DOAJ_DELAY
    from pipeline.ingestion.openalex.journal_enrichment import fetch_sources_batch
    from pipeline.publishing.enrich_journals_from_openalex import (
        run_enrich_journals_from_openalex,
    )
    from pipeline.publishing.journals import JournalGatewayQueries

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
    from pipeline.ingestion.http.api_params import (
        API_BASE_URLS,
        SUDOC_MAX_CONCURRENT,
        SUDOC_MAX_PER_SECOND,
    )
    from pipeline.ingestion.sudoc import fetch_ppns, fetch_serial_record
    from pipeline.publishing.check_journals_in_sudoc import (
        run_check_journals_in_sudoc,
    )
    from pipeline.publishing.journals import JournalGatewayQueries

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
    from pipeline.publishing.journal_merge import merge_journals
    from pipeline.publishing.journals import JournalGatewayQueries
    from pipeline.publishing.merge_duplicate_journals import (
        run_merge_duplicate_journals,
    )

    with open_tx() as conn:

        def merge(target_id: int, source_id: int) -> None:
            merge_journals(conn, target_id, source_id)
            conn.commit()

        return run_merge_duplicate_journals(
            log, journal_repo=JournalGatewayQueries(conn), merge=merge
        )


def _run_merge_duplicate_monographs() -> PhaseMetrics:
    from pipeline.publishing.merge_duplicate_monographs import (
        run_merge_duplicate_monographs,
    )
    from pipeline.publishing.monographs import MonographGatewayQueries

    with open_tx() as conn:
        return run_merge_duplicate_monographs(log, monograph_repo=MonographGatewayQueries(conn))


def _run_link_monographs_to_collections() -> PhaseMetrics:
    from pipeline.publishing.containers import ContainerGatewayQueries
    from pipeline.publishing.link_monographs_to_collections import (
        run_link_monographs_to_collections,
    )

    with open_tx() as conn:
        return run_link_monographs_to_collections(log, monograph_repo=ContainerGatewayQueries(conn))


def _run_type_proceedings_volumes() -> PhaseMetrics:
    from pipeline.publishing.monographs import MonographGatewayQueries
    from pipeline.publishing.type_proceedings_volumes import (
        run_type_proceedings_volumes,
    )

    with open_tx() as conn:
        return run_type_proceedings_volumes(log, monograph_repo=MonographGatewayQueries(conn))


def _run_type_proceedings_journals() -> PhaseMetrics:
    from pipeline.publishing.journals import JournalGatewayQueries
    from pipeline.publishing.type_proceedings_journals import (
        run_type_proceedings_journals,
    )

    with open_tx() as conn:
        return run_type_proceedings_journals(log, journal_repo=JournalGatewayQueries(conn))


def _run_learn_journal_doi_namespaces() -> PhaseMetrics:
    from pipeline.publishing.journals import JournalGatewayQueries
    from pipeline.publishing.learn_journal_doi_namespaces import (
        run_learn_journal_doi_namespaces,
    )

    with open_tx() as conn:
        return run_learn_journal_doi_namespaces(log, journal_repo=JournalGatewayQueries(conn))


def _run_enrich_journals_from_doaj() -> PhaseMetrics:
    from pipeline.ingestion.doaj import downloaded_doaj_dump
    from pipeline.ingestion.http.polite_pool import build_user_agent
    from pipeline.publishing.import_journals_from_doaj_dump import (
        run_enrich_journals_from_doaj,
    )
    from pipeline.publishing.journals import JournalGatewayQueries
    from pipeline.runtime.config import (
        get_doaj_refresh_after_days,
        get_polite_pool_email_optional,
    )

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
