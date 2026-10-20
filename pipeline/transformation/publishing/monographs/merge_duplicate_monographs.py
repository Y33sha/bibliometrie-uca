"""Sous-étape de la phase `publishers_journals` — fusionne les monographies en double.

Deux monographies de même titre naissent quand l'éditeur ou l'ISBN manque à l'une des sources, puis arrive par une autre. `duplicate_monographs` (`domain/monographs/matching.py`) désigne les fusions : une monographie rejoint la seule monographie compatible de son titre, quand celle-ci en dit davantage. Le journal garde le titre et les identifiants de chaque fusion.
"""

import logging
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.merge import MergedEntity
from domain.monographs.matching import MonographCandidate, duplicate_monographs
from infrastructure.repositories.merge_steps import record_redirect
from pipeline.runtime.observability.libelles import accord
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publishing.monographs.store import MonographStore

LIBELLE = "Fusion des monographies en double"
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

_MOVE_RECORDS = text("UPDATE source_publications SET monograph_id = :t WHERE monograph_id = :s")
_MOVE_PUBLICATIONS = text("UPDATE publications SET monograph_id = :t WHERE monograph_id = :s")
_SOURCE_FIELDS = text("""
    SELECT proceedings, year, isbn, eisbn, publisher_id, journal_id FROM monographs WHERE id = :s
""")
_RELEASE_SOURCE_ISBNS = text("UPDATE monographs SET isbn = NULL, eisbn = NULL WHERE id = :s")
_DELETE_SOURCE = text("DELETE FROM monographs WHERE id = :s")


def find_monographs_sharing_a_title(conn: Connection) -> list[MonographTitleGroup]:
    """Groupes d'au moins deux monographies de même titre normalisé."""
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


def merge_monograph_into(conn: Connection, target_id: int, source_id: int) -> None:
    """Reporte sur `target_id` les enregistrements et les publications de `source_id`, complète les champs vides de la cible, supprime la source et enregistre sa redirection."""
    params = {"t": target_id, "s": source_id}
    conn.execute(_MOVE_RECORDS, params)
    conn.execute(_MOVE_PUBLICATIONS, params)
    source = conn.execute(_SOURCE_FIELDS, params).one()
    # La source libère ses ISBN avant que la cible les reçoive : la contrainte d'unicité le demande.
    conn.execute(_RELEASE_SOURCE_ISBNS, params)
    MonographStore(conn).enrich_monograph(
        target_id,
        proceedings=source.proceedings,
        year=source.year,
        isbn=source.isbn,
        eisbn=source.eisbn,
        publisher_id=source.publisher_id,
        journal_id=source.journal_id,
    )
    conn.execute(_DELETE_SOURCE, params)
    record_redirect(conn, MergedEntity.MONOGRAPH, target_id, source_id)


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
    metrics.report = accord(len(merges), "monographie fusionnée", "monographies fusionnées")
    return metrics
