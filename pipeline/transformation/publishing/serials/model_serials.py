"""Tâche de la phase `publishing` : modèle open access des revues.

Une revue du Diamond Discovery Hub, ou présente dans le DOAJ sans APC ni autres frais, est `diamond`. Une autre revue en open access intégral d'après OpenAlex est `full_oa`, une revue présente dans OpenAlex hors open access intégral `subscription`. Le modèle d'une revue absente d'OpenAlex est inconnu. Un modèle saisi à la main reste en l'état.
"""

import logging

from sqlalchemy import Connection, and_, case, or_, update

from domain.serials.serial import OaModel
from domain.serials.serial_lists import DIAMOND_DISCOVERY_HUB, DOAJ
from infrastructure.db.tables import oa_model_enum, serials
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.serials.store import OA_MODEL_NOT_MANUAL, in_list

LABEL = "Modèle open access des revues"
"""Libellé de la tâche dans le journal de la phase."""

_DIAMOND = or_(
    in_list(DIAMOND_DISCOVERY_HUB),
    and_(
        in_list(DOAJ),
        serials.c.doaj_payload["APC"].astext == "No",
        serials.c.doaj_payload["Has other fees"].astext == "No",
    ),
)

_MODEL = case(
    (_DIAMOND, OaModel.DIAMOND.value),
    (serials.c.openalex_is_oa.is_(True), OaModel.FULL_OA.value),
    (serials.c.openalex_is_oa.is_(False), OaModel.SUBSCRIPTION.value),
).cast(oa_model_enum)


def model_serials(conn: Connection) -> int:
    """Écrit le modèle open access des revues. Renvoie le nombre de revues modifiées."""
    return conn.execute(
        update(serials)
        .where(serials.c.oa_model.is_distinct_from(_MODEL), OA_MODEL_NOT_MANUAL)
        .values(oa_model=_MODEL)
    ).rowcount


def run_model_serials(conn: Connection, logger: logging.Logger) -> PhaseMetrics:  # noqa: ARG001
    """Écrit le modèle open access des revues (`model_serials`) et en fait le bilan."""
    changed = model_serials(conn)
    metrics = PhaseMetrics()
    metrics.add(updated=changed)
    metrics.report = quantity(changed, "revue modifiée", "revues modifiées")
    return metrics
