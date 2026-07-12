"""Métriques de la phase personnes : résultat d'une passe et assemblage final.

`CascadeResult` porte les compteurs d'une passe (`match` ou `create`) ; `build_metrics` fusionne ceux des deux passes avec les compteurs des étapes `reset`/`purge` en `PhaseMetrics`.
"""

import logging
from collections import defaultdict
from typing import NamedTuple

from application.pipeline.metrics import PhaseMetrics

# Méthodes de rattachement, par fiabilité décroissante de la cascade.
_MATCHING_METHODS = ("orcid", "hal_person_id", "idref", "cross_source", "single_name")


class CascadeResult(NamedTuple):
    """Compteurs d'une passe (`match` ou `create`), agrégés en métriques de phase."""

    matched_counts: dict[str, int]
    skipped_counts: dict[str, int]
    created: int
    corroboration_rejected: int
    out_of_perimeter_matched: int
    in_perimeter_total: int
    out_of_perimeter_total: int


def log_matching_breakdown(
    logger: logging.Logger, match_result: CascadeResult, create_result: CascadeResult
) -> None:
    """Loggue le nombre de rattachements par méthode (cumul des passes `match` + `create`) et le nombre de créations."""
    matched: dict[str, int] = defaultdict(int)
    for r in (match_result, create_result):
        for method, count in r.matched_counts.items():
            matched[method] += count
    breakdown = ", ".join(f"{method}={matched[method]}" for method in _MATCHING_METHODS)
    logger.info("Rattachements par méthode : %s | créées : %d", breakdown, create_result.created)


def build_metrics(
    match_result: CascadeResult,
    create_result: CascadeResult,
    *,
    transferred: int,
    reset_cross: int,
    reorphaned: int,
    deleted_persons: int,
) -> PhaseMetrics:
    """Assemble les métriques de la phase personnes depuis les compteurs de chaque étape."""
    matched: dict[str, int] = defaultdict(int)
    for r in (match_result, create_result):
        for method, count in r.matched_counts.items():
            matched[method] += count
    skipped: dict[str, int] = defaultdict(int)
    for r in (match_result, create_result):
        for reason, count in r.skipped_counts.items():
            skipped[reason] += count

    linked_total = sum(matched.values())
    created = create_result.created

    metrics = PhaseMetrics()
    metrics.add(total=match_result.in_perimeter_total, new=created, updated=linked_total)
    # Tableau « méthode de rattachement » : clés techniques (libellés portés par le frontend), ordre par fiabilité décroissante de la cascade.
    metrics.details["table"] = {
        "rows": [{"key": method, "count": matched[method]} for method in _MATCHING_METHODS]
    }
    metrics.details["summary"] = {
        "created": created,
        "skipped_ambiguous": skipped["ambiguous_name_form"],
        "corroboration_rejected": match_result.corroboration_rejected,
        "identifiers_transferred": transferred,
        "reset_cross_source": reset_cross,
        "reorphaned_nominal": reorphaned,
        "deleted_empty_persons": deleted_persons,
    }
    return metrics
