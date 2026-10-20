"""Orchestrateur de la phase `countries` : pays candidats des adresses, résolution, et recalcul en cascade.

Quatre tâches (`pipeline.graph`), chacune dans sa propre transaction :

1. `countries.ror` — candidats `ror` : pays des organisations ROR de l'affiliation de chaque adresse.
2. `countries.detect` — candidats `country_name`, `institution` et `city` des adresses à traiter (`candidates_dirty`).
3. `countries.resolve` — `addresses.countries` composé des candidats par la préséance du domaine.
4. `countries.refresh_publication_countries` — recalcul des caches dénormalisés (signatures, source_publications, publications).

L'état pays des adresses est relevé avant et après le passage : l'entonnoir qui s'en déduit — manque initial, pays rattachés par le run, reste — alimente l'observabilité de la phase. Chaque sous-étape dit au journal ce qu'elle a résolu.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.runtime.context import OpenTransaction, Phase, PhaseContext
from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE, accord, etape
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.structures.countries import (
    detect_by_country_name,
    detect_by_place_name,
    refresh_publication_countries,
)
from pipeline.transformation.structures.countries.countries_queries import (
    AddressCountryStatus,
    CountryQueries,
)


def _etat_des_adresses(open_tx: OpenTransaction, queries: CountryQueries) -> AddressCountryStatus:
    """Relève combien d'adresses ont un pays."""
    with open_tx() as conn:
        return queries.count_address_country_status(conn)


@dataclass(frozen=True)
class CountriesPhase:
    queries: CountryQueries

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les tâches, borne l'entonnoir par les deux relevés et assemble les métriques."""
        open_tx, queries = ctx.open_tx, self.queries
        initial = _etat_des_adresses(open_tx, queries)

        def ror(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            etape(ctx.logger, "Pays des adresses d'après leurs organisations ROR")
            with ctx.open_tx() as conn:
                added = queries.insert_ror_candidates(conn)
            ctx.logger.info("%spays trouvé pour %s", DERNIERE_BRANCHE, accord(added, "adresse"))
            return PhaseMetrics(new=added)

        def detect(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            metrics = PhaseMetrics()
            with ctx.open_tx() as conn:
                metrics.merge(detect_by_country_name.run(conn, queries, ctx.logger))
            with ctx.open_tx() as conn:
                metrics.merge(detect_by_place_name.run(conn, queries, ctx.logger))
            return metrics

        def resolve(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            etape(ctx.logger, "Choix du pays des adresses parmi les pays trouvés")
            with ctx.open_tx() as conn:
                changed = queries.resolve_address_countries(conn)
            ctx.logger.info(
                "%s%s",
                DERNIERE_BRANCHE,
                accord(changed, "adresse mise à jour", "adresses mises à jour"),
            )
            return PhaseMetrics(updated=changed)

        def refresh(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                refresh_publication_countries.refresh(conn, queries, ctx.logger)
            return PhaseMetrics()

        by_task = run_tasks(
            "countries",
            {
                "countries.ror": TaskStep(ror),
                "countries.detect": TaskStep(detect),
                "countries.resolve": TaskStep(resolve),
                "countries.refresh_publication_countries": TaskStep(refresh),
            },
            ctx,
        )
        metrics = PhaseMetrics()
        for node_metrics in by_task.values():
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
        }
        return metrics


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    from pipeline.transformation.structures.countries.countries_queries import CountryQueries

    return CountriesPhase(CountryQueries())
