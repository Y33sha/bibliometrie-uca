# STATUS: oneshot (2026-09-21)
"""Instantané (lecture seule) des articles de congrès : séries, volumes, articles par volume.

Sert à comparer l'état avant et après le passage des volumes d'actes de `journals` à `monographs`. Les mesures valent pour les deux états :

- une **série** est une entrée de `journals` à ISSN, ou une entrée sans ISSN désignée par au moins deux monographies ;
- le **volume** d'une publication est sa monographie, à défaut son entrée de `journals` quand elle n'est pas une série ;
- la série d'une publication est son entrée de `journals` quand c'est une série, à défaut celle de sa monographie.

L'instantané s'écrit en JSON sous `data/snapshots/`. `--compare` confronte deux instantanés.

Usage :
    python -m interfaces.cli.oneshot.snapshot_conference_papers
    python -m interfaces.cli.oneshot.snapshot_conference_papers --compare AVANT.json APRES.json
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.db.sql_fragments import has_active_issn
from infrastructure.observability.log import setup_logger

log = setup_logger("snapshot_conference_papers", os.path.dirname(__file__))

_SNAPSHOTS = Path("data/snapshots")

_PAPERS = text(f"""
    WITH series AS (
        SELECT j.id, {has_active_issn("j.id")} AS has_issn
        FROM journals j
        WHERE {has_active_issn("j.id")}
           OR (SELECT count(*) FROM monographs m WHERE m.journal_id = j.id) >= 2
    )
    SELECT p.id,
           coalesce(ps.id, ms.id) AS series_id,
           coalesce(ps.has_issn, ms.has_issn) AS series_has_issn,
           CASE
               WHEN p.monograph_id IS NOT NULL THEN 'm' || p.monograph_id
               WHEN p.journal_id IS NOT NULL AND ps.id IS NULL THEN 'j' || p.journal_id
           END AS volume
    FROM publications p
    LEFT JOIN series ps ON ps.id = p.journal_id
    LEFT JOIN monographs m ON m.id = p.monograph_id
    LEFT JOIN series ms ON ms.id = m.journal_id
    WHERE p.doc_type = 'conference_paper'
""")

_BUCKETS = ((1, "1"), (5, "2-5"), (20, "6-20"), (100, "21-100"), (None, "> 100"))


def _bucket(n: int) -> str:
    return next(label for bound, label in _BUCKETS if bound is None or n <= bound)


def snapshot() -> dict[str, object]:
    with get_sync_engine().connect() as conn:
        rows = conn.execute(_PAPERS).all()
    per_volume = Counter(r.volume for r in rows if r.volume)
    series = {r.series_id: r.series_has_issn for r in rows if r.series_id}
    return {
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "articles_de_congres": len(rows),
        "series": len(series),
        "series_a_issn": sum(1 for has in series.values() if has),
        "series_sans_issn": sum(1 for has in series.values() if not has),
        "volumes": len(per_volume),
        "volumes_en_monographie": sum(1 for v in per_volume if v.startswith("m")),
        "volumes_dans_journals": sum(1 for v in per_volume if v.startswith("j")),
        "articles_par_volume": dict(Counter(_bucket(n) for n in per_volume.values())),
        "articles_sans_serie": sum(1 for r in rows if not r.series_id),
        "articles_sans_volume": sum(1 for r in rows if not r.volume),
        "articles_sans_serie_ni_volume": sum(1 for r in rows if not r.series_id and not r.volume),
    }


def _compare(before: dict[str, object], after: dict[str, object]) -> None:
    for key in before:
        if key == "date":
            continue
        log.info("%-32s %12s → %s", key, before[key], after.get(key))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare", nargs=2, metavar=("AVANT", "APRES"))
    args = parser.parse_args()
    if args.compare:
        before, after = (json.loads(Path(p).read_text()) for p in args.compare)
        _compare(before, after)
        return 0
    data = snapshot()
    _SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    path = _SNAPSHOTS / f"conference_papers_{datetime.now(UTC):%Y%m%d_%H%M}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    for key, value in data.items():
        log.info("%-32s %s", key, value)
    log.info("Instantané écrit : %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
