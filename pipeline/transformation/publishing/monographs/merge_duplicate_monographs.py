"""Sous-étape de la phase `publishing` : fusion des monographies en double.

Deux monographies de même titre sont créées quand l'éditeur ou l'ISBN manque à une source, puis arrive par une autre. `duplicate_monographs` (`domain/monographs/matching.py`) désigne les fusions : une monographie rejoint la seule monographie compatible de son titre, quand celle-ci prime. Le journal garde le titre et les identifiants de chaque fusion.
"""

import logging
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.monographs.matching import MonographCandidate, duplicate_monographs
from pipeline.runtime.observability.log_format import quantity
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.monographs.monograph_merge import merge_monograph_into

LABEL = "Fusion des monographies en double"
"""Libellé de la sous-étape dans le journal de la phase."""


class MonographTitleGroup(NamedTuple):
    """Monographies qui partagent un titre normalisé, avec le titre de la plus ancienne."""

    title: str
    monographs: tuple[MonographCandidate, ...]


_TITLE_GROUPS = text("""
    SELECT (array_agg(title ORDER BY id))[1] AS title,
           array_agg(id ORDER BY id) AS ids,
           array_agg(isbn ORDER BY id) AS isbns,
           array_agg(eisbn ORDER BY id) AS eisbns,
           array_agg(publisher_id ORDER BY id) AS publisher_ids
    FROM monographs
    GROUP BY title_normalized
    HAVING count(*) > 1
    ORDER BY min(id)
""")


def find_monographs_sharing_a_title(conn: Connection) -> list[MonographTitleGroup]:
    """Renvoie les groupes d'au moins deux monographies de même titre normalisé."""
    return [
        MonographTitleGroup(
            r.title,
            tuple(
                MonographCandidate(*fields)
                for fields in zip(r.ids, r.isbns, r.eisbns, r.publisher_ids, strict=True)
            ),
        )
        for r in conn.execute(_TITLE_GROUPS)
    ]


def run_merge_duplicate_monographs(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Fusionne les monographies en double et journalise chaque fusion."""
    merges = [
        (group.title, target, source)
        for group in find_monographs_sharing_a_title(conn)
        for target, source in duplicate_monographs(group.monographs)
    ]
    metrics = PhaseMetrics()
    if not merges:
        return metrics
    for title, target, source in merges:
        merge_monograph_into(conn, target, source)
        # Ligne de détail : le terminal la masque, le journal la garde.
        logger.info(
            "Monographie %d fusionnée dans %d : « %s »",
            source,
            target,
            title,
            extra={"detail": True},
        )
    metrics.add(seen=len(merges), monographs_merged=len(merges))
    metrics.report = quantity(len(merges), "monographie fusionnée", "monographies fusionnées")
    return metrics
