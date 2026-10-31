# STATUS: oneshot (2026-11-01)
"""Retire la série des enregistrements sources déjà normalisés quand elle désigne une plateforme (`names_platform`), comme le fait la normalisation.

Les candidats ont une série, et un DOI de serveur de preprints ou une source OpenAlex du registre des plateformes. La règle lit la série dans `biblio.journal` et le DOI de la ligne de `staging`, sans relire le raw store. Seul `biblio.journal` est retiré ; la phase `publishing` détache ensuite ces enregistrements sources de leur revue.

Usage :
    uv run python -m interfaces.cli.oneshot.drop_platform_series [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter

from sqlalchemy import text

from domain.platforms.platform import PlatformType
from domain.platforms.registry import KNOWN_PLATFORMS, names_platform
from domain.source_records.biblio import BiblioKey, JournalKey, with_journal
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("drop_platform_series", os.path.dirname(__file__))

_PREPRINT_PREFIXES = sorted(
    {
        f"%{prefix}/%"
        for p in KNOWN_PLATFORMS
        if p.platform_type is PlatformType.PREPRINT_SERVER
        for prefix in p.doi_prefixes
    }
)
_OPENALEX_IDS = sorted({i for p in KNOWN_PLATFORMS for i in p.openalex_ids})

_CANDIDATES = text("""
    SELECT sr.id, sr.source::text AS source, sr.biblio, st.doi
    FROM source_records sr
    LEFT JOIN staging st ON st.id = sr.staging_id
    WHERE sr.biblio ? 'journal'
      AND (st.doi ILIKE ANY(:prefixes)
           OR sr.biblio->'journal'->>'openalex_id' = ANY(:openalex_ids))
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
        candidates = conn.execute(
            _CANDIDATES, {"prefixes": _PREPRINT_PREFIXES, "openalex_ids": _OPENALEX_IDS}
        ).all()
        log.info("%d enregistrements sources candidats", len(candidates))
        rows: list[dict[str, object]] = []
        titles: Counter[tuple[str, str]] = Counter()
        for r in candidates:
            journal = r.biblio.get(BiblioKey.JOURNAL) or {}
            title = journal.get(JournalKey.TITLE)
            if names_platform([title], openalex_id=journal.get(JournalKey.OPENALEX_ID), doi=r.doi):
                rows.append({"id": r.id, "biblio": with_journal(r.biblio, None)})
                titles[(r.source, str(title))] += 1
        for (source, title), n in titles.most_common(20):
            log.info("  %s « %s » : %d", source, title, n)
        if args.dry_run:
            log.info("%d séries de plateforme. Dry-run, rien écrit.", len(rows))
            return
        if rows:
            conn.execute(_WRITE, {"rows": json.dumps(rows)})
        conn.commit()
        log.info("%d séries de plateforme retirées", len(rows))


if __name__ == "__main__":
    main()
