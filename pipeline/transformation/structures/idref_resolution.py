"""Résolution des laboratoires partenaires de thèse : rattachement de leur PPN IdRef aux structures, par leur nom. Nœud `affiliations.resolve_thesis_partners`.

Chaque PPN cité par une notice theses.fr (`meta.partenaires`) est résolu par les formes de noms de ses noms, avec le moteur de la résolution des adresses. `idref_structures` garde la forme à l'origine de chaque détection. Comme pour les adresses, une détection qui disparaît est supprimée, et un lien confirmé ou infirmé par l'administration reste en place.
"""

import logging
from collections import defaultdict

from sqlalchemy import Connection, text

from domain.normalize import normalize_text
from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE, etape
from pipeline.transformation.structures.address_resolution import (
    AddressMatcher,
    AddressResolutionQueries,
)

_PARTNERS = text("""
    SELECT DISTINCT partner ->> 'ppn' AS ppn, partner ->> 'nom' AS name
    FROM source_publications sp
    CROSS JOIN LATERAL jsonb_array_elements(sp.meta -> 'partenaires') partner
    WHERE sp.source = 'theses' AND partner ->> 'ppn' IS NOT NULL AND partner ->> 'nom' IS NOT NULL
""")

# Liens détectés : tableaux parallèles (PPN, structure, forme).
_DETECTED = (
    "unnest(CAST(:ppns AS text[]), CAST(:sids AS int[]), CAST(:fids AS int[])) AS d(ppn, sid, fid)"
)

_DELETE_OBSOLETE = text(f"""
    DELETE FROM idref_structures i
    WHERE i.is_confirmed IS NULL
      AND NOT EXISTS (SELECT 1 FROM {_DETECTED} WHERE d.ppn = i.idref_ppn AND d.sid = i.structure_id)
""")

_UNFLAG_OBSOLETE = text(f"""
    UPDATE idref_structures i SET matched_form_id = NULL
    WHERE i.is_confirmed IS NOT NULL AND i.matched_form_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM {_DETECTED} WHERE d.ppn = i.idref_ppn AND d.sid = i.structure_id)
""")

_UPSERT_DETECTED = text(f"""
    INSERT INTO idref_structures (idref_ppn, structure_id, matched_form_id)
    SELECT d.ppn, d.sid, d.fid FROM {_DETECTED}
    ON CONFLICT (idref_ppn, structure_id) DO UPDATE SET matched_form_id = EXCLUDED.matched_form_id
        WHERE idref_structures.matched_form_id IS DISTINCT FROM EXCLUDED.matched_form_id
""")


def resolve_thesis_partners(conn: Connection, logger: logging.Logger) -> int:
    """Rattache chaque PPN de laboratoire partenaire aux structures que ses noms désignent. Rend le nombre de PPN rattachés à au moins une structure. Le commit est à la charge de l'appelant."""
    etape(logger, "Identification des laboratoires partenaires de thèse")
    matcher = AddressMatcher(AddressResolutionQueries().load_name_forms(conn))
    detected: dict[tuple[str, int], int] = {}
    names_by_ppn: dict[str, list[str]] = defaultdict(list)
    for row in conn.execute(_PARTNERS):
        names_by_ppn[row.ppn].append(row.name)
    for ppn, names in names_by_ppn.items():
        for name in sorted(names):
            for match in matcher.resolve(normalize_text(name)):
                detected.setdefault((ppn, match.structure_id), match.form_id)
    params = {
        "ppns": [ppn for ppn, _ in detected],
        "sids": [sid for _, sid in detected],
        "fids": list(detected.values()),
    }
    conn.execute(_DELETE_OBSOLETE, params)
    conn.execute(_UNFLAG_OBSOLETE, params)
    conn.execute(_UPSERT_DETECTED, params)
    resolved = len({ppn for ppn, _ in detected})
    logger.info(
        "%s%d laboratoires partenaires rattachés sur %d",
        DERNIERE_BRANCHE,
        resolved,
        len(names_by_ppn),
    )
    return resolved
