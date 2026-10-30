# STATUS: oneshot (2026-10-10)
"""Marque `authors_truncated` les enregistrements OpenAlex rapatriés par `fetch_missing` avec exactement 100 auteurs.

La recherche par DOI de `fetch_missing` interroge la route de liste d'OpenAlex, qui plafonne les auteurs à 100, sans le marqueur posé par le moissonnage. Ces enregistrements sont restés tronqués. Une fois marqués, ils sont retéléchargés en entier par la phase `fetch_truncated` de l'exécution suivante, et `normalize` réécrit leurs contributions sources.

Le nombre d'auteurs se lit dans `raw_data` pour un enregistrement pas encore normalisé, et dans ses contributions sources sinon.

Usage :
    uv run python -m interfaces.cli.oneshot.backfill_mark_truncated_fetch_missing_openalex             # applique
    uv run python -m interfaces.cli.oneshot.backfill_mark_truncated_fetch_missing_openalex --dry-run   # rapport seul
"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.ingestion.openalex.payload import BULK_AUTHORSHIPS_CAP

log = setup_logger("backfill_mark_truncated_fetch_missing_openalex", os.path.dirname(__file__))

_A_MARQUER = """
    FROM staging s
    WHERE s.source = 'openalex'
      AND s.entry_mode = 'fetch_missing_doi'
      AND NOT s.authors_truncated
      AND (
          jsonb_typeof(s.raw_data -> 'authorships') = 'array'
              AND jsonb_array_length(s.raw_data -> 'authorships') = :cap
          OR (
              SELECT count(*)
              FROM source_records sr
              JOIN source_contributions sc ON sc.source_record_id = sr.id
              WHERE sr.staging_id = s.id
          ) = :cap
      )
"""

_COUNT = text(f"SELECT count(*) {_A_MARQUER}")
_MARK = text(f"UPDATE staging SET authors_truncated = TRUE WHERE id IN (SELECT s.id {_A_MARQUER})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()

    params = {"cap": BULK_AUTHORSHIPS_CAP}
    with get_sync_engine().connect() as conn:
        if args.dry_run:
            log.info("Enregistrements à marquer : %d", conn.execute(_COUNT, params).scalar_one())
            log.info("DRY-RUN terminé — aucune écriture")
            return 0
        n = conn.execute(_MARK, params).rowcount
        conn.commit()
        log.info("✓ %d enregistrements marqués authors_truncated", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
