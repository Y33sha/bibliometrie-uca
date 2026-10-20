"""Résolution des laboratoires partenaires de thèse : rattachement de leur PPN IdRef aux structures, par leur nom. Tâche `affiliations.resolve_thesis_partners`.

Chaque PPN cité par une notice theses.fr (`meta.partenaires`) est résolu par les formes de noms de ses noms, comme les adresses. `idref_structures` garde la forme à l'origine de chaque détection. Comme pour les adresses, une détection qui disparaît est supprimée, et un lien confirmé ou infirmé par l'administration reste en place.
"""

import logging
from collections import defaultdict

from sqlalchemy import Connection, text

from domain.normalize import normalize_text
from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE, etape
from pipeline.transformation.structures.detections import (
    IDREF_STRUCTURES,
    Detection,
    sync_detections,
)
from pipeline.transformation.structures.name_recognition import StructureNameMatcher

_PARTNERS = text("""
    SELECT DISTINCT partner ->> 'ppn' AS ppn, partner ->> 'nom' AS name
    FROM source_publications sp
    CROSS JOIN LATERAL jsonb_array_elements(sp.meta -> 'partenaires') partner
    WHERE sp.source = 'theses' AND partner ->> 'ppn' IS NOT NULL AND partner ->> 'nom' IS NOT NULL
""")


def resolve_thesis_partners(conn: Connection, logger: logging.Logger) -> int:
    """Rattache chaque PPN de laboratoire partenaire aux structures que ses noms désignent. Rend le nombre de PPN rattachés à au moins une structure. Le commit est à la charge de l'appelant."""
    etape(logger, "Identification des laboratoires partenaires de thèse")
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
        DERNIERE_BRANCHE,
        resolved,
        len(names_by_ppn),
    )
    return resolved
