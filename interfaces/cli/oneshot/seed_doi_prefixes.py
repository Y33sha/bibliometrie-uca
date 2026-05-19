# STATUS: oneshot (2026-05-19)
"""
Seed initial de `doi_prefixes` depuis les caches du spike Phase 0.

Lit `docs/chantiers/doi-prefixes-spike-data/ra_cache.json` (871 préfixes
résolus via doi.org/ra) et `publisher_cache.json` (718 préfixes Crossref
avec `name` + `member` via api.crossref.org/prefixes/), normalise les
noms d'éditeurs via `normalize_text`, matche contre
`publisher_name_forms.form_normalized` pour rattacher chaque préfixe à
un `publisher_id` quand un éditeur existe déjà, et insère le tout.

Idempotent : `ON CONFLICT (prefix) DO NOTHING`. Évite ~900 appels API
inutiles au premier run de la phase `resolve_doi_prefixes` en prod.

Usage :
    python -m interfaces.cli.oneshot.seed_doi_prefixes [--dry-run]

Lancement attendu : une seule fois, juste après la migration Alembic
0019 (`CREATE TABLE doi_prefixes`).
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text

from domain.normalize import normalize_text
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("seed_doi_prefixes", os.path.dirname(__file__))

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "docs" / "chantiers" / "doi-prefixes-spike-data"
RA_CACHE = DATA_DIR / "ra_cache.json"
PUBLISHER_CACHE = DATA_DIR / "publisher_cache.json"

_MEMBER_URL_RE = re.compile(r"/member/(\d+)\b")


def _parse_member_id(member: Any) -> int | None:
    """`https://id.crossref.org/member/10` → `10`."""
    if member is None:
        return None
    if isinstance(member, int):
        return member
    if isinstance(member, str):
        m = _MEMBER_URL_RE.search(member)
        if m:
            return int(m.group(1))
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche le plan sans écrire en base.",
    )
    args = parser.parse_args()

    ra_cache: dict[str, str] = json.loads(RA_CACHE.read_text(encoding="utf-8"))
    publisher_cache: dict[str, dict[str, Any]] = json.loads(
        PUBLISHER_CACHE.read_text(encoding="utf-8")
    )
    log.info(f"ra_cache : {len(ra_cache)} préfixes")
    log.info(f"publisher_cache : {len(publisher_cache)} préfixes")

    engine = get_sync_engine()
    with engine.connect() as conn:
        # Récupère tous les (form_normalized → publisher_id) en mémoire
        # pour un matching O(1). ~quelques centaines à milliers de
        # publishers, négligeable.
        forms = {
            row.form_normalized: row.publisher_id
            for row in conn.execute(
                text("SELECT form_normalized, publisher_id FROM publisher_name_forms")
            )
        }
        log.info(f"publisher_name_forms : {len(forms)} formes chargées")

        rows_to_insert: list[dict[str, Any]] = []
        stats = {"crossref_matched": 0, "crossref_unmatched": 0, "non_crossref": 0}

        for prefix, ra in sorted(ra_cache.items()):
            row: dict[str, Any] = {
                "prefix": prefix,
                "ra": ra,
                "publisher_id": None,
                "publisher_name_raw": None,
                "publisher_name_normalized": None,
                "crossref_member_id": None,
            }
            if ra == "Crossref":
                pub_info = publisher_cache.get(prefix, {})
                name_raw = pub_info.get("name")
                member_id = _parse_member_id(pub_info.get("member"))
                if name_raw:
                    name_norm = normalize_text(name_raw) or None
                    row["publisher_name_raw"] = name_raw
                    row["publisher_name_normalized"] = name_norm
                    row["crossref_member_id"] = member_id
                    if name_norm and name_norm in forms:
                        row["publisher_id"] = forms[name_norm]
                        stats["crossref_matched"] += 1
                    else:
                        stats["crossref_unmatched"] += 1
                else:
                    stats["crossref_unmatched"] += 1
            else:
                stats["non_crossref"] += 1
            rows_to_insert.append(row)

        log.info(
            f"plan : {len(rows_to_insert)} rows — "
            f"crossref matché : {stats['crossref_matched']}, "
            f"crossref non matché : {stats['crossref_unmatched']}, "
            f"autres RA : {stats['non_crossref']}"
        )

        if args.dry_run:
            log.info("dry-run : aucune écriture")
            return 0

        result = conn.execute(
            text(
                """
                INSERT INTO doi_prefixes (
                    prefix, ra, publisher_id,
                    publisher_name_raw, publisher_name_normalized,
                    crossref_member_id
                )
                VALUES (
                    :prefix, :ra, :publisher_id,
                    :publisher_name_raw, :publisher_name_normalized,
                    :crossref_member_id
                )
                ON CONFLICT (prefix) DO NOTHING
                """
            ),
            rows_to_insert,
        )
        conn.commit()
        log.info(f"INSERT : {result.rowcount} rows insérées (autres = conflits ignorés)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
