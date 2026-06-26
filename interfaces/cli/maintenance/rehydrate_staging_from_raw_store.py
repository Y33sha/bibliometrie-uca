"""Réhydrate `staging.raw_data` depuis le raw store, pour renormaliser une source.

Opération inverse de `mark_done` (`infrastructure/queries/pipeline/staging.py`),
qui archive le payload au raw store puis vide `staging.raw_data` (`= '{}'`) et
pose `processed = TRUE`. Une fois une source normalisée, son payload brut ne
survit plus qu'au raw store ; ce script le réinjecte en base pour permettre une
nouvelle passe de normalisation.

Pour chaque source demandée, parcourt les clés du raw store
(`data/raw_store/{source}/{source_id}.json.gz`), lit chaque payload et
réhydrate la ligne `(source, source_id)` : `raw_data = <payload>`, `raw_hash =
md5(canonique)` (recalculé depuis le payload, préservant l'invariant `raw_hash =
md5(canonical_json_bytes(raw_data))`), `processed = FALSE`.

Deux modes :

- défaut : ne met à jour que les lignes `staging` déjà présentes. Une clé du
  store sans ligne correspondante est comptée comme orpheline et signalée.
- `--full` : réinsère aussi les orphelins (cas d'un `TRUNCATE staging`, où tout
  est orphelin par définition). Le `source_id` est la clé du store et le `doi`
  est ré-extrait du payload par la logique propre à chaque source. Les drapeaux
  de provenance non reconstructibles depuis le seul payload (`entry_mode`,
  `authors_truncated`) reprennent leur défaut et se recalculent au prochain
  extract bulk réel.

Ne lance PAS la normalisation : une fois réhydraté, relancer
    python run_pipeline.py --only normalize --sources <sources>

Usage :
    python -m interfaces.cli.maintenance.rehydrate_staging_from_raw_store \
        --sources hal,openalex [--full] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from domain.sources.registry import ALL_SOURCES_SET
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import get_raw_store
from infrastructure.sources.common import compute_hash
from infrastructure.sources.hal.extract_hal import extract_doi as hal_extract_doi
from infrastructure.sources.openalex.parsing import extract_doi as openalex_extract_doi
from infrastructure.sources.scanr.extract_scanr import extract_doi as scanr_extract_doi
from infrastructure.sources.theses.extract_theses import extract_doi as theses_extract_doi
from infrastructure.sources.wos.parsing import extract_doi as wos_extract_doi

log = setup_logger("rehydrate_staging_from_raw_store", os.path.dirname(__file__))

_COMMIT_BATCH = 500

# DOI ré-extrait du payload par la logique propre à chaque source (réutilise les
# extracteurs des phases d'extraction, pas de réimplémentation). crossref et
# datacite sont absents : ce sont des sources DOI-natives dont le `source_id`
# (clé du store) est déjà le DOI — cf. `_doi_for`.
_DOI_EXTRACTORS: dict[str, Callable[[dict[str, Any]], str | None]] = {
    "hal": hal_extract_doi,
    "openalex": openalex_extract_doi,
    "wos": wos_extract_doi,
    "scanr": scanr_extract_doi,
    "theses": theses_extract_doi,
}


def _doi_for(source: str, source_id: str, raw_data: dict[str, Any]) -> str | None:
    """DOI à poser en staging pour un payload réhydraté."""
    if source in ("crossref", "datacite"):
        return source_id  # sources DOI-natives : source_id == doi
    return _DOI_EXTRACTORS[source](raw_data)


# Mode défaut : ne touche que les lignes déjà présentes (rowcount = 0 → orpheline).
_UPDATE_SQL = text(
    """
    UPDATE staging
    SET raw_data = :raw_data, raw_hash = :raw_hash, processed = FALSE
    WHERE source = :source AND source_id = :source_id
    """
).bindparams(bindparam("raw_data", type_=JSONB))

# Mode --full : réinsère les orphelins et force la réhydratation des existants
# (le `raw_hash` inchangé d'une ligne déjà normalisée interdit de passer par
# `upsert_staging`, qui ne réécrit que sur changement de hash). `doi` n'est posé
# qu'à l'insertion ; une ligne existante garde son `doi` d'origine.
_UPSERT_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, processed)
    VALUES (:source, :source_id, :doi, :raw_data, :raw_hash, FALSE)
    ON CONFLICT (source, source_id) DO UPDATE SET
        raw_data = EXCLUDED.raw_data,
        raw_hash = EXCLUDED.raw_hash,
        processed = FALSE
    RETURNING (xmax = 0) AS inserted
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
        "--full",
        action="store_true",
        help="Réinsère aussi les clés orphelines (après un TRUNCATE staging).",
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
            inserted = 0
            updated = 0
            orphans = 0
            seen = 0
            for source_id in store.iter_keys(source):
                raw_data = json.loads(store.get(source, source_id))
                params = {
                    "raw_data": raw_data,
                    "raw_hash": compute_hash(raw_data),
                    "source": source,
                    "source_id": source_id,
                }
                if args.full:
                    params["doi"] = _doi_for(source, source_id, raw_data)
                    row = conn.execute(_UPSERT_SQL, params).one()
                    if row.inserted:
                        inserted += 1
                    else:
                        updated += 1
                else:
                    if conn.execute(_UPDATE_SQL, params).rowcount:
                        updated += 1
                    else:
                        orphans += 1
                        log.warning(
                            "%s/%s : aucune ligne staging (orpheline, ignorée)", source, source_id
                        )

                seen += 1
                if seen % _COMMIT_BATCH == 0:
                    conn.commit()
                    log.info("%s : %d traités...", source, seen)

            conn.commit()
            if args.full:
                log.info(
                    "%s : %d insérés, %d mis à jour (processed=FALSE)", source, inserted, updated
                )
            else:
                log.info(
                    "%s : %d mis à jour (processed=FALSE), %d orphelins ignorés",
                    source,
                    updated,
                    orphans,
                )

    log.info(
        "Terminé. Relancer la normalisation : python run_pipeline.py --only normalize --sources %s",
        ",".join(sources),
    )


if __name__ == "__main__":
    main()
