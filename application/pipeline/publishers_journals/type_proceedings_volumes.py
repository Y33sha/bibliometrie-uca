"""Sous-étape de la phase `publishers_journals` — recalcule la nature des monographies, volume d'actes ou livre.

La nature se recalcule à chaque run d'après les enregistrements, la collection et le titre de la monographie (`is_proceedings_volume`) : elle suit les enregistrements quand ils changent, dans un sens comme dans l'autre. La sous-étape suit le typage des collections, dont elle lit le type.
"""

import logging

from application.pipeline.libelles import DERNIERE_BRANCHE, accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.monographs import MonographProceedingsQueries
from domain.monographs.proceedings import is_proceedings_volume


def run_type_proceedings_volumes(
    logger: logging.Logger, *, monograph_repo: MonographProceedingsQueries
) -> PhaseMetrics:
    """Pose la nature recalculée des monographies qui en changent, et journalise chacune."""
    to_proceedings: list[int] = []
    to_books: list[int] = []
    titles: dict[int, str] = {}
    for m in monograph_repo.find_monograph_proceedings_facts():
        proceedings = is_proceedings_volume(
            m.records, collection_type=m.collection_type, title=m.title
        )
        if proceedings != m.proceedings:
            (to_proceedings if proceedings else to_books).append(m.monograph_id)
            titles[m.monograph_id] = m.title
    metrics = PhaseMetrics()
    changed = len(to_proceedings) + len(to_books)
    if not changed:
        return metrics
    etape(
        logger,
        "Nature des monographies : %s, %s",
        accord(len(to_proceedings), "volume d'actes reconnu", "volumes d'actes reconnus"),
        accord(len(to_books), "livre reconnu", "livres reconnus"),
    )
    monograph_repo.set_monographs_proceedings(to_proceedings, True)
    monograph_repo.set_monographs_proceedings(to_books, False)
    for label, ids in (("volume d'actes", to_proceedings), ("livre", to_books)):
        for monograph_id in ids:
            # Ligne de détail : le terminal la masque, le journal la garde.
            logger.info(
                "Monographie devenue %s : %d « %s »",
                label,
                monograph_id,
                titles[monograph_id],
                extra={"detail": True},
            )
    metrics.add(
        total=changed,
        monographs_to_proceedings=len(to_proceedings),
        monographs_to_books=len(to_books),
    )
    logger.info(
        "%sTerminé : %s",
        DERNIERE_BRANCHE,
        accord(changed, "monographie retypée", "monographies retypées"),
    )
    return metrics
