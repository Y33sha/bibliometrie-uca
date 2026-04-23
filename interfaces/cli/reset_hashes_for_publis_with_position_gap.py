#!/usr/bin/env python3
"""One-shot : force la ré-extraction des ``source_publications`` dont la
numérotation d'``author_position`` a des trous.

Contexte
--------
Avant la migration 008 (clé d'unicité ``source_authorships`` étendue à
``author_position``), les upserts HAL/OpenAlex/ScanR/WoS/theses fusionnaient
toutes les occurrences d'un même couple (publi × source_person), même
quand la source listait l'auteur plusieurs fois (multi-affiliations,
homonymes sous la même forme-auteur, etc.). Résultat : au moment de la
migration, ~246 000 positions manquantes sur ~4 000 publis.

La migration rend ces rows insérables mais ne les recrée pas. Ce script
nulle le ``staging.raw_hash`` des publis concernées → la prochaine
extraction de leur source relance l'écrasement de ``raw_data`` +
``processed=FALSE`` (via le ``IS DISTINCT FROM`` dans l'ON CONFLICT des
extracteurs), et la normalisation suivante repeuple les positions
manquantes (avec pré-nettoyage par publi ajouté dans le même chantier).

Les publis hors périmètre d'extraction (auteurs externes ramenés par
cross-import, hors collections UCA, hors années) ne seront pas ramassées
par ``extract_<source>`` mais le seront par un futur cross-import si
citées ailleurs. Leurs trous restent en attendant.

Usage
-----
    python -m interfaces.cli.reset_hashes_for_publis_with_position_gap --dry-run
    python -m interfaces.cli.reset_hashes_for_publis_with_position_gap
    python -m interfaces.cli.reset_hashes_for_publis_with_position_gap --source hal
"""

from __future__ import annotations

import argparse
import logging
import os
from typing import Any

from domain.sources import ALL_SOURCES
from infrastructure.db.connection import get_connection
from infrastructure.log import setup_logger

log = setup_logger("reset_hashes_for_publis_with_position_gap", os.path.dirname(__file__))


def find_gap_staging_ids(cur: Any, source: str | None) -> dict[str, list[int]]:
    """Retourne ``{source: [staging_id, ...]}`` des publis avec trou dans
    la numérotation d'``author_position``.
    """
    source_filter = "AND spub.source = %s" if source else ""
    params: tuple[Any, ...] = (source,) if source else ()
    cur.execute(
        f"""
        SELECT spub.source, spub.staging_id
        FROM source_publications spub
        JOIN source_authorships sa ON sa.source_publication_id = spub.id
        WHERE sa.author_position IS NOT NULL
          AND spub.staging_id IS NOT NULL
          {source_filter}
        GROUP BY spub.source, spub.staging_id
        HAVING MAX(sa.author_position) + 1 > COUNT(*)
        """,
        params,
    )
    out: dict[str, list[int]] = {}
    for r in cur.fetchall():
        out.setdefault(r["source"], []).append(r["staging_id"])
    return out


def null_raw_hashes(cur: Any, staging_ids: list[int]) -> int:
    """Nulle ``raw_hash`` sur les rows staging : la prochaine extraction
    déclenchera le diff et réécrira ``raw_data`` + ``processed=FALSE``.
    """
    if not staging_ids:
        return 0
    cur.execute(
        "UPDATE staging SET raw_hash = NULL WHERE id = ANY(%s)",
        (staging_ids,),
    )
    return cur.rowcount


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Nulle raw_hash des staging rows derrière les publis avec trou de position"
    )
    parser.add_argument(
        "--source",
        choices=sorted(ALL_SOURCES),
        help="Cibler une seule source (défaut : toutes)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Compte sans modifier (rollback final)"
    )
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        by_source = find_gap_staging_ids(cur, args.source)

        total = sum(len(ids) for ids in by_source.values())
        log.info("Publis avec trou : %d", total)
        for src in sorted(by_source):
            log.info("  %-10s %d", src, len(by_source[src]))

        if args.dry_run:
            log.info("[DRY RUN] rollback, aucune modification.")
            conn.rollback()
            return

        nulled_total = 0
        for src, ids in by_source.items():
            n = null_raw_hashes(cur, ids)
            log.info("  %-10s raw_hash nullé sur %d staging rows", src, n)
            nulled_total += n

        conn.commit()
        log.info(
            "Terminé. %d hashes nullés. Prochaines étapes (manuel) :\n"
            "  - lancer `run_pipeline.py --mode full --only extract` (+ --sources si ciblage)\n"
            "  - puis `run_pipeline.py --mode full --only normalize`\n"
            "  - les publis hors périmètre d'extraction garderont leurs trous jusqu'au "
            "prochain cross-import qui les ré-amène.",
            nulled_total,
        )

    except Exception:
        conn.rollback()
        logging.getLogger().exception("Échec — rollback effectué")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
