"""Phase `relations`, tâche `retracted` : indicateur « Rétracté » des publications (`publications.is_retracted`).

Une publication est rétractée sur l'un de ces signaux :

- une relation de rétractation la vise ;
- Crossref déclare une rétractation sur place : mise à jour `retraction` ou `withdrawal` vers le DOI de l'enregistrement source lui-même ;
- Crossref déclare un retrait (`withdrawal`) dans `update_to` : l'enregistrement source déclarant est le doublon retiré ;
- OpenAlex la marque rétractée.

Un avis de rétractation est exclu : il est sujet d'un `is_retraction_of`, ou objet d'un `has_retraction`. OpenAlex marque aussi les avis.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection, text

from domain.publications.relations import (
    CROSSREF_RETRACTION_UPDATE,
    CROSSREF_WITHDRAWAL_UPDATE,
    RelationType,
)
from domain.source_records.source_extras import SourceExtra
from domain.sources.registry import Source
from pipeline.graph import Task, in_transaction
from pipeline.runtime.observability.log_format import inflect, quantity
from pipeline.runtime.observability.metrics import PhaseMetrics

_RETRACTED_SQL = f"""
    WITH crossref_update AS (
        SELECT sr.publication_id, sr.source_id, u.key, u.value->>'type' AS type, u.value->>'doi' AS doi
        FROM source_records sr
        CROSS JOIN LATERAL (
            SELECT '{SourceExtra.UPDATE_TO}' AS key, value
            FROM jsonb_array_elements(coalesce(sr.source_extras->'{SourceExtra.UPDATE_TO}', '[]'))
            UNION ALL
            SELECT '{SourceExtra.UPDATED_BY}', value
            FROM jsonb_array_elements(coalesce(sr.source_extras->'{SourceExtra.UPDATED_BY}', '[]'))
        ) u
        WHERE sr.source = '{Source.CROSSREF.value}' AND sr.publication_id IS NOT NULL
    ),
    signal AS (
        SELECT from_publication_id AS id FROM publication_relations
        WHERE relation_type = '{RelationType.HAS_RETRACTION.value}'
        UNION
        SELECT target_publication_id FROM publication_relations
        WHERE relation_type = '{RelationType.IS_RETRACTION_OF.value}' AND target_publication_id IS NOT NULL
        UNION
        SELECT publication_id FROM crossref_update
        WHERE (type IN ('{CROSSREF_RETRACTION_UPDATE}', '{CROSSREF_WITHDRAWAL_UPDATE}') AND doi = source_id)
           OR (type = '{CROSSREF_WITHDRAWAL_UPDATE}' AND key = '{SourceExtra.UPDATE_TO}')
        UNION
        SELECT publication_id FROM source_records
        WHERE source = '{Source.OPENALEX.value}' AND is_retracted AND publication_id IS NOT NULL
    ),
    notice AS (
        SELECT from_publication_id AS id FROM publication_relations
        WHERE relation_type = '{RelationType.IS_RETRACTION_OF.value}'
        UNION
        SELECT target_publication_id FROM publication_relations
        WHERE relation_type = '{RelationType.HAS_RETRACTION.value}' AND target_publication_id IS NOT NULL
    ),
    retracted AS (
        SELECT id FROM signal EXCEPT SELECT id FROM notice
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
