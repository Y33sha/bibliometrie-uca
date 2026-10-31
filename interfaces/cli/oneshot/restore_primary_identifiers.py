# STATUS: oneshot (2026-11-01)
"""Écrit l'identifiant primaire des enregistrements sources qui n'en ont pas, d'après leur `source_id`.

Crossref et DataCite ont pour `source_id` leur DOI, HAL son identifiant HAL, theses.fr le NNT d'une thèse soutenue. Un enregistrement source qui a un identifiant primaire, même retiré, reste tel quel. Chaque enregistrement source complété est mis en file pour la réconciliation.

Usage :
    uv run python -m interfaces.cli.oneshot.restore_primary_identifiers [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter

from sqlalchemy import Connection, text

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
    normalize_identifiers,
)
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.queues import Queue, enqueue
from infrastructure.observability.log import setup_logger

log = setup_logger("restore_primary_identifiers", os.path.dirname(__file__))

_PRIMARY_TYPES = {
    "crossref": SourceIdentifierType.DOI,
    "datacite": SourceIdentifierType.DOI,
    "hal": SourceIdentifierType.HAL_ID,
    "theses": SourceIdentifierType.NNT,
}

# Le `source_id` d'une thèse soutenue est son NNT : l'année, puis des lettres et des chiffres. Celui d'une thèse en cours est son identifiant theses.fr (`s123456`).
_NNT = re.compile(r"[0-9]{4}[0-9A-Z]+")

_WITHOUT_PRIMARY = text("""
    SELECT sr.id, sr.source::text AS source, sr.source_id
    FROM source_records sr
    WHERE sr.source::text = ANY(:sources)
      AND NOT EXISTS (
          SELECT 1 FROM source_record_identifiers i
          WHERE i.source_record_id = sr.id AND i.role = 'primary'
      )
    ORDER BY sr.id
""")

_INSERT = text("""
    INSERT INTO source_record_identifiers (source_record_id, id_type, id_value, role)
    SELECT i.source_record_id, CAST(i.id_type AS source_identifier_type), i.id_value, 'primary'
    FROM jsonb_to_recordset(CAST(:rows AS jsonb))
        AS i(source_record_id integer, id_type text, id_value text)
""")


def _primary(source: str, source_id: str) -> SourceIdentifier | None:
    """Renvoie l'identifiant primaire lu dans le `source_id`, ou `None` pour un `source_id` qui n'en est pas un."""
    if source == "theses" and not _NNT.fullmatch(source_id):
        return None
    identifiers, _ = normalize_identifiers(
        [SourceIdentifier(_PRIMARY_TYPES[source], source_id, SourceIdentifierRole.PRIMARY)]
    )
    return identifiers[0] if identifiers else None


def restore_primary_identifiers(conn: Connection, *, dry_run: bool = False) -> Counter[str]:
    """Écrit les identifiants primaires manquants et met leurs enregistrements sources en file. Renvoie les comptes par source et par issue."""
    rows = conn.execute(_WITHOUT_PRIMARY, {"sources": list(_PRIMARY_TYPES)}).all()
    counts: Counter[str] = Counter()
    restored: list[dict[str, object]] = []
    for r in rows:
        identifier = _primary(r.source, r.source_id)
        if identifier is None:
            counts[f"{r.source}, source_id sans identifiant primaire"] += 1
            continue
        counts[f"{r.source}, identifiant primaire écrit"] += 1
        restored.append(
            {
                "source_record_id": r.id,
                "id_type": identifier.id_type.value,
                "id_value": identifier.value,
            }
        )
    if restored and not dry_run:
        conn.execute(_INSERT, {"rows": json.dumps(restored)})
        enqueue(
            conn,
            Queue.SOURCE_RECORD_KEYS,
            "SELECT unnest(CAST(:ids AS integer[]))",
            {"ids": [row["source_record_id"] for row in restored]},
        )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte sans rien écrire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        log.info("Recherche des enregistrements sources sans identifiant primaire…")
        counts = restore_primary_identifiers(conn, dry_run=args.dry_run)
        for label, count in sorted(counts.items()):
            log.info("%s : %d", label, count)
        if args.dry_run:
            log.info("Dry-run, rien écrit.")
        else:
            conn.commit()


if __name__ == "__main__":
    main()
