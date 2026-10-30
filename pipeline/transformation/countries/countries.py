"""Phase `countries` : pays candidats des adresses en file, pays retenus, puis pays des contributions sources, des enregistrements sources et des publications. Chaque tâche a sa transaction.

L'état pays des adresses, relevé avant et après, donne l'entonnoir de la phase : manque initial, pays rattachés par le run, reste.
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


class AddressCountryStatus(NamedTuple):
    """Bilan pays des adresses citées par au moins une publication."""

    total: int
    with_country: int


def count_address_country_status(conn: Connection) -> AddressCountryStatus:
    """Renvoie le bilan pays des adresses citées par au moins une publication (`publication_count > 0`)."""
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
        """Exécute les tâches, relève l'état pays des adresses avant et après, puis assemble les métriques."""
        initial = _address_status(ctx.open_tx)

        def detect(ctx: PhaseContext) -> PhaseMetrics:
            metrics = PhaseMetrics()
            with ctx.open_tx() as conn:
                metrics.merge(detect_by_country_name.run(conn, ctx.logger))
            with ctx.open_tx() as conn:
                metrics.merge(detect_by_place_name.run(conn, ctx.logger))
            return metrics

        def resolve(ctx: PhaseContext) -> PhaseMetrics:
            step(ctx.logger, "Choix du pays des adresses parmi les pays trouvés")
            with ctx.open_tx() as conn:
                changed = resolve_queued_addresses(conn)
            ctx.logger.info(
                "%s%s",
                LAST_BRANCH,
                quantity(changed, "adresse mise à jour", "adresses mises à jour"),
            )
            return PhaseMetrics(updated=changed)

        def refresh(ctx: PhaseContext) -> PhaseMetrics:
            with ctx.open_tx() as conn:
                refresh_publication_countries.refresh(conn, ctx.logger)
            return PhaseMetrics()

        by_task = run_tasks(
            "countries",
            {
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


def build() -> Phase:
    return CountriesPhase()
