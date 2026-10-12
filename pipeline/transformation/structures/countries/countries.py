"""Orchestrateur de la phase `countries` : détection du pays des adresses et recalcul en cascade.

Trois nœuds (`pipeline.graph`) et quatre sous-étapes, chacune dans sa propre transaction :

1. **detect_by_country_name** (nœud `countries.detect`) — pays déduit du nom de pays qui termine l'adresse.
2. **detect_by_place_name** (nœud `countries.detect`) — pays déduit d'un nom de lieu (institution, ville).
3. **suggest_address_countries** (nœud `countries.suggest`) — suggestion floue (commits par lots). `retry_empty` (mode `full`) réessaie les adresses tentées sans match.
4. **refresh_publication_countries** (nœud `countries.refresh_publication_countries`) — recalcul des caches dénormalisés (source_publications, publications) depuis `addresses.countries`.

L'état pays des adresses est relevé avant et après le passage : l'entonnoir qui s'en déduit — manque initial, pays rattachés par le run, reste — alimente l'observabilité de la phase. Chaque sous-étape dit au journal ce qu'elle a résolu.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.node_runner import NodeStep, run_nodes
from pipeline.runtime.context import OpenTransaction, Phase, PhaseContext
from pipeline.runtime.modes import MODES
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.structures.countries import (
    detect_by_country_name,
    detect_by_place_name,
    refresh_publication_countries,
    suggest_countries,
)
from pipeline.transformation.structures.countries.countries_queries import (
    AddressCountryStatus,
    CountryQueries,
)


def _etat_des_adresses(open_tx: OpenTransaction, queries: CountryQueries) -> AddressCountryStatus:
    """Relève combien d'adresses portent un pays, une suggestion, ou rien."""
    with open_tx() as conn:
        return queries.count_address_country_status(conn)


@dataclass(frozen=True)
class CountriesPhase:
    queries: CountryQueries

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les trois nœuds, borne l'entonnoir par les deux relevés et assemble les métriques."""
        open_tx, queries = ctx.open_tx, self.queries
        initial = _etat_des_adresses(open_tx, queries)

        def detect(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            metrics = PhaseMetrics()
            with ctx.open_tx() as conn:
                metrics.merge(detect_by_country_name.run(conn, queries, ctx.logger))
            with ctx.open_tx() as conn:
                metrics.merge(detect_by_place_name.run(conn, queries, ctx.logger))
            return metrics

        def suggest(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            retry_empty = MODES[ctx.options.mode].retry_empty_country_suggestions
            with ctx.open_tx() as conn:
                return suggest_countries.run(conn, queries, ctx.logger, retry_empty=retry_empty)

        def refresh(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                refresh_publication_countries.refresh(conn, queries, ctx.logger)
            return PhaseMetrics()

        by_node = run_nodes(
            "countries",
            {
                "countries.detect": NodeStep(detect),
                "countries.suggest": NodeStep(suggest),
                "countries.refresh_publication_countries": NodeStep(refresh),
            },
            ctx,
        )
        metrics = PhaseMetrics()
        for node_metrics in by_node.values():
            metrics.merge(node_metrics)

        final = _etat_des_adresses(open_tx, queries)
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
        # Chaque sous-étape journalise ce qu'elle a résolu : une ligne de clôture les répéterait.
        metrics.resume = ""
        return metrics


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    """Détection des pays des adresses et recalcul sur les publications."""
    from pipeline.transformation.structures.countries.countries_queries import CountryQueries

    return CountriesPhase(CountryQueries())
