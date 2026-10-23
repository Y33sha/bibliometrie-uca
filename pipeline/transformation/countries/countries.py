"""Orchestrateur de la phase `countries` : pays candidats des adresses, résolution, et recalcul en cascade.

Quatre tâches (`pipeline.graph`), chacune dans sa propre transaction :

1. `countries.ror` — candidats `ror` : pays des organisations ROR de l'affiliation de chaque adresse.
2. `countries.detect` — candidats `country_name`, `institution` et `city` des adresses en file (`address_candidates_queue`).
3. `countries.resolve` — `addresses.countries` composé des candidats par la préséance du domaine.
4. `countries.refresh_publication_countries` — recalcul des caches dénormalisés (contributions sources, source_records, publications).

L'état pays des adresses est relevé avant et après le passage : l'entonnoir qui s'en déduit — manque initial, pays rattachés par le run, reste — alimente l'observabilité de la phase. Chaque sous-étape dit au journal ce qu'elle a résolu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy import Connection, text

from pipeline.runtime.context import OpenTransaction, Phase, PhaseContext
from pipeline.runtime.observability.log_format import LAST_BRANCH, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import TaskStep, run_tasks
from pipeline.transformation.countries import (
    detect_by_country_name,
    detect_by_place_name,
    refresh_publication_countries,
)
from pipeline.transformation.countries.resolution import resolve_queued_addresses
from pipeline.transformation.countries.store import CountryCandidatesStore


class AddressCountryStatus(NamedTuple):
    """Bilan de l'état pays des adresses (restreint à `publication_count > 0`)."""

    total: int
    with_country: int


def count_address_country_status(conn: Connection) -> AddressCountryStatus:
    """Bilan de la résolution des pays sur les adresses utiles (`publication_count > 0`)."""
    row = conn.execute(
        text("""
            SELECT
                count(*) AS total,
                count(*) FILTER (WHERE countries IS NOT NULL) AS with_country
            FROM addresses
            WHERE publication_count > 0
        """)
    ).one()
    return AddressCountryStatus(row.total, row.with_country)


def _address_status(open_tx: OpenTransaction) -> AddressCountryStatus:
    """Relève combien d'adresses ont un pays."""
    with open_tx() as conn:
        return count_address_country_status(conn)


@dataclass(frozen=True)
class CountriesPhase:
    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute les tâches, borne l'entonnoir par les deux relevés et assemble les métriques."""
        initial = _address_status(ctx.open_tx)

        def ror(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            step(ctx.logger, "Pays des adresses d'après leurs organisations ROR")
            with ctx.open_tx() as conn:
                added = CountryCandidatesStore(conn).add_ror()
            ctx.logger.info("%spays trouvé pour %s", LAST_BRANCH, quantity(added, "adresse"))
            return PhaseMetrics(new=added)

        def detect(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            metrics = PhaseMetrics()
            with ctx.open_tx() as conn:
                metrics.merge(detect_by_country_name.run(conn, ctx.logger))
            with ctx.open_tx() as conn:
                metrics.merge(detect_by_place_name.run(conn, ctx.logger))
            return metrics

        def resolve(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            step(ctx.logger, "Choix du pays des adresses parmi les pays trouvés")
            with ctx.open_tx() as conn:
                changed = resolve_queued_addresses(conn)
            ctx.logger.info(
                "%s%s",
                LAST_BRANCH,
                quantity(changed, "adresse mise à jour", "adresses mises à jour"),
            )
            return PhaseMetrics(updated=changed)

        def refresh(ctx: PhaseContext, _breaker: object) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                refresh_publication_countries.refresh(conn, ctx.logger)
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
        for task_metrics in by_task.values():
            metrics.merge(task_metrics)

        final = _address_status(ctx.open_tx)
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
    return CountriesPhase()
