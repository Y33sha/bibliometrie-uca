"""Tâche `affiliations.resolve_thesis_partners` : rattachement aux structures des PPN IdRef des laboratoires partenaires de thèse, par leurs noms.

Chaque PPN cité par un enregistrement source theses.fr est reconnu par les formes de nom de ses noms, comme une adresse. `idref_structures` garde la forme à l'origine de chaque détection ; ses liens se synchronisent comme ceux des adresses (`detections`).
"""

import logging
from collections import defaultdict

from sqlalchemy import Connection, text

from domain.normalize import normalize_text
from domain.source_records.source_extras import SourceExtra
from infrastructure.sql_fragments import source_extra_json
from pipeline.runtime.observability.log_format import LAST_BRANCH, step
from pipeline.transformation.structures.detections import (
    IDREF_STRUCTURES,
    Detection,
    sync_detections,
)
from pipeline.transformation.structures.name_recognition import StructureNameMatcher

_PARTNERS = text(f"""
    SELECT DISTINCT partner ->> 'ppn' AS ppn, partner ->> 'nom' AS name
    FROM source_records sr
    CROSS JOIN LATERAL jsonb_array_elements({source_extra_json(SourceExtra.PARTENAIRES)}) partner
    WHERE sr.source = 'theses' AND partner ->> 'ppn' IS NOT NULL AND partner ->> 'nom' IS NOT NULL
""")


def resolve_thesis_partners(conn: Connection, logger: logging.Logger) -> int:
    """Rattache chaque PPN de laboratoire partenaire aux structures que ses noms désignent. Renvoie le nombre de PPN rattachés à au moins une structure. L'appelant commite."""
    step(logger, "Identification des laboratoires partenaires de thèse")
    matcher = StructureNameMatcher.load(conn)
    detected: dict[tuple[str, int], int] = {}
    names_by_ppn: dict[str, list[str]] = defaultdict(list)
    for row in conn.execute(_PARTNERS):
        names_by_ppn[row.ppn].append(row.name)
    for ppn, names in names_by_ppn.items():
        for name in sorted(names):
            for match in matcher.resolve(normalize_text(name)):
                detected.setdefault((ppn, match.structure_id), match.form_id)
    sync_detections(
        conn,
        IDREF_STRUCTURES,
        [Detection(ppn, sid, fid) for (ppn, sid), fid in detected.items()],
    )
    resolved = len({ppn for ppn, _ in detected})
    logger.info(
        "%s%d laboratoires partenaires rattachés sur %d",
        LAST_BRANCH,
        resolved,
        len(names_by_ppn),
    )
    return resolved
