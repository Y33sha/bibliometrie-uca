# STATUS: oneshot (2026-06-29)
"""Backfill : purge du stock les `nnt` qui ne sont pas des Numéros Nationaux de Thèse.

L'extraction OpenAlex capturait l'identifiant de `primary_location.id` même quand la location
pointait vers un dépôt HAL (et non theses.fr). Le `location.id` d'un dépôt moissonné en OAI-PMH a
la forme `pmh:oai:HAL:hal-04677016v1` (ou `pmh:doi:…`, `pmh:ark:/…`) : tout ce qui suit `pmh:`
était pris pour un NNT, mis en majuscules, et stocké en `external_ids.nnt`
(`OAI:HAL:HAL-04677016V1`, `DOI:10.5281/…`, `ARK:/…`). Sur la fiche publication, ces valeurs
alimentaient un lien `theses.fr/<valeur>` mort (404) avec l'icône theses.fr.

L'extraction est corrigée depuis (`extract_nnt_from_location` ne lit la location que si elle pointe
vers theses.fr, et `normalize_nnt` n'accepte qu'une valeur strictement alphanumérique ASCII). Ce
one-shot retire la clé `nnt` de chaque `source_publications` dont la valeur stockée est rejetée par
`normalize_nnt` — les vrais NNT (`2021CLFAC030`) et les identifiants theses.fr « en préparation »
(`s181801`) sont conservés.

Le NNT est une clé de réconciliation (regroupement des composantes par `external_ids->>'nnt'`) :
les SP modifiées sont marquées `keys_dirty` pour que la réconciliation les reprenne au prochain run.

Idempotent : une fois purgées, les valeurs malformées ne réapparaissent pas (l'extraction corrigée
ne les réécrit plus).

Usage :
    python -m interfaces.cli.oneshot.backfill_purge_malformed_nnt [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from domain.publications.identifiers import normalize_nnt
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_purge_malformed_nnt", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Compte les SP concernées, sans écrire."
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT id, source::text AS source, external_ids->>'nnt' AS nnt
                FROM source_publications
                WHERE external_ids ? 'nnt'
            """)
        ).all()

        bad_ids = [row.id for row in rows if normalize_nnt(row.nnt) is None]

        log.info(
            "%d source_publications avec nnt ; %d à purger (valeur non conforme à un NNT)",
            len(rows),
            len(bad_ids),
        )
        for row in rows:
            if normalize_nnt(row.nnt) is None:
                log.debug("  purge [%s] id=%s : %r", row.source, row.id, row.nnt)

        if args.dry_run:
            log.info("DRY-RUN : aucune écriture")
            return 0

        if bad_ids:
            conn.execute(
                text("""
                    UPDATE source_publications
                    SET external_ids = external_ids - 'nnt',
                        keys_dirty = true
                    WHERE id = ANY(:ids)
                """),
                {"ids": bad_ids},
            )
            conn.commit()
        log.info("✓ %d source_publications corrigées (marquées keys_dirty)", len(bad_ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
