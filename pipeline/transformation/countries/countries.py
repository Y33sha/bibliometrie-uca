"""Étape des pays de la phase `affiliations` : pays candidats des adresses en file, pays retenus, puis pays des contributions sources, des enregistrements sources et des publications. Chaque tâche a sa transaction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple

from sqlalchemy import Connection, text

from pipeline.graph import Step, Task, in_transaction
from pipeline.runtime.context import PhaseContext
from pipeline.runtime.observability.log_format import LAST_BRANCH, quantity
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


def _detect_by_country_name(ctx: PhaseContext) -> PhaseMetrics:
    """Relève l'état pays des adresses, puis cherche les pays candidats par nom de pays."""
    with ctx.open_tx() as conn:
        before = count_address_country_status(conn)
        metrics = detect_by_country_name.run(conn, ctx.logger)
    metrics.details[_STATUS_BEFORE] = before
    return metrics


def _resolve(ctx: PhaseContext) -> PhaseMetrics:
    """Choisit le pays des adresses parmi les pays candidats, puis relève l'état pays des adresses."""
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


_DETECTION_READS = (
    "place_name_forms",
    "countries",
    "addresses.id",
    "addresses.normalized_text",
    "address_candidates_queue",
)
"""Lectures des deux détections : noms de lieux et adresses en file."""


_DETECT_BY_COUNTRY_NAME = Task(
    "detect_by_country_name",
    # État pays des adresses citées par une publication, relevé avant la détection.
    reads=(*_DETECTION_READS, "addresses.countries", "addresses.publication_count"),
    writes=("address_country_candidates",),
    # Adresses marquées depuis la dernière résolution, retirées de la file par `resolve_countries` ; pays des adresses écrits par `resolve_countries` ; nombre de publications des adresses, recompté par `finalize`.
    previous_run=("address_candidates_queue", "addresses.countries", "addresses.publication_count"),
    run=_detect_by_country_name,
    section="Pays des adresses d'après le nom de pays qui les termine",
)


_DETECT_BY_PLACE_NAME = Task(
    "detect_by_place_name",
    reads=_DETECTION_READS,
    writes=("address_country_candidates",),
    # Adresses marquées depuis la dernière résolution, retirées de la file par `resolve_countries`.
    previous_run=("address_candidates_queue",),
    run=in_transaction(detect_by_place_name.run),
    section="Pays des adresses d'après les noms de villes et d'institutions",
)


_RESOLVE_COUNTRIES = Task(
    "resolve_countries",
    reads=(
        "address_country_candidates",
        "addresses.id",
        "addresses.countries",
        "addresses.publication_count",
        "address_candidates_queue",
    ),
    writes=(
        "addresses.countries",
        "address_countries_queue",
        "address_candidates_queue",
    ),
    # Nombre de publications des adresses, recompté par `finalize`.
    previous_run=("addresses.publication_count",),
    run=_resolve,
    section="Choix du pays des adresses parmi les pays trouvés",
)


_REFRESH_PUBLICATION_COUNTRIES = Task(
    "refresh_publication_countries",
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
    # Publications et rattachements des enregistrements sources, écrits par `publications.reconcile` et `finalize.purge_publications`.
    previous_run=("publications.id", "source_records.publication_id"),
    run=_refresh,
    section="Rafraîchissement des pays associés aux publications",
)


STEP = Step(
    "countries",
    "adresses → pays des adresses, des contributions sources, des enregistrements sources et des publications",
    (
        _DETECT_BY_COUNTRY_NAME,
        _DETECT_BY_PLACE_NAME,
        _RESOLVE_COUNTRIES,
        _REFRESH_PUBLICATION_COUNTRIES,
    ),
)


def funnel(by_task: Mapping[str, PhaseMetrics]) -> dict[str, float]:
    """Renvoie l'entonnoir des pays des adresses citées, tiré des relevés pris avant la détection et après le choix du pays : manque initial, pays rattachés par le run, reste."""
    initial = by_task[_DETECT_BY_COUNTRY_NAME.name].details[_STATUS_BEFORE]
    final = by_task[_RESOLVE_COUNTRIES.name].details[_STATUS_AFTER]
    assert isinstance(initial, AddressCountryStatus) and isinstance(final, AddressCountryStatus)
    total = final.total
    without_initial = total - initial.with_country
    return {
        "cited_addresses": total,
        "without_country_initial": without_initial,
        "without_country_pct": round(100 * without_initial / total, 1) if total else 0,
        "country_newly_attached": final.with_country - initial.with_country,
        "without_country_remaining": total - final.with_country,
    }
