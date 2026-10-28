# STATUS: oneshot (2026-10-28)
"""Remet en file de normalisation les enregistrements sources dont le résumé contient une formule en deux versions, LaTeX et MathML.

Ces résumés contiennent une formule MathML et soit une formule LaTeX `$$…$$`, soit une annotation LaTeX. Leur payload est réinjecté en `staging` depuis le raw store (`rehydrate_staging_row`) ; la normalisation les réécrit ensuite avec `drop_duplicate_mathml`, puis la phase `publications` recalcule le résumé de leurs publications :
    run_pipeline --from normalize --sources crossref,openalex

Usage :
    python -m interfaces.cli.oneshot.renormalize_duplicate_mathml_abstracts [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import UnreadablePayloadError, get_raw_store
from interfaces.cli.maintenance.rehydrate_staging_from_raw_store import rehydrate_staging_row

log = setup_logger("renormalize_duplicate_mathml_abstracts", os.path.dirname(__file__))

_TARGETS = text("""
    SELECT st.source::text AS source, st.source_id
    FROM source_records sr
    JOIN staging st ON st.id = sr.staging_id
    WHERE strpos(sr.abstract, '<mml:math') > 0
      AND (strpos(sr.abstract, '$$') > 0 OR strpos(sr.abstract, 'application/x-tex') > 0)
    ORDER BY st.source, st.source_id
""")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte les cibles sans rien écrire")
    args = parser.parse_args()
    store = get_raw_store()
    with get_sync_engine().begin() as conn:
        targets = conn.execute(_TARGETS).all()
        log.info("%d enregistrements sources à renormaliser", len(targets))
        if args.dry_run:
            log.info("Dry-run, rien écrit.")
            return
        rehydrated = 0
        for source, source_id in targets:
            try:
                raw_data = json.loads(store.get(source, source_id))
            except (KeyError, UnreadablePayloadError, ValueError):
                log.warning("%s/%s : payload absent ou illisible au raw store", source, source_id)
                continue
            rehydrated += rehydrate_staging_row(conn, source, source_id, raw_data)
        log.info("%d lignes staging remises en file de normalisation", rehydrated)


if __name__ == "__main__":
    main()
