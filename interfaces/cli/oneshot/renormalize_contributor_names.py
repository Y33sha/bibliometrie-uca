# STATUS: oneshot (2026-11-02)
"""Remet en file de normalisation les enregistrements sources dont un nom d'auteur stocké diffère de son nettoyage actuel (`clean_raw_author_name`) : caractères invisibles, séparateur final.

Le payload de ces enregistrements sources est réinjecté en `staging` depuis le raw store (`rehydrate_staging_row`). Leur empreinte de bloc auteurs (`authors_hash`) est vidée : la normalisation resynchronise leurs contributions sources, bloc auteurs inchangé compris. Les phases suivantes traitent ensuite ce qui a changé :
    run_pipeline --from normalize --sources <sources affichées>

Usage :
    uv run python -m interfaces.cli.oneshot.renormalize_contributor_names [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from functools import cache

from sqlalchemy import bindparam, text

from domain.normalize import clean_raw_author_name
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import UnreadablePayloadError, get_raw_store
from interfaces.cli.maintenance.rehydrate_staging_from_raw_store import rehydrate_staging_row

log = setup_logger("renormalize_contributor_names", os.path.dirname(__file__))

_EXAMPLES = 10

_NAMES = text("""
    SELECT source_record_id, raw_author_name, raw_last_name, raw_first_name
    FROM source_contributions
""")

_TARGETS = text("""
    SELECT sr.id, st.source::text AS source, st.source_id
    FROM source_records sr
    JOIN staging st ON st.id = sr.staging_id
    WHERE sr.id IN :ids
    ORDER BY st.source, st.source_id
""").bindparams(bindparam("ids", expanding=True))

_CLEAR_AUTHORS_HASH = text(
    "UPDATE source_records SET authors_hash = NULL WHERE id IN :ids"
).bindparams(bindparam("ids", expanding=True))


@cache
def _cleaned(name: str) -> str:
    return clean_raw_author_name(name).strip()


def _stale(name: str | None) -> bool:
    """Vrai si le nom stocké diffère de son nettoyage actuel."""
    return bool(name) and _cleaned(name) != name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="rapport seul, sans écriture")
    args = parser.parse_args()
    store = get_raw_store()
    with get_sync_engine().begin() as conn:
        ids: set[int] = set()
        stale_names: set[str] = set()
        rows = conn.execute(_NAMES, execution_options={"stream_results": True, "yield_per": 20_000})
        for source_record_id, *names in rows:
            stale = {name for name in names if _stale(name)}
            if stale:
                ids.add(source_record_id)
                stale_names |= stale
        targets = conn.execute(_TARGETS, {"ids": sorted(ids)}).all() if ids else []
        log.info(
            "%d noms, %d enregistrements sources à renormaliser", len(stale_names), len(targets)
        )
        for name in sorted(stale_names)[:_EXAMPLES]:
            log.info("    · %r → %r", name, _cleaned(name))
        sources = sorted({t.source for t in targets})
        if args.dry_run or not targets:
            log.info("Sources concernées : %s", ",".join(sources) or "aucune")
            return
        conn.execute(_CLEAR_AUTHORS_HASH, {"ids": [t.id for t in targets]})
        rehydrated = 0
        for target in targets:
            try:
                raw_data = json.loads(store.get(target.source, target.source_id))
            except KeyError, UnreadablePayloadError, ValueError:
                log.warning(
                    "%s/%s : payload absent ou illisible au raw store",
                    target.source,
                    target.source_id,
                )
                continue
            rehydrated += rehydrate_staging_row(conn, target.source, target.source_id, raw_data)
        log.info("%d lignes staging remises en file de normalisation", rehydrated)
        log.info("Ensuite : run_pipeline --from normalize --sources %s", ",".join(sources))


if __name__ == "__main__":
    main()
