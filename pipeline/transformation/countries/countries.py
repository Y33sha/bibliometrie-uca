"""Phase `countries` : pays candidats des adresses en file, pays retenus, puis pays des contributions sources, des enregistrements sources et des publications. Chaque tâche a sa transaction.

L'état pays des adresses, relevé avant la détection et après le choix du pays, donne l'entonnoir de la phase : manque initial, pays rattachés par le run, reste.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple

from sqlalchemy import Connection, text

from pipeline.graph import Task
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import LAST_BRANCH, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
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


_STATUS_BEFORE = "address_status_before"
_STATUS_AFTER = "address_status_after"


def _detect(ctx: PhaseContext) -> PhaseMetrics:
    """Relève l'état pays des adresses, puis cherche les pays candidats par nom de pays et par nom de lieu."""
    metrics = PhaseMetrics()
    with ctx.open_tx() as conn:
        before = count_address_country_status(conn)
        metrics.merge(detect_by_country_name.run(conn, ctx.logger))
    with ctx.open_tx() as conn:
        metrics.merge(detect_by_place_name.run(conn, ctx.logger))
    metrics.details[_STATUS_BEFORE] = before
    return metrics


def _resolve(ctx: PhaseContext) -> PhaseMetrics:
    """Choisit le pays des adresses parmi les pays candidats, puis relève l'état pays des adresses."""
    step(ctx.logger, "Choix du pays des adresses parmi les pays trouvés")
    with ctx.open_tx() as conn:
        changed = resolve_queued_addresses(conn)
        after = count_address_country_status(conn)
    ctx.logger.info(
        "%s%s",
        LAST_BRANCH,
        quantity(changed, "adresse mise à jour", "adresses mises à jour"),
    )
    metrics = PhaseMetrics(updated=changed)
    metrics.details[_STATUS_AFTER] = after
    return metrics


def _refresh(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        refresh_publication_countries.refresh(conn, ctx.logger)
    return PhaseMetrics()


TASKS = (
    Task(
        "countries.detect",
        reads=(
            "place_name_forms",
            "countries",
            "addresses.id",
            "addresses.normalized_text",
            "address_candidates_queue",
        ),
        writes=("address_country_candidates",),
        # Adresses marquées depuis la dernière résolution, retirées de la file par `countries.resolve`.
        previous_run=("address_candidates_queue",),
        run=_detect,
    ),
    Task(
        "countries.resolve",
        reads=(
            "address_country_candidates",
            "addresses.id",
            "addresses.countries",
            "address_candidates_queue",
        ),
        writes=(
            "addresses.countries",
            "address_countries_queue",
            "address_candidates_queue",
        ),
        run=_resolve,
    ),
    Task(
        "countries.refresh_publication_countries",
        reads=(
            "source_contribution_countries_queue",
            "source_contributions.source_record_id",
            "source_contributions.countries",
            "source_contribution_addresses",
            "source_contribution_rors",
            "source_contribution_hal_structures",
            "ror_organizations",
            "hal_structures",
            "hal_structure_aliases",
            "addresses.countries",
            "address_countries_queue",
            "source_records.publication_id",
            "source_records.countries",
            "publications.id",
        ),
        writes=(
            "source_contributions.countries",
            "source_records.countries",
            "publications.countries",
            "source_contribution_countries_queue",
            "address_countries_queue",
        ),
        run=_refresh,
    ),
)


def assemble(by_task: Mapping[str, PhaseMetrics]) -> PhaseMetrics:
    """Renvoie la somme des métriques des tâches, avec l'entonnoir tiré des deux relevés de l'état pays des adresses."""
    metrics = PhaseMetrics()
    for task_metrics in by_task.values():
        metrics.merge(task_metrics)
    initial = metrics.details.pop(_STATUS_BEFORE)
    final = metrics.details.pop(_STATUS_AFTER)
    assert isinstance(initial, AddressCountryStatus) and isinstance(final, AddressCountryStatus)
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
