"""Métriques de la phase personnes : résultat d'une passe et assemblage final.

`CascadeResult` porte les compteurs d'une passe (`match` ou `create`) ; `build_metrics` fusionne ceux des deux passes avec les compteurs des étapes `reset`/`purge` en `PhaseMetrics`.
"""

import logging
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
    # Incrémental cross-source : les signatures cross-source re-jugées ce run, et celles réellement re-résolues. Le complément (candidates − résolues) est détaché par la phase.
    cross_source_candidate_ids: set[int]
    resolved_cross_source_ids: set[int]


def log_matching_breakdown(logger: logging.Logger, result: CascadeResult) -> None:
    """Loggue le nombre de rattachements par méthode et le nombre de créations."""
    matched = result.matched_counts
    breakdown = ", ".join(f"{method}={matched.get(method, 0)}" for method in _MATCHING_METHODS)
    logger.info("Rattachements par méthode : %s | créées : %d", breakdown, result.created)


def build_metrics(
    result: CascadeResult,
    *,
    transferred: int,
    cross_source_detached: int,
    reorphaned: int,
    deleted_persons: int,
) -> PhaseMetrics:
    """Assemble les métriques de la phase personnes depuis les compteurs de la cascade."""
    matched = result.matched_counts
    skipped = result.skipped_counts
    linked_total = sum(matched.values())
    created = result.created

    metrics = PhaseMetrics()
    metrics.add(total=result.in_perimeter_total, new=created, updated=linked_total)
    # Tableau « méthode de rattachement » : clés techniques (libellés portés par le frontend), ordre par fiabilité décroissante de la cascade.
    metrics.details["table"] = {
        "rows": [{"key": method, "count": matched.get(method, 0)} for method in _MATCHING_METHODS]
    }
    metrics.details["summary"] = {
        "created": created,
        "skipped_ambiguous": skipped.get("ambiguous_name_form", 0),
        "corroboration_rejected": result.corroboration_rejected,
        "identifiers_transferred": transferred,
        "cross_source_detached": cross_source_detached,
        "reorphaned_nominal": reorphaned,
        "deleted_empty_persons": deleted_persons,
    }
    return metrics
