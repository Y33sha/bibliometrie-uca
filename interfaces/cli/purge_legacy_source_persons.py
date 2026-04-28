"""Purge des `source_persons` synthétiques rendues inutiles par le chantier
source_persons (cf. `docs/chantiers/source-persons.md`).

Catégories purgées :
- OpenAlex / WoS / CrossRef : intégralité (entités algorithmiques non
  fiables, désormais sans nouvelle écriture côté normalizers).
- HAL `0_<form_id>` (form_id seul, sans hal_person_id) et `nokey-*` :
  cas synthétiques, plus créés. On garde les HAL avec `hal_person_id`
  (= comptes HAL identifiés, cas légitime).
- ScanR `scanr-<seq>` : cas synthétiques. On garde les ScanR avec idref.
- theses `nokey-*` : cas synthétiques. On garde les theses avec PPN.

Prérequis : migration 013 (FK source_person_id passée à ON DELETE
SET NULL) — sans elle, le DELETE source_persons cascadait sur les
source_authorships, ce qu'on ne veut pas.

La FK ON DELETE SET NULL fait automatiquement passer
`source_authorships.source_person_id` à NULL pour les rows qui
référençaient un source_persons supprimé. Les source_authorships
elles-mêmes restent intactes (les identifiants ORCID/idref/idhal
ont déjà été migrés sur `source_authorships.identifiers` lors du
backfill phase 1).

Traitement par batches via cursor sur sa.id, logs de progression.
Idempotent : re-lancer reprend à zéro mais ne trouvera rien.

Usage:
    python -m interfaces.cli.purge_legacy_source_persons --dry-run
    python -m interfaces.cli.purge_legacy_source_persons
    python -m interfaces.cli.purge_legacy_source_persons --batch-size 5000
"""

from __future__ import annotations

import argparse
import os
import time
from typing import Any

from infrastructure.db.connection import get_connection
from infrastructure.log import setup_logger

logger = setup_logger("purge_legacy_source_persons", os.path.dirname(__file__))


# Catégories de purge : (label, WHERE clause)
_CATEGORIES: list[tuple[str, str]] = [
    ("OpenAlex (toutes)", "source = 'openalex'"),
    ("WoS (toutes)", "source = 'wos'"),
    ("CrossRef (toutes)", "source = 'crossref'"),
    (
        "HAL synthétiques (0_<form_id> + nokey-*)",
        "source = 'hal' AND (source_id LIKE '0\\_%' ESCAPE '\\' OR source_id LIKE 'nokey-%')",
    ),
    ("ScanR synthétiques (scanr-*)", "source = 'scanr' AND source_id LIKE 'scanr-%'"),
    ("theses synthétiques (nokey-*)", "source = 'theses' AND source_id LIKE 'nokey-%'"),
]


def count_category(cur: Any, where: str) -> int:
    cur.execute(f"SELECT COUNT(*) AS n FROM source_persons WHERE {where}")
    return cur.fetchone()["n"]


def purge_category(
    cur: Any, where: str, batch_size: int, *, dry_run: bool, label: str
) -> int:
    """DELETE en batches. Retourne le nombre total de rows supprimées."""
    total_deleted = 0
    t0 = time.time()
    initial_count = count_category(cur, where)
    if initial_count == 0:
        logger.info(f"  {label} : 0 row, skip")
        return 0

    logger.info(f"  {label} : {initial_count} rows à purger")

    if dry_run:
        return 0

    while True:
        # Sélectionne un batch d'IDs à supprimer (DELETE direct par batch)
        cur.execute(
            f"""
            DELETE FROM source_persons
            WHERE id IN (
                SELECT id FROM source_persons WHERE {where} LIMIT %s
            )
            """,
            (batch_size,),
        )
        n = cur.rowcount
        if n == 0:
            break
        total_deleted += n
        cur.connection.commit()

        elapsed = time.time() - t0
        rate = total_deleted / elapsed if elapsed > 0 else 0
        pct = 100 * total_deleted / initial_count if initial_count else 100
        logger.info(
            f"    {total_deleted}/{initial_count} ({pct:.1f}%), "
            f"{rate:.0f} rows/s"
        )

    return total_deleted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Nombre de rows supprimées par batch (défaut : 5000)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compte sans DELETE")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    if args.dry_run:
        logger.info("Mode --dry-run : aucun DELETE")

    # Inventaire global avant
    cur.execute("SELECT COUNT(*) AS n FROM source_persons")
    total_before = cur.fetchone()["n"]
    logger.info(f"Total source_persons avant purge : {total_before}")
    logger.info("")

    # Pré-vérification FK
    cur.execute("""
        SELECT pg_get_constraintdef(con.oid) AS def
        FROM pg_constraint con
        WHERE con.conname = 'source_authorships_source_person_id_fkey'
    """)
    fk_row = cur.fetchone()
    if fk_row and "SET NULL" not in fk_row["def"]:
        logger.error(
            "FK source_authorships.source_person_id n'est pas en ON DELETE SET NULL "
            "→ purge dangereuse (cascade des source_authorships). "
            "Appliquer d'abord la migration 013."
        )
        raise SystemExit(1)

    grand_total = 0
    for label, where in _CATEGORIES:
        n = purge_category(cur, where, args.batch_size, dry_run=args.dry_run, label=label)
        grand_total += n

    if not args.dry_run:
        conn.commit()
        cur.execute("SELECT COUNT(*) AS n FROM source_persons")
        total_after = cur.fetchone()["n"]
        logger.info("")
        logger.info(f"Total purgé : {grand_total}")
        logger.info(f"source_persons avant : {total_before} → après : {total_after}")
    else:
        logger.info("")
        logger.info("[DRY RUN] aucune modification")

    conn.close()


if __name__ == "__main__":
    main()
