"""Orchestrateur de la phase `publishers_journals` : enrichissement des référentiels d'éditeurs, de revues et de monographies.

Trois groupes de sous-étapes, dans l'ordre :

- **Éditeurs** — `resolve_crossref_publishers`, puis `resolve_datacite_publishers` : éditeur Crossref, provider et repository DataCite de chaque préfixe DOI en attente.
- **Revues** — `enrich_journals_from_openalex` (type et frais de publication), `check_journals_in_sudoc` (ISSN vérifiés, corrigés et rangés par support), `merge_duplicate_journals`, `type_proceedings_journals`, `learn_journal_doi_namespaces`, `enrich_journals_from_doaj`.
- **Monographies** — `merge_duplicate_monographs`, `link_monographs_to_collections`, `type_proceedings_volumes`.

Contraintes d'ordre :

- OpenAlex type les revues `unknown` avant le typage en recueil d'actes, qui vise aussi les revues `unknown`.
- La vérification Sudoc précède la fusion des revues, qui lit l'ISSN-L, et l'import DOAJ, qui apparie les revues par ISSN.
- Les espaces de noms DOI suivent la fusion et le typage des revues.
- Le rattachement des monographies suit la fusion des revues. La nature des monographies lit le type de la collection que pose le rattachement.

Chaque sous-étape est un nœud du graphe (`pipeline.graph`), exécuté par `pipeline.node_runner` dans l'ordre du graphe : une ligne du journal par nœud, sous le titre de sa section. Un nœud qui interroge une source passe par l'accès à cette source : sans identifiants, il est sauté avec un signal `source_unconfigured`. Ici, les étapes de chaque nœud et l'assemblage des métriques.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pipeline.http.circuit_breaker import SourceCircuitBreaker
from pipeline.node_runner import NodeStep, run_nodes
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.execution import log, open_tx
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.journals import (
    check_journals_in_sudoc,
    enrich_journals_from_openalex,
    import_journals_from_doaj_dump,
    learn_journal_doi_namespaces,
    merge_duplicate_journals,
    type_proceedings_journals,
)
from pipeline.transformation.publishing.monographs import (
    link_monographs_to_collections,
    merge_duplicate_monographs,
    type_proceedings_volumes,
)
from pipeline.transformation.publishing.publishers import resolve_publishers

_GROUP = "publishers_journals"


@dataclass(frozen=True)
class PublishersJournalsPhase:
    """`steps` associe à chaque nœud de la phase son étape (`NodeStep`)."""

    steps: Mapping[str, NodeStep]

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les nœuds de la phase et assemble ses métriques."""
        by_node = run_nodes(_GROUP, self.steps, ctx)
        metrics = PhaseMetrics()
        _assemble(metrics, {name.removeprefix(f"{_GROUP}."): m for name, m in by_node.items()})
        return metrics


# Ligne de la table d'observabilité de chaque sous-étape : son champ, son libellé, et ce qui compte comme identifié.
_TABLE: tuple[tuple[str, str, Callable[[PhaseMetrics], int]], ...] = (
    (
        "resolve_crossref_publishers",
        "préfixes DOI Crossref → éditeurs",
        lambda m: m.extras.get("publisher_matched", 0),
    ),
    (
        "resolve_datacite_publishers",
        "préfixes DOI DataCite → éditeurs",
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

    metrics.details["table"] = {
        "rows": [
            {
                "key": key,
                "traités": by_step[champ].total,
                "identifiés": identifies(by_step[champ]),
                "créés": by_step[champ].extras.get("publisher_created", 0),
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

    `resolve_crossref_publishers` et `resolve_datacite_publishers` rattachent chaque préfixe DOI en attente à son éditeur, via l'API `/prefixes` de son agence. `enrich_journals_from_openalex` lit dans OpenAlex Sources les frais de publication et le type des revues encore typées `unknown`. `check_journals_in_sudoc` vérifie dans le Sudoc les ISSN des revues jamais vérifiées, les corrige et les range par support. `enrich_journals_from_doaj` importe le dump CSV du DOAJ, qui fait autorité sur `is_in_doaj`, quand le dernier import date de plus que le délai `doaj_refresh_after_days`.

    La phase suit `normalize`, qui crée les éditeurs et les revues à enrichir. L'enrichissement des éditeurs eux-mêmes — pays, ROR, type — se lance à la demande, par `interfaces/cli/maintenance/enrich_publishers.py`.
    """

    return PublishersJournalsPhase(
        {
            f"{_GROUP}.{name}": step
            for name, step in {
                "resolve_crossref_publishers": NodeStep(
                    _run_resolve_crossref_publishers,
                    "Éditeurs",
                    resolve_publishers.LIBELLES["Crossref"],
                ),
                "resolve_datacite_publishers": NodeStep(
                    _run_resolve_datacite_publishers,
                    "Éditeurs",
                    resolve_publishers.LIBELLES["DataCite"],
                ),
                # Trois lots consécutifs en 429 disent le quota OpenAlex du jour épuisé : le reste attend le run suivant.
                "enrich_journals_from_openalex": NodeStep(
                    _run_enrich_journals_from_openalex,
                    "Revues",
                    enrich_journals_from_openalex.LIBELLE,
                    threshold=3,
                ),
                "check_journals_in_sudoc": NodeStep(
                    _run_check_journals_in_sudoc,
                    "Revues",
                    check_journals_in_sudoc.LIBELLE,
                    threshold=3,
                ),
                "merge_duplicate_journals": NodeStep(
                    _run_merge_duplicate_journals, "Revues", merge_duplicate_journals.LIBELLE
                ),
                "type_proceedings_journals": NodeStep(
                    _run_type_proceedings_journals, "Revues", type_proceedings_journals.LIBELLE
                ),
                "learn_journal_doi_namespaces": NodeStep(
                    _run_learn_journal_doi_namespaces,
                    "Revues",
                    learn_journal_doi_namespaces.LIBELLE,
                ),
                "enrich_journals_from_doaj": NodeStep(
                    _run_enrich_journals_from_doaj,
                    "Revues",
                    import_journals_from_doaj_dump.LIBELLE,
                ),
                "merge_duplicate_monographs": NodeStep(
                    _run_merge_duplicate_monographs,
                    "Monographies",
                    merge_duplicate_monographs.LIBELLE,
                ),
                "link_monographs_to_collections": NodeStep(
                    _run_link_monographs_to_collections,
                    "Monographies",
                    link_monographs_to_collections.LIBELLE,
                ),
                "type_proceedings_volumes": NodeStep(
                    _run_type_proceedings_volumes,
                    "Monographies",
                    type_proceedings_volumes.LIBELLE,
                ),
            }.items()
        }
    )


def _run_resolve_crossref_publishers(
    _ctx: PhaseContext, breaker: SourceCircuitBreaker | None
) -> PhaseMetrics:
    from pipeline.ingestion.crossref.prefixes import fetch_crossref_prefix
    from pipeline.transformation.publishing.doi_prefixes import DoiPrefixesQueries
    from pipeline.transformation.publishing.publishers.publishers import PublisherGatewayQueries
    from pipeline.transformation.publishing.publishers.resolve_publishers import (
        run_resolve_crossref_publishers,
    )

    user_agent = _prefixes_user_agent()
    with open_tx() as conn:
        return run_resolve_crossref_publishers(
            conn,
            log,
            repo=DoiPrefixesQueries(conn),
            publisher_repo=PublisherGatewayQueries(conn),
            fetch_prefix_fn=lambda client, prefix, sample_doi: fetch_crossref_prefix(
                client, prefix, sample_doi, user_agent=user_agent
            ),
            breaker=breaker,
        )


def _run_resolve_datacite_publishers(
    _ctx: PhaseContext, breaker: SourceCircuitBreaker | None
) -> PhaseMetrics:
    from pipeline.ingestion.datacite.prefixes import fetch_datacite_prefix
    from pipeline.transformation.publishing.doi_prefixes import DoiPrefixesQueries
    from pipeline.transformation.publishing.publishers.publishers import PublisherGatewayQueries
    from pipeline.transformation.publishing.publishers.resolve_publishers import (
        run_resolve_datacite_publishers,
    )

    user_agent = _prefixes_user_agent()
    with open_tx() as conn:
        return run_resolve_datacite_publishers(
            conn,
            log,
            repo=DoiPrefixesQueries(conn),
            publisher_repo=PublisherGatewayQueries(conn),
            fetch_prefix_fn=lambda client, prefix: fetch_datacite_prefix(
                client, prefix, user_agent=user_agent
            ),
            breaker=breaker,
        )


def _prefixes_user_agent() -> str:
    from pipeline.http.polite_pool import build_user_agent
    from pipeline.runtime.config import get_polite_pool_email_optional

    return build_user_agent(get_polite_pool_email_optional() or "")


def _run_enrich_journals_from_openalex(
    _ctx: PhaseContext, breaker: SourceCircuitBreaker | None
) -> PhaseMetrics:
    assert breaker is not None, "nœud à source : l'exécuteur pose le circuit-breaker"
    from pipeline.ingestion.api_params import API_BASE_URLS, OPENALEX_DELAY
    from pipeline.ingestion.openalex.journal_enrichment import fetch_sources_batch
    from pipeline.transformation.publishing.journals.enrich_journals_from_openalex import (
        run_enrich_journals_from_openalex,
    )
    from pipeline.transformation.publishing.journals.journals import JournalGatewayQueries

    sources_api = API_BASE_URLS["openalex_sources"]
    with open_tx() as conn:
        return run_enrich_journals_from_openalex(
            conn,
            log,
            journal_repo=JournalGatewayQueries(conn),
            fetch_batch=lambda oa_ids: fetch_sources_batch(
                oa_ids, openalex_sources_api=sources_api
            ),
            breaker=breaker,
            rate_delay=OPENALEX_DELAY,
        )


def _run_check_journals_in_sudoc(
    _ctx: PhaseContext, breaker: SourceCircuitBreaker | None
) -> PhaseMetrics:
    assert breaker is not None, "nœud à source : l'exécuteur pose le circuit-breaker"
    from pipeline.ingestion.api_params import (
        API_BASE_URLS,
        SUDOC_MAX_CONCURRENT,
        SUDOC_MAX_PER_SECOND,
    )
    from pipeline.ingestion.complements.sudoc import fetch_ppns, fetch_serial_record
    from pipeline.transformation.publishing.journals.check_journals_in_sudoc import (
        run_check_journals_in_sudoc,
    )
    from pipeline.transformation.publishing.journals.journals import JournalGatewayQueries

    base_url = API_BASE_URLS["sudoc"]
    with open_tx() as conn:
        # `asyncio.run` transmet aux coroutines la ContextVar du circuit-breaker.
        return asyncio.run(
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
        )


def _run_merge_duplicate_journals(
    _ctx: PhaseContext, _breaker: SourceCircuitBreaker | None
) -> PhaseMetrics:
    from pipeline.transformation.publishing.journals.journal_merge import merge_journals
    from pipeline.transformation.publishing.journals.journals import JournalGatewayQueries
    from pipeline.transformation.publishing.journals.merge_duplicate_journals import (
        run_merge_duplicate_journals,
    )

    with open_tx() as conn:

        def merge(target_id: int, source_id: int) -> None:
            merge_journals(conn, target_id, source_id)
            conn.commit()

        return run_merge_duplicate_journals(
            log, journal_repo=JournalGatewayQueries(conn), merge=merge
        )


def _run_merge_duplicate_monographs(
    _ctx: PhaseContext, _breaker: SourceCircuitBreaker | None
) -> PhaseMetrics:
    from pipeline.transformation.publishing.monographs.merge_duplicate_monographs import (
        run_merge_duplicate_monographs,
    )
    from pipeline.transformation.publishing.monographs.monographs import MonographGatewayQueries

    with open_tx() as conn:
        return run_merge_duplicate_monographs(log, monograph_repo=MonographGatewayQueries(conn))


def _run_link_monographs_to_collections(
    _ctx: PhaseContext, _breaker: SourceCircuitBreaker | None
) -> PhaseMetrics:
    from pipeline.transformation.publishing.containers import ContainerGatewayQueries
    from pipeline.transformation.publishing.monographs.link_monographs_to_collections import (
        run_link_monographs_to_collections,
    )

    with open_tx() as conn:
        return run_link_monographs_to_collections(log, monograph_repo=ContainerGatewayQueries(conn))


def _run_type_proceedings_volumes(
    _ctx: PhaseContext, _breaker: SourceCircuitBreaker | None
) -> PhaseMetrics:
    from pipeline.transformation.publishing.monographs.monographs import MonographGatewayQueries
    from pipeline.transformation.publishing.monographs.type_proceedings_volumes import (
        run_type_proceedings_volumes,
    )

    with open_tx() as conn:
        return run_type_proceedings_volumes(log, monograph_repo=MonographGatewayQueries(conn))


def _run_type_proceedings_journals(
    _ctx: PhaseContext, _breaker: SourceCircuitBreaker | None
) -> PhaseMetrics:
    from pipeline.transformation.publishing.journals.journals import JournalGatewayQueries
    from pipeline.transformation.publishing.journals.type_proceedings_journals import (
        run_type_proceedings_journals,
    )

    with open_tx() as conn:
        return run_type_proceedings_journals(log, journal_repo=JournalGatewayQueries(conn))


def _run_learn_journal_doi_namespaces(
    _ctx: PhaseContext, _breaker: SourceCircuitBreaker | None
) -> PhaseMetrics:
    from pipeline.transformation.publishing.journals.journals import JournalGatewayQueries
    from pipeline.transformation.publishing.journals.learn_journal_doi_namespaces import (
        run_learn_journal_doi_namespaces,
    )

    with open_tx() as conn:
        return run_learn_journal_doi_namespaces(log, journal_repo=JournalGatewayQueries(conn))


def _run_enrich_journals_from_doaj(
    _ctx: PhaseContext, _breaker: SourceCircuitBreaker | None
) -> PhaseMetrics:
    from pipeline.http.polite_pool import build_user_agent
    from pipeline.ingestion.complements.doaj import downloaded_doaj_dump
    from pipeline.runtime.config import (
        get_doaj_refresh_after_days,
        get_polite_pool_email_optional,
    )
    from pipeline.transformation.publishing.journals.import_journals_from_doaj_dump import (
        run_enrich_journals_from_doaj,
    )
    from pipeline.transformation.publishing.journals.journals import JournalGatewayQueries

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
