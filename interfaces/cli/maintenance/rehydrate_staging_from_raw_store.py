"""Réhydrate `staging.raw_data` depuis le raw store, pour renormaliser une source.

Opération inverse de `mark_done` (`infrastructure/queries/pipeline/staging.py`),
qui archive le payload au raw store puis vide `staging.raw_data` (`= '{}'`) et
pose `processed = TRUE`. Une fois une source normalisée, son payload brut ne
survit plus qu'au raw store ; ce script le réinjecte en base pour permettre une
nouvelle passe de normalisation.

Pour chaque source demandée, parcourt les clés du raw store
(`data/raw_store/{source}/{source_id}.json.gz`), lit chaque payload et fait
`UPDATE staging SET raw_data = <payload>, raw_hash = md5(canonique), processed
= FALSE` sur la ligne `(source, source_id)` correspondante. `raw_hash` est
recalculé depuis le payload réhydraté (`compute_hash`), préservant l'invariant
`raw_hash = md5(canonical_json_bytes(raw_data))`.

Ne touche que les lignes `staging` déjà présentes (clé `UNIQUE (source,
source_id)`) : une clé du store sans ligne correspondante est comptée comme
orpheline et signalée, jamais réinsérée (le DOI et la provenance ne sont pas
reconstructibles depuis le seul payload).

Ne lance PAS la normalisation : une fois réhydraté, relancer
    python run_pipeline.py --only normalize --sources <sources>

Usage :
    python -m interfaces.cli.maintenance.rehydrate_staging_from_raw_store \
        --sources hal,openalex [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from domain.sources.registry import ALL_SOURCES_SET
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import get_raw_store
from infrastructure.sources.common import compute_hash

log = setup_logger("rehydrate_staging_from_raw_store", os.path.dirname(__file__))

_COMMIT_BATCH = 500

_REHYDRATE_SQL = text(
    """
    UPDATE staging
    SET raw_data = :raw_data, raw_hash = :raw_hash, processed = FALSE
    WHERE source = :source AND source_id = :source_id
    """
).bindparams(bindparam("raw_data", type_=JSONB))


def _parse_sources(raw: str) -> list[str]:
    sources = [s.strip() for s in raw.split(",") if s.strip()]
    unknown = [s for s in sources if s not in ALL_SOURCES_SET]
    if unknown:
        valides = ", ".join(sorted(ALL_SOURCES_SET))
        raise SystemExit(f"Source(s) inconnue(s) : {', '.join(unknown)}. Valides : {valides}")
    if not sources:
        raise SystemExit("Aucune source fournie.")
    return sources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources",
        required=True,
        help="Sources à réhydrater, séparées par des virgules (ex: hal,openalex).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compte les clés présentes au raw store sans rien écrire.",
    )
    args = parser.parse_args()
    sources = _parse_sources(args.sources)

    store = get_raw_store()

    if args.dry_run:
        for source in sources:
            n = sum(1 for _ in store.iter_keys(source))
            log.info("%s : %d payloads au raw store", source, n)
        log.info("Dry-run, rien écrit.")
        return

    engine = get_sync_engine()
    with engine.connect() as conn:
        for source in sources:
            rehydrated = 0
            orphans = 0
            for source_id in store.iter_keys(source):
                raw_data = json.loads(store.get(source, source_id))
                result = conn.execute(
                    _REHYDRATE_SQL,
                    {
                        "raw_data": raw_data,
                        "raw_hash": compute_hash(raw_data),
                        "source": source,
                        "source_id": source_id,
                    },
                )
                if result.rowcount:
                    rehydrated += 1
                else:
                    orphans += 1
                    log.warning(
                        "%s/%s : aucune ligne staging (orpheline, ignorée)", source, source_id
                    )

                done = rehydrated + orphans
                if done % _COMMIT_BATCH == 0:
                    conn.commit()
                    log.info("%s : %d traités...", source, done)

            conn.commit()
            log.info(
                "%s : %d réhydratés (processed=FALSE), %d orphelins ignorés",
                source,
                rehydrated,
                orphans,
            )

    log.info(
        "Terminé. Relancer la normalisation : python run_pipeline.py --only normalize --sources %s",
        ",".join(sources),
    )


if __name__ == "__main__":
    main()
