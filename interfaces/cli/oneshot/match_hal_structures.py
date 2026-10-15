# STATUS: oneshot (2026-10-15)
"""Rattache à une structure interne (`ref.hal_structures.structure_id`) les structures HAL que la résolution des adresses rattache par leur nom à une structure du périmètre d'extraction.

Une structure HAL est candidate quand :

- une signature la cite ;
- son statut est `VALID` ou `OLD` ;
- aucune structure interne n'a son ROR, et elle n'a pas déjà de structure interne ;
- une adresse de même texte que son nom est rattachée à une seule structure du périmètre, par un lien non infirmé, détecté par une forme de nom ou confirmé.

Une structure HAL rattachée à plusieurs structures internes est signalée et laissée de côté. `--dry-run` écrit les candidates dans `data/measures/hal_structure_matches.csv` sans modifier la base.

Usage :
    python -m interfaces.cli.oneshot.match_hal_structures [--dry-run]
"""

import argparse
import csv
import os
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("match_hal_structures", os.path.dirname(__file__))

_OUTPUT = Path("data/measures/hal_structure_matches.csv")

_CANDIDATES = text("""
    WITH cited AS (
        SELECT coalesce(al.hal_structure_id, sah.hal_structure_id) AS hal_structure_id, count(*) AS signatures
        FROM source_authorship_hal_structures sah
        LEFT JOIN hal_structure_aliases al ON al.alias_id = sah.hal_structure_id
        GROUP BY 1
    ),
    perimeter AS (
        SELECT ps.structure_id
        FROM perimeter_structures ps
        JOIN perimeters p ON p.id = ps.perimeter_id
        WHERE p.code = (SELECT value #>> '{}' FROM config WHERE key = 'perimeter_extraction')
    )
    SELECT DISTINCT h.hal_structure_id, h.name AS hal_name, h.status::text AS status, c.signatures,
           s.id AS structure_id, s.code
    FROM hal_structures h
    JOIN cited c ON c.hal_structure_id = h.hal_structure_id
    JOIN addresses a ON a.raw_text = h.name
    JOIN address_structures ast ON ast.address_id = a.id
    JOIN structures s ON s.id = ast.structure_id
    WHERE h.status IN ('VALID', 'OLD')
      AND NOT EXISTS (SELECT 1 FROM structures r WHERE r.ror_id = h.ror_id)
      AND h.structure_id IS NULL
      AND ast.is_confirmed IS DISTINCT FROM false
      AND (ast.matched_form_id IS NOT NULL OR ast.is_confirmed)
      AND s.id IN (SELECT structure_id FROM perimeter)
    ORDER BY s.code, c.signatures DESC
""")

_SET = text(
    "UPDATE hal_structures SET structure_id = :structure_id WHERE hal_structure_id = ANY(:ids)"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Structure interne des structures HAL")
    parser.add_argument(
        "--dry-run", action="store_true", help="Écrit les candidates sans modifier la base"
    )
    args = parser.parse_args()
    with get_sync_engine().begin() as conn:
        rows = conn.execute(_CANDIDATES).mappings().all()
        by_hal: dict[int, list[dict]] = defaultdict(list)
        for row in rows:
            by_hal[row["hal_structure_id"]].append(dict(row))
        kept = [rs[0] for rs in by_hal.values() if len(rs) == 1]
        for rs in by_hal.values():
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
                "%s : %d structures HAL, %d signatures",
                rs[0]["code"],
                len(rs),
                sum(r["signatures"] for r in rs),
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
