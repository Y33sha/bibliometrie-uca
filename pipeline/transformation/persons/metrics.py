"""Métriques de la phase personnes, assemblées depuis les compteurs de ses tâches."""

from collections.abc import Mapping

from domain.persons.group_matching import GroupMatchReason, GroupOutcome
from pipeline.runtime.observability.metrics import PhaseMetrics


def build_metrics(
    *,
    resolution: Mapping[str, int],
    arbitration: Mapping[str, int],
    name_forms: Mapping[str, int],
    purge: Mapping[str, int],
) -> PhaseMetrics:
    """Métriques de la phase : compteurs du rattachement des groupes (`resolve_groups`), de l'arbitrage des identifiants, de la régénération des formes de nom et de la purge.

    `details.table` compte les groupes rattachés pendant le run, par mode de résolution (`GroupMatchReason`), et ceux qui fondent une personne (`created`). Le mode `manual` réunit les épinglages appliqués et les décisions par épinglage.
    """
    attached = {
        reason: resolution.get(f"{GroupOutcome.MATCH}:{reason}", 0) for reason in GroupMatchReason
    }
    attached[GroupMatchReason.MANUAL] += resolution.get("pinned", 0)
    created = resolution.get(f"{GroupOutcome.CREATE}:{GroupMatchReason.NAME}", 0)

    metrics = PhaseMetrics()
    metrics.add(seen=resolution.get("groups", 0), new=created, updated=sum(attached.values()))
    # Clés techniques : le frontend donne les libellés.
    metrics.details["table"] = {
        "rows": [
            *({"key": str(reason), "count": count} for reason, count in attached.items()),
            {"key": "created", "count": created},
        ]
    }
    metrics.details["summary"] = {
        **resolution,
        "identifiers_neutralized": arbitration.get("neutralized", 0),
        "identifiers_transferred": arbitration.get("transferred", 0),
        "ambiguous_marked": purge.get("ambiguous_marked", 0),
        "deleted_attributions": purge.get("deleted_attributions", 0),
        "deleted_persons": purge.get("deleted_persons", 0),
        **{f"name_forms_{key}": count for key, count in name_forms.items()},
    }
    return metrics
