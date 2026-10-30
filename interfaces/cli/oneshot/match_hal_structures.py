# STATUS: oneshot (2026-10-15)
"""Rattache à une structure interne (`ref.hal_structures.structure_id`) les structures HAL que la résolution des noms rattache à une structure du périmètre d'extraction.

Une structure HAL est candidate quand une contribution source la cite, que son statut est `VALID` ou `OLD`, qu'aucune structure interne n'a son ROR et qu'elle n'a pas déjà de structure interne. Deux voies proposent sa structure interne :

- adresse : une adresse de même texte que son nom est rattachée à une structure du périmètre, par un lien non infirmé, détecté par une forme de nom ou confirmé ;
- scanR : une affiliation scanR qui cite la structure HAL (`structId`) a un nom que les formes de noms rattachent à un seul laboratoire du périmètre, et à une autre structure du périmètre (université, organisme) qui en confirme le contexte. Les payloads se lisent dans le raw store.

Une structure HAL rattachée à plusieurs structures internes est signalée et laissée de côté. `--dry-run` écrit les candidates dans `data/measures/hal_structure_matches.csv` sans modifier la base.

Usage :
    uv run python -m interfaces.cli.oneshot.match_hal_structures [--dry-run] [--exclude ID ...]
"""

import argparse
import csv
import gzip
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import Connection, text

from domain.normalize import normalize_text
from domain.structures.structure import StructureType
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.transformation.structures.name_recognition import StructureNameMatcher

log = setup_logger("match_hal_structures", os.path.dirname(__file__))

_OUTPUT = Path("data/measures/hal_structure_matches.csv")
_SCANR_RAW_STORE = Path("data/raw_store/scanr")

_PERIMETER = """
    SELECT ps.structure_id
    FROM perimeter_structures ps
    JOIN perimeters p ON p.id = ps.perimeter_id
    WHERE p.code = (SELECT value #>> '{}' FROM config WHERE key = 'perimeter_extraction')
"""

# Structures HAL sans structure interne : ni ROR d'une structure interne, ni `structure_id`.
_UNMATCHED = """
    h.status IN ('VALID', 'OLD')
    AND NOT EXISTS (SELECT 1 FROM structures r WHERE r.ror_id = h.ror_id)
    AND h.structure_id IS NULL
"""

_CANDIDATES = text(f"""
    WITH cited AS (
        SELECT coalesce(al.hal_structure_id, sch.hal_structure_id) AS hal_structure_id, count(*) AS source_contributions
        FROM source_contribution_hal_structures sch
        LEFT JOIN hal_structure_aliases al ON al.alias_id = sch.hal_structure_id
        GROUP BY 1
    ),
    perimeter AS ({_PERIMETER})
    SELECT DISTINCT h.hal_structure_id, h.name AS hal_name, h.status::text AS status, c.source_contributions,
           s.id AS structure_id, s.code, 'adresse' AS voie
    FROM hal_structures h
    JOIN cited c ON c.hal_structure_id = h.hal_structure_id
    JOIN addresses a ON a.raw_text = h.name
    JOIN address_structures ast ON ast.address_id = a.id
    JOIN structures s ON s.id = ast.structure_id
    WHERE {_UNMATCHED}
      AND ast.is_confirmed IS DISTINCT FROM false
      AND (ast.matched_form_id IS NOT NULL OR ast.is_confirmed)
      AND s.id IN (SELECT structure_id FROM perimeter)
    ORDER BY s.code, c.source_contributions DESC
""")


def _scanr_candidates(conn: Connection) -> list[dict]:
    """Candidates de la voie scanR : structure HAL citée par une affiliation scanR dont le nom désigne un seul laboratoire du périmètre, et une autre structure du périmètre."""
    matcher = StructureNameMatcher.load(conn)
    labs = dict(
        conn.execute(
            text(f"""
                SELECT s.id, s.code FROM structures s
                WHERE s.structure_type = :labo AND s.id IN ({_PERIMETER})
            """),
            {"labo": StructureType.LABO.value},
        ).all()
    )
    perimeter = set(conn.execute(text(_PERIMETER)).scalars())
    eligible = {
        r.hal_structure_id: r
        for r in conn.execute(
            text(
                f"SELECT h.hal_structure_id, h.name, h.status::text AS status FROM hal_structures h WHERE {_UNMATCHED}"
            )
        )
    }
    aliases = dict(
        conn.execute(text("SELECT alias_id, hal_structure_id FROM hal_structure_aliases")).all()
    )
    mentions: Counter[tuple[int, int]] = Counter()
    for path in _SCANR_RAW_STORE.glob("*.json.gz"):
        with gzip.open(path) as f:
            doc = json.load(f)
        for author in doc.get("authors") or []:
            for aff in author.get("affiliations") or []:
                struct_id, name = str(aff.get("structId") or ""), aff.get("name")
                if not (struct_id.isdigit() and name):
                    continue
                hal_structure_id = aliases.get(int(struct_id), int(struct_id))
                if hal_structure_id not in eligible:
                    continue
                matched = {m.structure_id for m in matcher.resolve(normalize_text(name))}
                found = matched & labs.keys()
                if len(found) == 1 and (matched - found) & perimeter:
                    mentions[(hal_structure_id, found.pop())] += 1
    return [
        {
            "hal_structure_id": hal_structure_id,
            "hal_name": eligible[hal_structure_id].name,
            "status": eligible[hal_structure_id].status,
            "source_contributions": n,
            "structure_id": structure_id,
            "code": labs[structure_id],
            "voie": "scanR",
        }
        for (hal_structure_id, structure_id), n in mentions.items()
    ]


_SET = text(
    "UPDATE hal_structures SET structure_id = :structure_id WHERE hal_structure_id = ANY(:ids)"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Structure interne des structures HAL")
    parser.add_argument(
        "--dry-run", action="store_true", help="Écrit les candidates sans modifier la base"
    )
    parser.add_argument(
        "--exclude", type=int, nargs="*", default=[], help="Structures HAL écartées après relecture"
    )
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        rows = [dict(r) for r in conn.execute(_CANDIDATES).mappings()] + _scanr_candidates(conn)
        by_hal: dict[int, dict[int, dict]] = defaultdict(dict)
        for row in rows:
            by_hal[row["hal_structure_id"]].setdefault(row["structure_id"], row)
        kept = [
            next(iter(rs.values()))
            for hal_structure_id, rs in by_hal.items()
            if len(rs) == 1 and hal_structure_id not in args.exclude
        ]
        for found in by_hal.values():
            rs = list(found.values())
            if len(rs) > 1:
                log.warning(
                    "structure HAL %d « %s » rattachée à plusieurs structures : %s",
                    rs[0]["hal_structure_id"],
                    rs[0]["hal_name"],
                    ", ".join(r["code"] for r in rs),
                )
        by_structure: dict[int, list[dict]] = defaultdict(list)
        for row in kept:
            by_structure[row["structure_id"]].append(row)
        for rs in by_structure.values():
            log.info(
                "%s : %d structures HAL, %d contributions sources",
                rs[0]["code"],
                len(rs),
                sum(r["source_contributions"] for r in rs),
            )
        log.info("%d structures HAL pour %d structures internes", len(kept), len(by_structure))
        if args.dry_run:
            _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            with _OUTPUT.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f, fieldnames=list(kept[0]) if kept else ["hal_structure_id"]
                )
                writer.writeheader()
                writer.writerows(kept)
            log.info("Candidates écrites dans %s (dry-run)", _OUTPUT)
            return
        for structure_id, rs in by_structure.items():
            conn.execute(
                _SET, {"structure_id": structure_id, "ids": [r["hal_structure_id"] for r in rs]}
            )
        log.info("structure_id posé pour %d structures HAL", len(kept))


if __name__ == "__main__":
    main()
