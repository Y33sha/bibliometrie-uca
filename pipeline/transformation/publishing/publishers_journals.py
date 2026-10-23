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

`enrich_journals_from_doaj` importe le dump CSV du DOAJ, qui fait autorité sur `is_in_doaj`, quand le dernier import date de plus que le délai `doaj_refresh_after_days`. L'enrichissement des éditeurs — pays, ROR, type — se lance à la demande, par `interfaces/cli/maintenance/enrich_publishers.py`.

Chaque sous-étape est une tâche du graphe (`pipeline.graph`), exécutée par `pipeline.task_runner` dans l'ordre du graphe : une ligne du journal par tâche, sous le titre de sa section. Une tâche qui interroge une source passe par l'accès à cette source : sans identifiants, elle est sautée avec un signal `source_unconfigured`. Ici, les étapes de chaque tâche et l'assemblage des métriques.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from domain.config import ConfigKey
from pipeline.http.polite_pool import default_user_agent
from pipeline.ingestion.api_params import (
    API_BASE_URLS,
    SUDOC_MAX_CONCURRENT,
)
from pipeline.ingestion.complements.doaj import downloaded_doaj_dump
from pipeline.ingestion.complements.sudoc import fetch_ppns, fetch_serial_record
from pipeline.ingestion.crossref.prefixes import fetch_crossref_prefix
from pipeline.ingestion.datacite.prefixes import fetch_datacite_prefix
from pipeline.ingestion.openalex.journal_enrichment import fetch_sources_batch
from pipeline.runtime.config import delay
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.publishing.doi_prefixes import DoiPrefixStore
from pipeline.transformation.publishing.journals import (
    check_journals_in_sudoc,
    enrich_journals_from_doaj,
    enrich_journals_from_openalex,
    learn_journal_doi_namespaces,
    merge_duplicate_journals,
    type_proceedings_journals,
)
from pipeline.transformation.publishing.journals.check_journals_in_sudoc import (
    run_check_journals_in_sudoc,
)
from pipeline.transformation.publishing.journals.enrich_journals_from_doaj import (
    run_enrich_journals_from_doaj,
)
from pipeline.transformation.publishing.journals.enrich_journals_from_openalex import (
    run_enrich_journals_from_openalex,
)
from pipeline.transformation.publishing.journals.journal_merge import merge_journals
from pipeline.transformation.publishing.journals.learn_journal_doi_namespaces import (
    run_learn_journal_doi_namespaces,
)
from pipeline.transformation.publishing.journals.merge_duplicate_journals import (
    run_merge_duplicate_journals,
)
from pipeline.transformation.publishing.journals.type_proceedings_journals import (
    run_type_proceedings_journals,
)
from pipeline.transformation.publishing.monographs import (
    link_monographs_to_collections,
    merge_duplicate_monographs,
    type_proceedings_volumes,
)
from pipeline.transformation.publishing.monographs.link_monographs_to_collections import (
    run_link_monographs_to_collections,
)
from pipeline.transformation.publishing.monographs.merge_duplicate_monographs import (
    run_merge_duplicate_monographs,
)
from pipeline.transformation.publishing.monographs.type_proceedings_volumes import (
    run_type_proceedings_volumes,
)
from pipeline.transformation.publishing.publishers import resolve_publishers
from pipeline.transformation.publishing.publishers.resolve_publishers import (
    run_resolve_crossref_publishers,
    run_resolve_datacite_publishers,
)
from pipeline.transformation.publishing.publishers.store import PublisherStore

_PHASE = "publishers_journals"


@dataclass(frozen=True)
class PublishersJournalsPhase:
    """`steps` associe à chaque tâche de la phase son étape (`TaskStep`)."""

    steps: Mapping[str, TaskStep]

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les tâches de la phase et assemble ses métriques."""
        by_task = run_tasks(_PHASE, self.steps, ctx)
        metrics = PhaseMetrics()
        _assemble(metrics, {name.removeprefix(f"{_PHASE}."): m for name, m in by_task.items()})
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
    # Les compteurs et signaux des sous-étapes remontent à la phase : l'observabilité (`to_payload()`) et le passage en avertissement sur circuit-breaker tripé en dépendent. Les `details` sur-mesure sont posés juste après.
    for sub in by_step.values():
        metrics.merge(sub)

    metrics.details["table"] = {
        "rows": [
            {
                "key": key,
                "traités": by_step[field].total,
                "identifiés": identifies(by_step[field]),
                "créés": by_step[field].extras.get("publisher_created", 0),
            }
            for field, key, identifies in _TABLE
        ]
    }
    # DOAJ : ligne à part (sous-étape conditionnelle, métrique propre).
    metrics.details["summary"] = {
        "doaj_matched": by_step["enrich_journals_from_doaj"].extras.get("matched", 0)
    }


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    return PublishersJournalsPhase(
        {
            f"{_PHASE}.{name}": step
            for name, step in {
                "resolve_crossref_publishers": TaskStep(
                    _run_resolve_crossref_publishers,
                    "Éditeurs",
                    resolve_publishers.LABELS["Crossref"],
                ),
                "resolve_datacite_publishers": TaskStep(
                    _run_resolve_datacite_publishers,
                    "Éditeurs",
                    resolve_publishers.LABELS["DataCite"],
                ),
                # Trois lots consécutifs en 429 disent le quota OpenAlex du jour épuisé : le reste attend le run suivant.
                "enrich_journals_from_openalex": TaskStep(
                    _run_enrich_journals_from_openalex,
                    "Revues",
                    enrich_journals_from_openalex.LABEL,
                    threshold=3,
                ),
                "check_journals_in_sudoc": TaskStep(
                    _run_check_journals_in_sudoc,
                    "Revues",
                    check_journals_in_sudoc.LABEL,
                    threshold=3,
                ),
                "merge_duplicate_journals": TaskStep(
                    _run_merge_duplicate_journals, "Revues", merge_duplicate_journals.LABEL
                ),
                "type_proceedings_journals": TaskStep(
                    _run_type_proceedings_journals, "Revues", type_proceedings_journals.LABEL
                ),
                "learn_journal_doi_namespaces": TaskStep(
                    _run_learn_journal_doi_namespaces,
                    "Revues",
                    learn_journal_doi_namespaces.LABEL,
                ),
                "enrich_journals_from_doaj": TaskStep(
                    _run_enrich_journals_from_doaj,
                    "Revues",
                    enrich_journals_from_doaj.LABEL,
                ),
                "merge_duplicate_monographs": TaskStep(
                    _run_merge_duplicate_monographs,
                    "Monographies",
                    merge_duplicate_monographs.LABEL,
                ),
                "link_monographs_to_collections": TaskStep(
                    _run_link_monographs_to_collections,
                    "Monographies",
                    link_monographs_to_collections.LABEL,
                ),
                "type_proceedings_volumes": TaskStep(
                    _run_type_proceedings_volumes,
                    "Monographies",
                    type_proceedings_volumes.LABEL,
                ),
            }.items()
        }
    )


def _run_resolve_crossref_publishers(
    ctx: PhaseContext,
) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_resolve_crossref_publishers(
            conn,
            ctx.logger,
            prefix_store=DoiPrefixStore(conn),
            publisher_store=PublisherStore(conn),
            fetch_prefix_fn=fetch_crossref_prefix,
        )


def _run_resolve_datacite_publishers(
    ctx: PhaseContext,
) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_resolve_datacite_publishers(
            conn,
            ctx.logger,
            prefix_store=DoiPrefixStore(conn),
            publisher_store=PublisherStore(conn),
            fetch_prefix_fn=fetch_datacite_prefix,
        )


def _run_enrich_journals_from_openalex(
    ctx: PhaseContext,
) -> PhaseMetrics:
    sources_api = API_BASE_URLS["openalex_sources"]
    with ctx.open_tx() as conn:
        return run_enrich_journals_from_openalex(
            conn,
            ctx.logger,
            fetch_batch=lambda oa_ids: fetch_sources_batch(
                oa_ids, openalex_sources_api=sources_api
            ),
        )


def _run_check_journals_in_sudoc(
    ctx: PhaseContext,
) -> PhaseMetrics:
    base_url = API_BASE_URLS["sudoc"]
    with ctx.open_tx() as conn:
        # `asyncio.run` transmet aux coroutines la ContextVar du circuit-breaker.
        return asyncio.run(
            run_check_journals_in_sudoc(
                conn,
                ctx.logger,
                fetch_ppns=lambda client, issns: fetch_ppns(client, issns, base_url=base_url),
                fetch_record=lambda client, ppn: fetch_serial_record(
                    client, ppn, base_url=base_url
                ),
                max_concurrent=SUDOC_MAX_CONCURRENT,
            )
        )


def _run_merge_duplicate_journals(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:

        def merge(target_id: int, source_id: int) -> None:
            merge_journals(conn, target_id, source_id)
            conn.commit()

        return run_merge_duplicate_journals(conn, ctx.logger, merge=merge)


def _run_merge_duplicate_monographs(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_merge_duplicate_monographs(conn, ctx.logger)


def _run_link_monographs_to_collections(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_link_monographs_to_collections(conn, ctx.logger)


def _run_type_proceedings_volumes(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_type_proceedings_volumes(conn, ctx.logger)


def _run_type_proceedings_journals(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_type_proceedings_journals(conn, ctx.logger)


def _run_learn_journal_doi_namespaces(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        return run_learn_journal_doi_namespaces(conn, ctx.logger)


def _run_enrich_journals_from_doaj(ctx: PhaseContext) -> PhaseMetrics:
    user_agent = default_user_agent()
    with ctx.open_tx() as conn:
        return run_enrich_journals_from_doaj(
            conn,
            ctx.logger,
            refresh_after_days=delay(conn, ConfigKey.DOAJ_REFRESH_AFTER_DAYS),
            download_dump=lambda: downloaded_doaj_dump(user_agent=user_agent, logger=ctx.logger),
        )
