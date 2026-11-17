"""Phase `relations`, tâche `retracted` : indicateur « Rétracté » des publications (`publications.is_retracted`).

Une publication est rétractée sur l'un de ces signaux :

- elle a un avis de rétractation (`has_retraction`) ;
- Crossref déclare une rétractation sur place : mise à jour `retraction` ou `withdrawal` vers le DOI de l'enregistrement source lui-même ;
- OpenAlex la marque rétractée.

Un retrait (`withdrawal`) vers un autre DOI désigne un doublon éditorial de l'article original : le doublon reste hors de la réconciliation (`is_matchable`), l'original n'est pas rétracté.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection, text

from domain.publications.relations import RelationType
from domain.source_records.notices import CROSSREF_RETRACTION_UPDATE, CROSSREF_WITHDRAWAL_UPDATE
from domain.source_records.source_extras import SourceExtra
from domain.sources.registry import Source
from pipeline.graph import Task, in_transaction
from pipeline.runtime.observability.log_format import inflect, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics

_RETRACTED_SQL = f"""
    WITH crossref_update AS (
        SELECT sr.publication_id, sr.source_id, u.value->>'type' AS type, u.value->>'doi' AS doi
        FROM source_records sr
        CROSS JOIN LATERAL jsonb_array_elements(
            coalesce(sr.source_extras->'{SourceExtra.UPDATE_TO}', '[]')
            || coalesce(sr.source_extras->'{SourceExtra.UPDATED_BY}', '[]')
        ) u
        WHERE sr.source = '{Source.CROSSREF.value}' AND sr.publication_id IS NOT NULL
    ),
    retracted AS (
        SELECT from_publication_id AS id FROM publication_relations
        WHERE relation_type = '{RelationType.HAS_RETRACTION.value}'
        UNION
        SELECT publication_id FROM crossref_update
        WHERE type IN ('{CROSSREF_RETRACTION_UPDATE}', '{CROSSREF_WITHDRAWAL_UPDATE}') AND doi = source_id
        UNION
        SELECT publication_id FROM source_records
        WHERE source = '{Source.OPENALEX.value}' AND is_retracted AND publication_id IS NOT NULL
    )
"""
"""Publications rétractées (`retracted`), d'après les signaux de la docstring du module."""

_WRITE_SQL = text(f"""
    {_RETRACTED_SQL}
    UPDATE publications p
    SET is_retracted = NOT p.is_retracted, updated_at = now()
    WHERE p.is_retracted <> EXISTS (SELECT 1 FROM retracted r WHERE r.id = p.id)
    RETURNING p.is_retracted
""")
"""Inverse l'indicateur des publications dont l'état change. Renvoie le nouvel état de chacune."""


def mark_retracted(conn: Connection, _logger: logging.Logger) -> PhaseMetrics:
    """Écrit l'indicateur « Rétracté » des publications. Renvoie le nombre de publications rétractées et les changements."""
    changed = [r.is_retracted for r in conn.execute(_WRITE_SQL)]
    marked = sum(changed)
    unmarked = len(changed) - marked
    total = conn.execute(text("SELECT count(*) FROM publications WHERE is_retracted")).scalar_one()
    metrics = PhaseMetrics()
    metrics.add(updated=len(changed), seen=total)
    metrics.report = (
        f"{quantity(total, 'publication rétractée', 'publications rétractées')}"
        f" ({marked} {inflect(marked, 'marquée')}, {unmarked} {inflect(unmarked, 'démarquée')})"
    )
    return metrics


TASKS = (
    Task(
        "retracted",
        reads=(
            "publication_relations",
            *(
                f"source_records.{column}"
                for column in (
                    "source",
                    "source_id",
                    "source_extras",
                    "is_retracted",
                    "publication_id",
                )
            ),
            "publications.is_retracted",
        ),
        writes=("publications.is_retracted",),
        run=in_transaction(mark_retracted),
        label="Publications rétractées",
    ),
)
