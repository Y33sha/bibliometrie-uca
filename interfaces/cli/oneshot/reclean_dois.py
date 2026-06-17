# STATUS: oneshot (2026-06-17)
"""Ré-applique `clean_doi` aux `source_publications` dont la colonne `doi` n'est pas canonique.

`clean_doi` évolue (strip du slash final parasite, des suffixes `.vN` / `/pdf`) ; les DOI écrits
sous une version antérieure du cleaner ne reflètent plus la forme canonique. On les re-nettoie en
place et on pose `keys_dirty`, pour que la réconciliation fusionne au prochain run de la phase
`publications` les doublons que la forme canonique révèle (ex. `10.x/abc/` et `10.x/abc`).

Le brut d'origine reste dans `data/raw_store` ; la colonne `doi` est la valeur canonique, donc la
ré-écrire = re-normaliser, pas corriger. Skip si `clean_doi` renvoie `None` (on ne nulle pas un DOI).

Usage :
    python -m interfaces.cli.oneshot.reclean_dois [--dry-run]
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from domain.publications.identifiers import clean_doi
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("reclean_dois", os.path.dirname(__file__))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte les DOI à re-nettoyer.")
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, doi FROM source_publications WHERE doi IS NOT NULL")
        ).all()
        updates = [
            (r.id, cleaned) for r in rows if (cleaned := clean_doi(r.doi)) and cleaned != r.doi
        ]
        log.info("%d source_publications à re-nettoyer", len(updates))

        if args.dry_run:
            for sid, new in updates[:20]:
                log.info("  %d → %s", sid, new)
            return 0

        for sid, new in updates:
            conn.execute(
                text("UPDATE source_publications SET doi = :doi, keys_dirty = true WHERE id = :id"),
                {"doi": new, "id": sid},
            )
        conn.commit()
        log.info(
            "✓ %d DOI re-nettoyés (keys_dirty posé → fusion au prochain run publications)",
            len(updates),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
