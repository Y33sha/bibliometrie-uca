"""Sous-étape de la phase `publishers_journals` — rattache chaque monographie à sa collection.

Les monographies sans collection à ISSN se regroupent en séries (`group_series`, `domain/journals/series.py`) : même clé de série, même éditeur, au moins deux volumes. Chaque série a son entrée dans `journals`, sans ISSN, typée série d'actes ou collection de livres selon ses volumes. `choose_monograph_journal` (`domain/monographs/collection.py`) choisit ensuite l'entrée de chaque monographie : sa collection à ISSN, à défaut sa série sans ISSN, à défaut le volume lui-même, à défaut aucune. Une monographie en conflit reste en l'état, signalée. Le calcul se refait à chaque run, d'après les enregistrements.
"""

import logging

from application.pipeline.libelles import DERNIERE_BRANCHE, accord, etape
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.containers import MonographSeriesQueries
from application.ports.pipeline.monographs import MonographJournalCandidates
from application.services.journals.core import find_or_create_journal
from domain.journals.journal import JournalType
from domain.journals.series import VolumeTitle, group_series
from domain.monographs.collection import MonographJournalChoice, choose_monograph_journal


def _series_by_monograph(
    candidates: list[MonographJournalCandidates], repo: MonographSeriesQueries
) -> dict[int, int]:
    """Série sans ISSN de chaque monographie qui en a une, trouvée ou créée dans `journals`."""
    proceedings = {m.monograph_id: m.proceedings for m in candidates}
    series: dict[int, int] = {}
    for group in group_series(
        [
            VolumeTitle(m.monograph_id, m.title, m.publisher_id)
            for m in candidates
            if not m.with_issn
        ]
    ):
        series_id = find_or_create_journal(group.title, publisher_id=group.publisher_id, repo=repo)
        if series_id is None:
            continue
        kind = (
            JournalType.PROCEEDINGS
            if all(proceedings[i] for i in group.volume_ids)
            else JournalType.BOOK_SERIES
        )
        repo.set_journal_type_if_unknown(series_id, kind)
        series |= dict.fromkeys(group.volume_ids, series_id)
    return series


def run_link_monographs_to_collections(
    logger: logging.Logger, *, monograph_repo: MonographSeriesQueries
) -> PhaseMetrics:
    """Rattache les monographies à leur entrée de `journals`, et journalise chaque changement et chaque conflit."""
    candidates = monograph_repo.find_monograph_journal_candidates()
    series = _series_by_monograph(candidates, monograph_repo)
    changes: list[tuple[MonographJournalCandidates, MonographJournalChoice]] = []
    conflicts: list[tuple[MonographJournalCandidates, MonographJournalChoice]] = []
    for m in candidates:
        choice = choose_monograph_journal(m.with_issn, m.without_issn, series.get(m.monograph_id))
        if choice.conflict:
            conflicts.append((m, choice))
        elif choice.journal_id != m.journal_id:
            changes.append((m, choice))
    metrics = PhaseMetrics()
    if not (changes or conflicts):
        return metrics
    etape(logger, "Rattachement des monographies à leur collection")
    for m, choice in changes:
        monograph_repo.set_monograph_journal(m.monograph_id, choice.journal_id)
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Monographie %d « %s » rattachée à %s (au lieu de %s)",
            m.monograph_id,
            m.title,
            choice.journal_id,
            m.journal_id,
            extra={"detail": True},
        )
    for m, choice in conflicts:
        logger.warning(
            "Monographie %d « %s » : plusieurs rattachements possibles %s — laissée en l'état",
            m.monograph_id,
            m.title,
            list(choice.conflict),
            extra={"detail": True},
        )
    metrics.add(
        total=len(changes) + len(conflicts),
        monographs_linked=len(changes),
        monograph_collection_conflicts=len(conflicts),
        monograph_series=len(set(series.values())),
    )
    logger.info(
        "%sTerminé : %s, %s, %s",
        DERNIERE_BRANCHE,
        accord(len(set(series.values())), "série sans ISSN", "séries sans ISSN"),
        accord(len(changes), "monographie rattachée", "monographies rattachées"),
        accord(len(conflicts), "conflit", "conflits"),
    )
    return metrics
