# STATUS: oneshot (2026-11-01)
"""Retire la série sans ISSN des chapitres, des livres et des communications déjà normalisés, comme le fait la normalisation (`determine_container_type`).

Le conteneur d'un tel document est son volume. Sa série se reconnaît seulement par un ISSN. Le rôle du conteneur se lit sur le type brut et la déclaration de congrès en base (`container_role`), sans relire le raw store. Seul `biblio.journal` est retiré ; la phase `publishing` détache ensuite ces enregistrements sources de leur revue.

Usage :
    uv run python -m interfaces.cli.oneshot.drop_series_without_issn [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter

from sqlalchemy import text

from domain.serials.containers import ContainerRole, container_role
from domain.source_records.biblio import BiblioKey, JournalKey, with_journal
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sql_fragments import declares_conference_sql

log = setup_logger("drop_series_without_issn", os.path.dirname(__file__))

# Séries sans ISSN valide.
_CANDIDATES = text(f"""
    SELECT sr.id, sr.source::text AS source, sr.raw_doc_type, sr.biblio,
           {declares_conference_sql("sr")} AS declares_conference
    FROM source_records sr
    WHERE sr.biblio ? 'journal'
      AND NOT EXISTS (
          SELECT 1 FROM jsonb_array_elements(coalesce(sr.biblio->'journal'->'issns', '[]'::jsonb)) e
          WHERE NOT coalesce((e->>'malformed')::boolean, false)
      )
""")

_WRITE = text("""
    UPDATE source_records sr SET biblio = NULLIF(t.biblio, 'null'::jsonb)
    FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS t(id integer, biblio jsonb)
    WHERE sr.id = t.id
""")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Compte les séries sans rien écrire")
    args = parser.parse_args()
    with get_sync_engine().connect() as conn:
        candidates = conn.execute(_CANDIDATES).all()
        rows: list[dict[str, object]] = []
        kinds: Counter[tuple[str, str]] = Counter()
        examples: list[tuple[str, object]] = []
        for r in candidates:
            role = container_role(
                r.raw_doc_type, r.source, declares_conference=r.declares_conference
            )
            if role is ContainerRole.JOURNAL:
                continue
            rows.append({"id": r.id, "biblio": with_journal(r.biblio, None)})
            kinds[(r.source, str(r.raw_doc_type))] += 1
            if len(examples) < 5:
                examples.append(
                    (r.source, (r.biblio.get(BiblioKey.JOURNAL) or {}).get(JournalKey.TITLE))
                )
        log.info(
            "%d séries sans ISSN, dont %d de chapitre, livre ou communication",
            len(candidates),
            len(rows),
        )
        for (source, raw_doc_type), n in kinds.most_common(20):
            log.info("  %s « %s » : %d", source, raw_doc_type, n)
        for source, title in examples:
            log.info("  exemple : %s « %s »", source, title)
        if args.dry_run:
            log.info("Dry-run, rien écrit.")
            return
        if rows:
            conn.execute(_WRITE, {"rows": json.dumps(rows)})
        conn.commit()
        log.info("%d séries retirées", len(rows))


if __name__ == "__main__":
    main()
