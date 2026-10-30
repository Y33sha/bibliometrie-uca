# STATUS: oneshot (2026-09-21)
"""Instantané (lecture seule) des conteneurs de chaque enregistrement source : entrée de `serials` et monographie.

Sert à quantifier, par type de changement, l'effet d'une renormalisation du stock. L'entrée de `serials` retenue est celle donnée par la normalisation, avant correction par espace de noms DOI.

L'instantané s'écrit en JSON compressé sous `data/snapshots/`. `--compare` confronte deux instantanés : pour chaque enregistrement source présent dans les deux, le changement de son entrée de `serials` et celui de sa monographie, par source et type de document.

Usage :
    uv run python -m interfaces.cli.oneshot.snapshot_record_containers
    uv run python -m interfaces.cli.oneshot.snapshot_record_containers --compare AVANT.json.gz APRES.json.gz
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sql_fragments import has_active_issn

log = setup_logger("snapshot_record_containers", os.path.dirname(__file__))

_SNAPSHOTS = Path("data/snapshots")
_EXAMPLES = 5

_RECORDS = text(f"""
    SELECT sr.source::text AS source, sr.source_id, sr.doc_type,
           normalized.id AS serial_id, j.title AS journal_title,
           coalesce({has_active_issn("j.id")}, false) AS serial_has_issn,
           sr.monograph_id, m.title AS monograph_title
    FROM source_records sr
    CROSS JOIN LATERAL (
        SELECT CASE WHEN sr.corrections ? 'serial_id'
                    THEN (sr.corrections->'serial_id'->>'raw')::int
                    ELSE sr.serial_id END AS id
    ) normalized
    LEFT JOIN serials j ON j.id = normalized.id
    LEFT JOIN monographs m ON m.id = sr.monograph_id
""")

Record = list[object]
"""`[doc_type, serial_id, journal_title, serial_has_issn, monograph_id, monograph_title]`"""


def snapshot() -> dict[str, Record]:
    with get_sync_engine().connect() as conn:
        rows = conn.execute(_RECORDS).all()
    return {
        f"{r.source}:{r.source_id}": [
            r.doc_type,
            r.serial_id,
            r.journal_title,
            r.serial_has_issn,
            r.monograph_id,
            r.monograph_title,
        ]
        for r in rows
    }


def _serial_kind(record: Record) -> str:
    if record[1] is None:
        return "aucune"
    return "à ISSN" if record[3] else "sans ISSN"


def _serial_change(before: Record, after: Record) -> str:
    if before[1] == after[1]:
        return "revue inchangée"
    return f"revue {_serial_kind(before)} → {_serial_kind(after)}"


def _monograph_change(before: Record, after: Record) -> str:
    if before[4] == after[4]:
        return "monographie inchangée"
    if before[4] is None:
        return "monographie créée ou trouvée"
    if after[4] is None:
        return "monographie perdue"
    return "monographie changée"


def _describe(record: Record) -> str:
    return f"revue {record[1]} « {record[2]} », monographie {record[4]} « {record[5]} »"


def _compare(before: dict[str, Record], after: dict[str, Record]) -> None:
    common = before.keys() & after.keys()
    log.info(
        "Enregistrements : %d avant, %d après, %d communs",
        len(before),
        len(after),
        len(common),
    )
    tally: Counter[tuple[str, str]] = Counter()
    by_type: Counter[tuple[str, str, str]] = Counter()
    examples: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    for key in sorted(common):
        b, a = before[key], after[key]
        change = (_serial_change(b, a), _monograph_change(b, a))
        if change == ("revue inchangée", "monographie inchangée"):
            continue
        tally[change] += 1
        by_type[(*change, f"{key.split(':', 1)[0]} {a[0]}")] += 1
        if len(examples[change]) < _EXAMPLES:
            examples[change].append(f"{key} ({a[0]}) : {_describe(b)} → {_describe(a)}")

    log.info("─── Changements ───")
    for change, n in tally.most_common():
        log.info("%s, %s : %d", *change, n)
        for (serial, monograph, kind), m in by_type.most_common():
            if (serial, monograph) == change:
                log.info("    %-40s %6d", kind, m)
        for line in examples[change]:
            log.info("    · %s", line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare", nargs=2, metavar=("AVANT", "APRES"))
    args = parser.parse_args()
    if args.compare:
        before, after = (json.loads(gzip.decompress(Path(p).read_bytes())) for p in args.compare)
        _compare(before, after)
        return 0
    data = snapshot()
    _SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    path = _SNAPSHOTS / f"record_containers_{datetime.now(UTC):%Y%m%d_%H%M}.json.gz"
    path.write_bytes(gzip.compress(json.dumps(data, ensure_ascii=False).encode()))
    log.info("Instantané écrit : %s (%d enregistrements)", path, len(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
