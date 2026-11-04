# STATUS: oneshot (2026-11-01)
"""Écrit l'identifiant contenu dans le `source_id` des enregistrements sources qui n'ont ni identifiant primaire ni identifiant dérivé.

Crossref et DataCite ont pour `source_id` leur DOI, HAL son identifiant HAL, theses.fr le NNT d'une thèse soutenue : chacun est l'identifiant primaire. Le `source_id` ScanR contient l'identifiant dérivé (`halhal-01234567`). Un enregistrement source qui a un identifiant primaire ou dérivé, même retiré, reste tel quel. Chaque enregistrement source complété est mis en file pour la réconciliation.

Usage :
    uv run python -m interfaces.cli.oneshot.restore_identifiers_from_source_id [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from collections.abc import Callable

from sqlalchemy import Connection, text

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
    normalize_identifiers,
)
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue_ids
from infrastructure.observability.log import setup_logger
from pipeline.ingestion.scanr.payload import scanr_derived_identifier

log = setup_logger("restore_identifiers_from_source_id", os.path.dirname(__file__))

_NNT = re.compile(r"[0-9]{4}[0-9A-Z]+")
"""Le `source_id` d'une thèse soutenue est son NNT : l'année, puis des lettres et des chiffres. Celui d'une thèse en cours est son identifiant theses.fr (`s123456`)."""


def _primary(id_type: SourceIdentifierType) -> Callable[[str], SourceIdentifier]:
    return lambda source_id: SourceIdentifier(id_type, source_id, SourceIdentifierRole.PRIMARY)


def _thesis_nnt(source_id: str) -> SourceIdentifier | None:
    if not _NNT.fullmatch(source_id):
        return None
    return SourceIdentifier(SourceIdentifierType.NNT, source_id, SourceIdentifierRole.PRIMARY)


_IDENTIFIER_OF_SOURCE_ID: dict[str, Callable[[str], SourceIdentifier | None]] = {
    "crossref": _primary(SourceIdentifierType.DOI),
    "datacite": _primary(SourceIdentifierType.DOI),
    "hal": _primary(SourceIdentifierType.HAL_ID),
    "theses": _thesis_nnt,
    "scanr": scanr_derived_identifier,
}

_WITHOUT_IDENTIFIER = text("""
    SELECT sr.id, sr.source::text AS source, sr.source_id
    FROM source_records sr
    WHERE sr.source::text = ANY(:sources)
      AND NOT EXISTS (
          SELECT 1 FROM source_record_identifiers i
          WHERE i.source_record_id = sr.id AND i.role IN ('primary', 'derived')
      )
    ORDER BY sr.id
""")

_INSERT = text("""
    INSERT INTO source_record_identifiers (source_record_id, id_type, id_value, role)
    SELECT i.source_record_id, CAST(i.id_type AS source_identifier_type), i.id_value,
           CAST(i.role AS source_identifier_role)
    FROM jsonb_to_recordset(CAST(:rows AS jsonb))
        AS i(source_record_id integer, id_type text, id_value text, role text)
""")


def _identifier(source: str, source_id: str) -> SourceIdentifier | None:
    """Renvoie l'identifiant normalisé contenu dans le `source_id`, ou `None` pour un `source_id` qui n'en contient pas."""
    identifier = _IDENTIFIER_OF_SOURCE_ID[source](source_id)
    if identifier is None:
        return None
    identifiers, _ = normalize_identifiers([identifier])
    return identifiers[0] if identifiers else None


def restore_identifiers(conn: Connection, *, dry_run: bool = False) -> Counter[str]:
    """Écrit les identifiants manquants et met leurs enregistrements sources en file. Renvoie les comptes par source et par issue."""
    rows = conn.execute(_WITHOUT_IDENTIFIER, {"sources": list(_IDENTIFIER_OF_SOURCE_ID)}).all()
    counts: Counter[str] = Counter()
    restored: list[dict[str, object]] = []
    for r in rows:
        identifier = _identifier(r.source, r.source_id)
        if identifier is None:
            counts[f"{r.source}, source_id sans identifiant"] += 1
            continue
        counts[f"{r.source}, identifiant {identifier.role.value} écrit"] += 1
        restored.append(
            {
                "source_record_id": r.id,
                "id_type": identifier.id_type.value,
                "id_value": identifier.value,
                "role": identifier.role.value,
            }
        )
    if restored and not dry_run:
        conn.execute(_INSERT, {"rows": json.dumps(restored)})
        enqueue_ids(conn, Queue.SOURCE_RECORD_KEYS, [row["source_record_id"] for row in restored])
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte sans rien écrire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        log.info("Recherche des enregistrements sources sans identifiant primaire ni dérivé…")
        counts = restore_identifiers(conn, dry_run=args.dry_run)
        for label, count in sorted(counts.items()):
            log.info("%s : %d", label, count)
        if args.dry_run:
            log.info("Dry-run, rien écrit.")
        else:
            conn.commit()


if __name__ == "__main__":
    main()
