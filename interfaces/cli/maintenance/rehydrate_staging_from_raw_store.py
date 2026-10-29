# STATUS: maintenance
"""Réhydrate `staging.raw_data` depuis le raw store, pour normaliser de nouveau une source.

Opération inverse de `StagingStore.mark_done` (`pipeline/ingestion/common/staging.py`), qui archive le payload au raw store, vide `staging.raw_data` et marque la ligne traitée. Une source normalisée garde son payload brut seulement dans le raw store ; ce script le remet en base pour rejouer la normalisation.

Pour chaque source demandée, le script parcourt les clés du raw store (`data/raw_store/{source}/{source_id}.json.gz`), lit chaque payload et réhydrate la ligne `(source, source_id)` : `raw_data` reçoit le payload, `raw_hash` son empreinte (`change_detection_hash`, celle du moissonnage), et la ligne repasse à normaliser.

Deux modes :

- par défaut, seules les lignes `staging` présentes sont mises à jour ; une clé du store sans ligne est comptée comme orpheline et signalée ;
- `--full` réinsère aussi les orphelines, par exemple après un `TRUNCATE staging`. Le `source_id` est la clé du store, et le DOI se relit dans le payload par l'adaptateur de la source. La provenance (`entry_mode`) et le marqueur de troncature (`authors_truncated`), que le payload seul ne donne pas, reprennent leur défaut et se recalculent au moissonnage suivant.

La normalisation se lance ensuite, avec les phases qui la suivent :
    run_pipeline --from normalize --sources <sources>

`--doi-prefix` limite une source dont l'identifiant natif est le DOI (crossref, datacite) aux DOI d'un préfixe. `--id-prefix` limite toute source aux identifiants d'un préfixe. La normalisation traite ensuite ces seuls documents.

Usage :
    python -m interfaces.cli.maintenance.rehydrate_staging_from_raw_store \
        --sources hal,openalex [--full] [--dry-run]
    python -m interfaces.cli.maintenance.rehydrate_staging_from_raw_store \
        --sources crossref --doi-prefix 10.70675
    python -m interfaces.cli.maintenance.rehydrate_staging_from_raw_store \
        --sources scanr --id-prefix nnt
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterator, Mapping

from sqlalchemy import Connection, bindparam, text

from domain.sources.registry import ALL_SOURCES_SET, Source
from infrastructure.db.engine import get_sync_engine
from infrastructure.db.jsonb import Jsonb
from infrastructure.observability.log import setup_logger
from infrastructure.raw_store import UnreadablePayloadError, get_raw_store
from pipeline.ingestion.adapters import ADAPTERS
from pipeline.ingestion.common.change_detection import change_detection_hash

log = setup_logger("rehydrate_staging_from_raw_store", os.path.dirname(__file__))

from domain.types import JsonValue

_COMMIT_BATCH = 500

_REHYDRATE_UPDATE_SQL = text(
    """
    UPDATE staging
    SET raw_data = :raw_data, raw_hash = :raw_hash, processed = FALSE
    WHERE source = :source AND source_id = :source_id
    """
).bindparams(bindparam("raw_data", type_=Jsonb))

_REHYDRATE_UPSERT_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, processed)
    VALUES (:source, :source_id, :doi, :raw_data, :raw_hash, FALSE)
    ON CONFLICT (source, source_id) DO UPDATE SET
        raw_data = EXCLUDED.raw_data,
        raw_hash = EXCLUDED.raw_hash,
        processed = FALSE
    RETURNING (xmax = 0) AS inserted
    """
).bindparams(bindparam("raw_data", type_=Jsonb))


def rehydrate_staging_row(
    conn: Connection, source: str, source_id: str, raw_data: Mapping[str, JsonValue]
) -> bool:
    """Remet un payload archivé dans une ligne `staging` existante, prête à normaliser : `raw_data`, `raw_hash` (`change_detection_hash`) et état à traiter. Rend faux si la ligne est absente (clé orpheline du raw store)."""
    return (
        conn.execute(
            _REHYDRATE_UPDATE_SQL,
            {
                "raw_data": raw_data,
                "raw_hash": change_detection_hash(source, raw_data),
                "source": source,
                "source_id": source_id,
            },
        ).rowcount
        > 0
    )


def rehydrate_or_create_staging_row(
    conn: Connection,
    source: str,
    source_id: str,
    doi: str | None,
    raw_data: Mapping[str, JsonValue],
) -> bool:
    """Réhydrate une ligne `staging`, en la créant si elle manque (après un `TRUNCATE staging`, où tout est orphelin).

    Réinsère les clés orphelines et écrase les lignes existantes. Le DOI se pose seulement à l'insertion : une ligne existante garde le sien. Rend vrai pour une ligne insérée, faux pour une ligne mise à jour.
    """
    return bool(
        conn.execute(
            _REHYDRATE_UPSERT_SQL,
            {
                "raw_data": raw_data,
                "raw_hash": change_detection_hash(source, raw_data),
                "source": source,
                "source_id": source_id,
                "doi": doi,
            },
        ).scalar_one()
    )


def _doi_for(source: str, raw_data: Mapping[str, JsonValue]) -> str | None:
    """DOI à poser en staging pour un payload réhydraté, lu par l'adaptateur de la source."""
    identity = ADAPTERS[Source(source)].identify(raw_data)
    return identity.doi if identity else None


# Sources dont l'identifiant natif est le DOI : leur clé d'archive commence par un préfixe de DOI.
_DOI_NATIVE_SOURCES = frozenset({"crossref", "datacite"})


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
        "--doi-prefix",
        help="Limite la réhydratation aux DOI de ce préfixe (ex: 10.70675). Sources crossref et datacite seulement.",
    )
    parser.add_argument(
        "--id-prefix",
        help="Limite la réhydratation aux identifiants source de ce préfixe (ex: nnt pour les thèses scanR).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compte les clés présentes au raw store sans rien écrire.",
    )
    args = parser.parse_args()
    sources = _parse_sources(args.sources)
    if args.doi_prefix and not set(sources) <= _DOI_NATIVE_SOURCES:
        raise SystemExit("--doi-prefix s'applique seulement aux sources crossref et datacite.")
    if args.doi_prefix and args.id_prefix:
        raise SystemExit("--doi-prefix et --id-prefix s'excluent.")

    store = get_raw_store()
    prefix = f"{args.doi_prefix}/" if args.doi_prefix else args.id_prefix or ""

    def keys(source: str) -> Iterator[str]:
        return (k for k in store.iter_keys(source) if k.startswith(prefix))

    if args.dry_run:
        for source in sources:
            n = sum(1 for _ in keys(source))
            log.info("%s : %d payloads au raw store", source, n)
        log.info("Dry-run, rien écrit.")
        return

    engine = get_sync_engine()
    with engine.connect() as conn:
        for source in sources:
            inserted = 0
            updated = 0
            orphans = 0
            unreadable = 0
            seen = 0
            for source_id in keys(source):
                try:
                    raw_data = json.loads(store.get(source, source_id))
                except UnreadablePayloadError, ValueError:
                    unreadable += 1
                    log.warning(
                        "%s/%s : payload illisible au raw store (ligne staging inchangée)",
                        source,
                        source_id,
                    )
                    continue
                if args.full:
                    doi = _doi_for(source, raw_data)
                    if rehydrate_or_create_staging_row(conn, source, source_id, doi, raw_data):
                        inserted += 1
                    else:
                        updated += 1
                elif rehydrate_staging_row(conn, source, source_id, raw_data):
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
                    "%s : %d insérés, %d mis à jour (processed=FALSE), %d illisibles",
                    source,
                    inserted,
                    updated,
                    unreadable,
                )
            else:
                log.info(
                    "%s : %d mis à jour (processed=FALSE), %d orphelins ignorés, %d illisibles",
                    source,
                    updated,
                    orphans,
                    unreadable,
                )

    log.info(
        "Terminé. Relancer le pipeline depuis la normalisation : "
        "run_pipeline --from normalize --sources %s",
        ",".join(sources),
    )


if __name__ == "__main__":
    main()
