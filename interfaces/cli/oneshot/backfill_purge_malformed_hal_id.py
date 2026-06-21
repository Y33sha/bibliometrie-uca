# STATUS: oneshot (2026-06-21)
"""Backfill : purge du stock les `hal_id` dont le numéro n'a pas 8 chiffres.

L'extraction de hal_id (corrigée depuis) capturait n'importe quel fragment `mot-chiffres`
d'une URL non-HAL : un suffixe de DOI DataCite (`10.3204/pubdb-2020-…`, `10.18154/rwth-2020-…`)
ou un PURL étranger (`gro-2`) devenait un faux hal_id, partageant à tort une clé de confirmation
entre publications. Le docid CCSD a un format uniforme : exactement 8 chiffres (100 % des hal_id
observés sur des hôtes HAL). Ce one-shot retire de chaque tableau `external_ids.hal_id` toute
valeur dont la partie numérique diffère de 8 chiffres — `gro-2` (1), `pubdb-2020` (4),
`jyu-201808163850` (12) — sans re-fetcher les sources. Les vrais `hal-04600667`, `in2p3-01480071`,
`sic_01848963` (8 chiffres, séparateur indifférent) sont conservés.

Les SP modifiées sont marquées `keys_dirty` : le hal_id étant une clé de confirmation, la
réconciliation des composantes les reprend au prochain run.

Idempotent : une fois purgées, les valeurs malformées ne réapparaissent pas.

Usage :
    python -m interfaces.cli.oneshot.backfill_purge_malformed_hal_id [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_purge_malformed_hal_id", os.path.dirname(__file__))

# Partie numérique en fin de hal_id, suffixe de version `v\d+` éventuel ignoré. Ancrée à la fin
# pour ne pas confondre avec des chiffres présents dans le code de collection (`in2p3-…`).
_TRAILING_NUMBER = re.compile(r"(\d+)(?:v\d+)?$")


def _kept_hal_ids(values: list[str]) -> list[str]:
    """Conserve les valeurs dont le numéro fait exactement 8 chiffres, en dédoublonnant."""
    out: list[str] = []
    for value in values:
        match = _TRAILING_NUMBER.search(value)
        if match and len(match.group(1)) == 8 and value not in out:
            out.append(value)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Compte les SP et valeurs concernées, sans écrire."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id, external_ids->'hal_id' AS hal_id
                FROM source_publications
                WHERE jsonb_typeof(external_ids->'hal_id') = 'array'
            """)
        ).all()

        updates: list[dict] = []
        removed_count = 0
        for row in rows:
            current = list(row.hal_id)
            kept = _kept_hal_ids(current)
            if kept != current:
                removed_count += len(current) - len(kept)
                updates.append({"id": row.id, "kept": json.dumps(kept)})

        log.info(
            "%d source_publications avec hal_id ; %d à corriger (%d valeurs malformées retirées)",
            len(rows),
            len(updates),
            removed_count,
        )

        if args.dry_run:
            log.info("DRY-RUN : aucune écriture")
            return 0

        if updates:
            conn.execute(
                text("""
                    UPDATE source_publications
                    SET external_ids = CASE
                            WHEN :kept = '[]' THEN external_ids - 'hal_id'
                            ELSE jsonb_set(external_ids, '{hal_id}', CAST(:kept AS jsonb))
                        END,
                        keys_dirty = true
                    WHERE id = :id
                """),
                updates,
            )
            conn.commit()
        log.info("✓ %d source_publications corrigées (marquées keys_dirty)", len(updates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
