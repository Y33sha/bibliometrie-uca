#!/usr/bin/env python3
"""One-shot : re-merge les publications dont la ``pub_year`` suit OpenAlex
alors qu'une source HAL plus prioritaire donne une année différente.

Contexte
--------
HAL renseigne ``pub_year`` = **année de publication de l'article** (date
réelle du support, éventuellement ancienne). OpenAlex, quand HAL est la
source du record, renseigne souvent ``pub_year`` = **année de dépôt
dans HAL** — d'où des écarts parfois considérables (jusqu'à +18 ans
observés). ``SOURCE_PRIORITY`` place HAL avant OpenAlex ; dans la plupart
des cas ``refresh_from_sources`` applique bien HAL, mais ~960 publis
sont restées alignées sur OpenAlex (refresh non rejoué après un merge
ou un re-rattachement HAL tardif).

Le script :

1. Trouve les ``publications`` où une ``source_publications`` HAL et une
   OpenAlex existent avec des ``pub_year`` différents, et dont la
   ``pub_year`` canonique est alignée sur OpenAlex (= non-HAL).
2. Ré-appelle ``refresh_from_sources(pub_id)`` sur chacune. Cette
   fonction applique ``SOURCE_PRIORITY`` sur tous les champs agrégés
   (pas seulement ``pub_year`` — c'est la philosophie DDD : on ne
   court-circuite pas la règle métier en touchant un seul champ).

Usage
-----
    python -m interfaces.cli.refresh_publications_year_mismatch --dry-run
    python -m interfaces.cli.refresh_publications_year_mismatch
"""

from __future__ import annotations

import argparse
import logging
import os
from typing import Any

from application.publications import refresh_from_sources
from infrastructure.db.connection import get_connection
from infrastructure.log import setup_logger
from infrastructure.repositories import publication_repository

log = setup_logger("refresh_publications_year_mismatch", os.path.dirname(__file__))


def find_candidates(cur: Any) -> list[dict[str, Any]]:
    """Publications où ``pub_year`` canonique suit OpenAlex alors que HAL
    a une année différente (et donc prioritaire).

    Critère : il existe au moins une paire HAL/OA rattachée à la publi
    avec des ``pub_year`` différents non-NULL, et la ``pub_year`` canonique
    n'est alignée sur aucune ``source_publications`` HAL de la publi.
    """
    cur.execute("""
        WITH per_pub AS (
            SELECT p.id AS pub_id,
                   p.pub_year AS canon,
                   array_agg(DISTINCT sp.pub_year) FILTER
                       (WHERE sp.source = 'hal' AND sp.pub_year IS NOT NULL) AS hal_years,
                   array_agg(DISTINCT sp.pub_year) FILTER
                       (WHERE sp.source = 'openalex' AND sp.pub_year IS NOT NULL) AS oa_years
            FROM publications p
            JOIN source_publications sp ON sp.publication_id = p.id
            GROUP BY p.id, p.pub_year
        )
        SELECT pub_id, canon, hal_years, oa_years
        FROM per_pub
        WHERE hal_years IS NOT NULL
          AND oa_years  IS NOT NULL
          AND NOT (hal_years && oa_years)      -- HAL et OA divergent
          AND (canon IS NULL OR NOT (canon = ANY(hal_years)))
        ORDER BY pub_id
    """)
    return list(cur.fetchall())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-merge les publications avec pub_year alignée sur OA alors que HAL diverge"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Compte sans appliquer (rollback final)"
    )
    parser.add_argument("--limit", type=int, help="Nombre max de publications à traiter (debug)")
    args = parser.parse_args()

    conn = get_connection()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        candidates = find_candidates(cur)
        log.info("Publications candidates : %d", len(candidates))

        if args.limit:
            candidates = candidates[: args.limit]
            log.info("Limité à %d candidates (--limit)", len(candidates))

        if args.dry_run:
            log.info("[DRY RUN] 10 premiers cas :")
            for c in candidates[:10]:
                log.info(
                    "  pub_id=%d canon=%s hal=%s oa=%s",
                    c["pub_id"],
                    c["canon"],
                    c["hal_years"],
                    c["oa_years"],
                )
            conn.rollback()
            return

        repo = publication_repository(cur)
        changed = 0
        for i, c in enumerate(candidates, start=1):
            before = c["canon"]
            refresh_from_sources(cur, c["pub_id"], repo=repo)
            cur.execute("SELECT pub_year FROM publications WHERE id = %s", (c["pub_id"],))
            after = cur.fetchone()["pub_year"]
            if after != before:
                changed += 1
            if i % 200 == 0:
                log.info("  %d/%d traitées (%d pub_year modifiées)", i, len(candidates), changed)

        conn.commit()
        log.info(
            "Terminé : %d publications re-mergées, dont %d avec pub_year modifiée.",
            len(candidates),
            changed,
        )

    except Exception:
        conn.rollback()
        logging.getLogger().exception("Échec — rollback effectué")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
