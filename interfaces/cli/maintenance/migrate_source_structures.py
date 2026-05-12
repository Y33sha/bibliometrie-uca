# STATUS: oneshot (2026-05-12)
"""
Phase 2 du chantier DATA_simplify-source-tables.

Peuple les deux nouvelles colonnes de `source_authorships` à partir
de l'ancienne forme (`source_struct_ids` → jointure sur
`source_structures.id`) :

- `source_structures TEXT[]` (toutes sources) : array des
  `source_structures.source_id` (HAL : numérique, OpenAlex : "I****",
  etc.), trié par source_id pour stabilité.
- `countries TEXT[]` (HAL uniquement) : array des
  `source_structures.country` distincts, trié. Pour OA/WoS/ScanR, le
  pays est porté côté `addresses.countries` — rien à migrer ici
  (`source_structures.country` y était écrit mais jamais lu, cf.
  fiche du chantier).

Idempotent : skip les `source_authorships` dont la colonne cible est
déjà non-NULL.

Usage :
    python -m interfaces.cli.maintenance.migrate_source_structures           # dry-run
    python -m interfaces.cli.maintenance.migrate_source_structures --apply
"""

import argparse
import os
import sys

from sqlalchemy import Connection, text

from infrastructure.db.engine import get_sync_engine
from infrastructure.log import setup_logger

log = setup_logger("migrate_source_structures", os.path.dirname(__file__))


_COUNT_STRUCTURES_TO_FILL = text("""
    SELECT COUNT(DISTINCT sa.id)
    FROM source_authorships sa
    WHERE sa.source_structures IS NULL
      AND sa.source_struct_ids IS NOT NULL
      AND array_length(sa.source_struct_ids, 1) > 0
""")

_COUNT_COUNTRIES_TO_FILL = text("""
    SELECT COUNT(DISTINCT sa.id)
    FROM source_authorships sa
    JOIN unnest(sa.source_struct_ids) AS sid ON true
    JOIN source_structures ss ON ss.id = sid
    WHERE sa.source = 'hal'
      AND sa.countries IS NULL
      AND sa.source_struct_ids IS NOT NULL
      AND ss.country IS NOT NULL
""")

_UPDATE_STRUCTURES = text("""
    WITH src AS (
        SELECT sa.id AS sa_id,
               array_agg(ss.source_id ORDER BY ss.source_id) AS struct_source_ids
        FROM source_authorships sa
        JOIN unnest(sa.source_struct_ids) AS sid ON true
        JOIN source_structures ss ON ss.id = sid
        WHERE sa.source_structures IS NULL
          AND sa.source_struct_ids IS NOT NULL
        GROUP BY sa.id
    )
    UPDATE source_authorships sa
    SET source_structures = src.struct_source_ids
    FROM src
    WHERE sa.id = src.sa_id
""")

_UPDATE_COUNTRIES_HAL = text("""
    WITH src AS (
        SELECT sa.id AS sa_id,
               array_agg(DISTINCT ss.country ORDER BY ss.country) AS country_codes
        FROM source_authorships sa
        JOIN unnest(sa.source_struct_ids) AS sid ON true
        JOIN source_structures ss ON ss.id = sid
        WHERE sa.source = 'hal'
          AND sa.countries IS NULL
          AND sa.source_struct_ids IS NOT NULL
          AND ss.country IS NOT NULL
        GROUP BY sa.id
    )
    UPDATE source_authorships sa
    SET countries = src.country_codes
    FROM src
    WHERE sa.id = src.sa_id
""")


def _report(conn: Connection) -> tuple[int, int]:
    """Retourne (nb_sa_à_remplir_structures, nb_sa_à_remplir_countries_hal)."""
    structures = conn.execute(_COUNT_STRUCTURES_TO_FILL).scalar_one()
    countries = conn.execute(_COUNT_COUNTRIES_TO_FILL).scalar_one()
    return structures, countries


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Peuple source_authorships.source_structures (toutes sources) "
        "et source_authorships.countries (HAL) depuis source_structures."
    )
    parser.add_argument("--apply", action="store_true", help="Appliquer (sinon dry-run).")
    args = parser.parse_args()

    conn = get_sync_engine().connect()
    try:
        nb_structs, nb_countries = _report(conn)
        log.info(
            "À remplir : %d source_authorships (source_structures), "
            "%d source_authorships HAL (countries)",
            nb_structs,
            nb_countries,
        )

        if not args.apply:
            log.info("[dry-run] ajouter --apply pour exécuter les UPDATE")
            return 0

        r1 = conn.execute(_UPDATE_STRUCTURES)
        log.info("source_structures peuplée sur %d rows", r1.rowcount)
        r2 = conn.execute(_UPDATE_COUNTRIES_HAL)
        log.info("countries (HAL) peuplée sur %d rows", r2.rowcount)
        conn.commit()
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
