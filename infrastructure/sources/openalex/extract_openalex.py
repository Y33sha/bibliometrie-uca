"""
Extraction des publications UCA depuis l'API OpenAlex.

Usage:
    python extract_openalex.py              # extraction complète 2022-2025
    python extract_openalex.py --year 2024  # une seule année
    python extract_openalex.py --dry-run    # compte les résultats sans insérer

L'API OpenAlex est interrogée via le filtre institution (ROR) + année.
Les résultats bruts sont stockés dans staging (JSONB).
Les works déjà présents (même openalex_id) sont ignorés.
"""

import argparse
import os
import time
from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from domain.pipeline_metrics import PhaseMetrics
from infrastructure.sources.api_limits import OPENALEX_DELAY
from infrastructure.sources.base import (
    ExtractionConfigError,
    SourceExtractor,
    run_extractor,
)
from infrastructure.sources.common import compute_hash, setup_logger
from infrastructure.sources.config import (
    get_api_base_urls,
    get_extraction_api_ids,
    get_openalex_api_key,
    get_openalex_email,
    get_years,
)
from infrastructure.sources.http_retry import http_request_with_retry
from infrastructure.sources.openalex import init_auth
from infrastructure.sources.openalex.parsing import (
    build_params,
    extract_doi,
    extract_openalex_id,
)

# ----- Logging -----
logger = setup_logger("extract_openalex", os.path.join(os.path.dirname(__file__), "logs"))


def fetch_page(
    base_url: str,
    year: int = None,
    cursor: str = "*",
    institution_ids: list[str] = None,
    since: str = None,
) -> dict:
    """Récupère une page de résultats depuis l'API OpenAlex (avec retry/backoff)."""
    params = build_params(year, cursor, institution_ids=institution_ids, since=since)
    label = f"OpenAlex {since or year}"
    return http_request_with_retry("GET", base_url, params=params, timeout=30, label=label)


_INSERT_OA_BATCH_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash)
    VALUES ('openalex', :source_id, :doi, :raw_data, :raw_hash)
    ON CONFLICT (source, source_id) DO UPDATE SET
        raw_data = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN EXCLUDED.raw_data
            ELSE staging.raw_data
        END,
        raw_hash = COALESCE(EXCLUDED.raw_hash, staging.raw_hash),
        processed = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN FALSE
            ELSE staging.processed
        END,
        last_seen_at = now()
    """
).bindparams(bindparam("raw_data", type_=JSONB))


def insert_batch(conn: Connection, batch: list[dict]) -> int:
    """Insère / met à jour un batch de works dans staging.

    `raw_hash` est l'unique clé de détection de changement, aligné sur le
    pattern des autres sources (HAL/ScanR/WoS/theses/crossref). La
    préservation des authorships complètes obtenues par
    `refetch_truncated` repose sur le fait que **refetch ne recalcule pas
    `raw_hash`** : la ligne refetchée garde le hash du payload bulk
    initial. Tant que le bulk renvoie ce même payload, la comparaison
    `raw_hash` reste équivalente et l'UPSERT ne touche pas `raw_data`.

    Le caller est responsable du `conn.commit()` après cette fonction.

    Retourne le nombre de documents dont le hash a changé.
    """
    source_ids = [b["source_id"] for b in batch]
    rows = conn.execute(
        text(
            "SELECT source_id, raw_hash FROM staging "
            "WHERE source = 'openalex' AND source_id = ANY(:ids)"
        ),
        {"ids": source_ids},
    ).all()
    old_hashes = {r.source_id: r.raw_hash for r in rows}

    conn.execute(_INSERT_OA_BATCH_SQL, batch)

    updated = sum(
        1
        for entry in batch
        if entry["source_id"] in old_hashes and old_hashes[entry["source_id"]] != entry["raw_hash"]
    )
    return updated


def extract_year(
    year: int | None = None,
    conn: Connection | None = None,
    existing_ids: set | None = None,
    base_url: str = "",
    institution_ids: list[str] | None = None,
    since: str | None = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Extrait des publications OpenAlex par année ou par date de modification.
    Retourne (nouveaux, mis_a_jour).
    """
    cursor = "*"
    total_fetched = 0
    total_new = 0
    total_updated = 0
    page_num = 0

    # Premier appel pour avoir le count total
    first_page = fetch_page(base_url, year, cursor, institution_ids=institution_ids, since=since)
    total_count = first_page["meta"]["count"]
    label = f"depuis {since}" if since else f"année {year}"
    logger.info(f"{label} : {total_count} works trouvés sur OpenAlex")

    if dry_run:
        return 0, 0

    assert conn is not None, "conn requis hors dry_run"
    while True:
        page_num += 1

        if page_num == 1:
            data = first_page
        else:
            data = fetch_page(base_url, year, cursor, institution_ids=institution_ids, since=since)

        results = data.get("results", [])
        if not results:
            break

        # Préparer le batch
        batch: list[dict] = []
        new_count = 0
        for work in results:
            oa_id = extract_openalex_id(work)
            batch.append(
                {
                    "source_id": oa_id,
                    "doi": extract_doi(work),
                    "raw_data": work,
                    "raw_hash": compute_hash(work),
                }
            )
            if existing_ids is not None and oa_id not in existing_ids:
                existing_ids.add(oa_id)
                new_count += 1

        # Insérer / mettre à jour
        updated_count = 0
        if batch:
            updated_count = insert_batch(conn, batch)
            conn.commit()
            total_new += new_count
            total_updated += updated_count

        total_fetched += len(results)
        parts = []
        if new_count:
            parts.append(f"{new_count} nouveaux")
        if updated_count:
            parts.append(f"{updated_count} mis à jour")
        if not parts:
            parts.append("aucun changement")
        logger.info(
            f"  Page {page_num} : {len(results)} works — {', '.join(parts)} "
            f"({total_fetched}/{total_count})"
        )

        # Pagination cursor
        next_cursor = data["meta"].get("next_cursor")
        if not next_cursor:
            break
        cursor = next_cursor

        time.sleep(OPENALEX_DELAY)

    logger.info(
        f"Année {year} terminée : {total_new} nouveaux, {total_updated} mis à jour "
        f"(sur {total_fetched} récupérés, {total_count} sur OpenAlex)"
    )
    return total_new, total_updated


class OpenalexExtractor(SourceExtractor):
    SOURCE = "openalex"
    DESCRIPTION = "Extraction OpenAlex → staging"

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--year", type=int, help="Année spécifique (sinon toutes)")
        parser.add_argument(
            "--mode", choices=["full", "weekly"], default="full", help="Mode (défaut: full)"
        )
        parser.add_argument(
            "--since",
            help="Date ISO (YYYY-MM-DD) : ne récupérer que les documents modifiés depuis cette date",
        )

    def load_config(self, conn: Connection) -> dict[str, Any]:
        institution_ids = get_extraction_api_ids(conn, "openalex")
        if not institution_ids:
            raise ExtractionConfigError(
                "aucun institution_id OpenAlex configuré "
                "(structures.api_ids->'openalex' vide pour le périmètre d'extraction)"
            )
        init_auth(api_key=get_openalex_api_key(conn), email=get_openalex_email(conn))
        return {
            "institution_ids": institution_ids,
            "base_url": get_api_base_urls(conn).get("openalex", "https://api.openalex.org/works"),
        }

    def setup_logging(self, args: argparse.Namespace, config: dict[str, Any]) -> None:
        self.logger.info(
            f"Institutions OpenAlex : {', '.join(config['institution_ids'])} (lineage OR)"
        )
        if args.since:
            self.logger.info(f"Mode incrémental : documents modifiés depuis {args.since}")

    def extract_all(
        self, args: argparse.Namespace, config: dict[str, Any], existing_ids: set
    ) -> PhaseMetrics:
        config_years = get_years(self.conn, mode=args.mode)
        years = [args.year] if args.year else config_years
        if not args.since:
            self.logger.info(f"Années : {years}")

        stats = PhaseMetrics()
        if args.since:
            year_new, year_updated = extract_year(
                conn=self.conn,
                existing_ids=existing_ids,
                base_url=config["base_url"],
                institution_ids=config["institution_ids"],
                since=args.since,
                dry_run=args.dry_run,
            )
            stats.add(new=year_new, updated=year_updated)
        else:
            for year in years:
                year_new, year_updated = extract_year(
                    year,
                    self.conn,
                    existing_ids,
                    base_url=config["base_url"],
                    institution_ids=config["institution_ids"],
                    dry_run=args.dry_run,
                )
                stats.add(new=year_new, updated=year_updated)
        return stats


def main() -> None:
    run_extractor(OpenalexExtractor, logger)


if __name__ == "__main__":
    main()
