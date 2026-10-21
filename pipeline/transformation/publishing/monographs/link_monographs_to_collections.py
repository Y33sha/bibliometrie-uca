"""Sous-étape de la phase `publishers_journals` — rattache chaque monographie à sa collection.

Les monographies sans collection à ISSN se regroupent en séries (`group_series`, `domain/journals/series.py`) : même clé de série, même éditeur, au moins deux volumes. Chaque série a son entrée dans `journals`, sans ISSN, typée série d'actes ou collection de livres selon ses volumes. `choose_monograph_journal` (`domain/monographs/collection.py`) choisit ensuite l'entrée de chaque monographie : sa collection à ISSN, à défaut sa série sans ISSN, à défaut le volume lui-même, à défaut aucune. Une monographie en conflit reste en l'état, signalée. Le calcul se refait à chaque run, d'après les enregistrements.
"""

import logging
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.journals.journal import JournalType
from domain.journals.series import VolumeTitle, group_series
from domain.monographs.collection import MonographJournalChoice, choose_monograph_journal
from infrastructure.sql_fragments import has_active_issn
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.find_or_create import find_or_create_journal
from pipeline.transformation.publishing.journals.store import JournalStore

LABEL = "Rattachement aux collections"
"""Libellé de la sous-étape dans le journal de la phase."""


class MonographJournalCandidates(NamedTuple):
    """Une monographie, son éditeur, sa nature, son `journal_id`, et les entrées de `journals` de ses enregistrements, à ISSN et sans ISSN."""

    monograph_id: int
    title: str
    publisher_id: int | None
    proceedings: bool
    journal_id: int | None
    with_issn: tuple[int, ...]
    without_issn: tuple[int, ...]


_JOURNAL_CANDIDATES = text(f"""
    WITH entrees AS (
        SELECT DISTINCT s.monograph_id, s.journal_id,
               {has_active_issn("s.journal_id")} AS a_issn
        FROM source_records s
        WHERE s.monograph_id IS NOT NULL
    )
    SELECT m.id, m.title, m.publisher_id, m.proceedings, m.journal_id,
           coalesce(array_agg(e.journal_id ORDER BY e.journal_id) FILTER (
               WHERE e.journal_id IS NOT NULL AND e.a_issn
           ), '{{}}') AS with_issn,
           coalesce(array_agg(e.journal_id ORDER BY e.journal_id) FILTER (
               WHERE e.journal_id IS NOT NULL AND NOT e.a_issn
           ), '{{}}') AS without_issn
    FROM monographs m
    JOIN entrees e ON e.monograph_id = m.id
    GROUP BY m.id
    ORDER BY m.id
""")

_SET_JOURNAL = text("UPDATE monographs SET journal_id = :journal_id WHERE id = :id")


def find_monograph_journal_candidates(conn: Connection) -> list[MonographJournalCandidates]:
    """Chaque monographie portée par au moins un enregistrement, avec les entrées de `journals` de ses enregistrements."""
    return [
        MonographJournalCandidates(
            r.id,
            r.title,
            r.publisher_id,
            r.proceedings,
            r.journal_id,
            tuple(r.with_issn),
            tuple(r.without_issn),
        )
        for r in conn.execute(_JOURNAL_CANDIDATES)
    ]


def set_monograph_journal(conn: Connection, monograph_id: int, journal_id: int | None) -> None:
    """Pose le `journal_id` d'une monographie."""
    conn.execute(_SET_JOURNAL, {"id": monograph_id, "journal_id": journal_id})


def _series_by_monograph(
    candidates: list[MonographJournalCandidates], repo: JournalStore
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


def run_link_monographs_to_collections(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Rattache les monographies à leur entrée de `journals`, et journalise chaque changement et chaque conflit."""
    candidates = find_monograph_journal_candidates(conn)
    series = _series_by_monograph(candidates, JournalStore(conn))
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
    for m, choice in changes:
        set_monograph_journal(conn, m.monograph_id, choice.journal_id)
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
        seen=len(changes) + len(conflicts),
        monographs_linked=len(changes),
        monograph_collection_conflicts=len(conflicts),
        monograph_series=len(set(series.values())),
    )
    metrics.report = (
        f"{quantity(len(set(series.values())), 'série sans ISSN', 'séries sans ISSN')}, "
        f"{quantity(len(changes), 'monographie rattachée', 'monographies rattachées')}, "
        f"{quantity(len(conflicts), 'conflit', 'conflits')}"
    )
    return metrics
