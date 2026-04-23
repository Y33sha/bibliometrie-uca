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

from psycopg.types.json import Jsonb as Json

from infrastructure.api_limits import OPENALEX_DELAY, OPENALEX_PER_PAGE
from infrastructure.api_retry import http_request_with_retry
from infrastructure.app_config import (
    get_api_base_urls,
    get_extraction_api_ids,
    get_openalex_api_key,
    get_openalex_email,
    get_years,
)
from infrastructure.sources.base import (
    ExtractionConfigError,
    ExtractionStats,
    SourceExtractor,
    run_extractor,
)
from infrastructure.sources.common import compute_hash, setup_logger
from infrastructure.sources.openalex import (
    SELECT_FIELDS,
    auth_params,
    compute_meta_hash,
    extract_doi,
    extract_openalex_id,
    init_auth,
)

# ----- Logging -----
logger = setup_logger("extract_openalex", os.path.join(os.path.dirname(__file__), "logs"))


def build_params(
    year: int = None, cursor: str = "*", institution_ids: list[str] | None = None, since: str = None
) -> dict:
    """Construit les paramètres de requête pour l'API OpenAlex.

    Si since est fourni (YYYY-MM-DD), filtre sur from_updated_date
    au lieu de filtrer par année.
    """
    lineage_filter = "|".join(institution_ids or [])
    if since:
        filter_str = f"authorships.institutions.lineage:{lineage_filter},from_updated_date:{since}"
    else:
        filter_str = f"authorships.institutions.lineage:{lineage_filter},publication_year:{year}"
    return {
        "filter": filter_str,
        "select": SELECT_FIELDS,
        "per_page": OPENALEX_PER_PAGE,
        "cursor": cursor,
        **auth_params(),
    }


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


def insert_batch(conn: Any, batch: list[tuple]) -> int:
    """Insère un batch de works dans staging.

    Logique de mise à jour :
    - Compare meta_hash (métadonnées hors authorships) pour détecter les vrais changements
    - Si meta_hash identique → rien à faire
    - Si meta_hash différent → met à jour raw_data en préservant les authorships de la
      version en base si elle en a plus (cas des works >100 auteurs déjà re-fetchés)

    Retourne le nombre de documents dont les métadonnées ont changé.
    """
    query = """
        INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, meta_hash)
        VALUES (%s, %s, %s, %s::jsonb, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            raw_data = CASE
                WHEN staging.meta_hash IS NOT DISTINCT FROM EXCLUDED.meta_hash
                    THEN staging.raw_data
                WHEN jsonb_array_length(staging.raw_data->'authorships')
                     > jsonb_array_length(EXCLUDED.raw_data->'authorships')
                    THEN jsonb_set(staging.raw_data,
                         '{title}', EXCLUDED.raw_data->'title')
                      || jsonb_build_object(
                         'open_access', EXCLUDED.raw_data->'open_access',
                         'primary_location', EXCLUDED.raw_data->'primary_location',
                         'locations', EXCLUDED.raw_data->'locations',
                         'cited_by_count', EXCLUDED.raw_data->'cited_by_count',
                         'type', EXCLUDED.raw_data->'type',
                         'language', EXCLUDED.raw_data->'language',
                         'biblio', EXCLUDED.raw_data->'biblio',
                         'is_retracted', EXCLUDED.raw_data->'is_retracted')
                ELSE EXCLUDED.raw_data
            END,
            raw_hash = CASE
                WHEN staging.meta_hash IS NOT DISTINCT FROM EXCLUDED.meta_hash
                    THEN staging.raw_hash
                ELSE EXCLUDED.raw_hash
            END,
            meta_hash = COALESCE(EXCLUDED.meta_hash, staging.meta_hash),
            processed = CASE
                WHEN staging.meta_hash IS NOT DISTINCT FROM EXCLUDED.meta_hash
                    THEN staging.processed
                ELSE FALSE
            END,
            last_seen_at = now()
    """
    with conn.cursor() as cur:
        # Compter les documents existants avec un meta_hash différent
        source_ids = [b[1] for b in batch]
        cur.execute(
            """
            SELECT source_id, meta_hash FROM staging
            WHERE source = 'openalex' AND source_id = ANY(%s)
        """,
            (source_ids,),
        )
        old_hashes = {r["source_id"]: r["meta_hash"] for r in cur.fetchall()}

        cur.executemany(query, batch)
    conn.commit()

    # Compter les mises à jour réelles (meta_hash différent, document existant)
    updated = 0
    for _, source_id, _, _, _, meta_hash in batch:
        old = old_hashes.get(source_id)
        if old is not None and old != meta_hash:
            updated += 1
    return updated


def extract_year(
    year: int = None,
    conn: Any = None,
    existing_ids: set = None,
    base_url: str = "",
    institution_ids: list[str] = None,
    since: str = None,
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
        batch = []
        new_count = 0
        for work in results:
            oa_id = extract_openalex_id(work)
            doi = extract_doi(work)
            raw_hash = compute_hash(work)
            meta_hash = compute_meta_hash(work)
            batch.append(("openalex", oa_id, doi, Json(work), raw_hash, meta_hash))
            if existing_ids is not None and oa_id not in existing_ids:
                existing_ids.add(oa_id)
                new_count += 1

        # Insérer / mettre à jour
        updated_count = 0
        if batch:
            updated_count = insert_batch(conn, batch)
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

    def load_config(self, cur: Any) -> dict[str, Any]:
        institution_ids = get_extraction_api_ids(cur, "openalex")
        if not institution_ids:
            raise ExtractionConfigError(
                "aucun institution_id OpenAlex configuré "
                "(structures.api_ids->'openalex' vide pour le périmètre d'extraction)"
            )
        init_auth(api_key=get_openalex_api_key(cur), email=get_openalex_email(cur))
        return {
            "institution_ids": institution_ids,
            "base_url": get_api_base_urls(cur).get("openalex", "https://api.openalex.org/works"),
        }

    def setup_logging(self, args: argparse.Namespace, config: dict[str, Any]) -> None:
        self.logger.info(
            f"Institutions OpenAlex : {', '.join(config['institution_ids'])} (lineage OR)"
        )
        if args.since:
            self.logger.info(f"Mode incrémental : documents modifiés depuis {args.since}")

    def extract_all(
        self, args: argparse.Namespace, config: dict[str, Any], existing_ids: set
    ) -> ExtractionStats:
        with self.conn.cursor() as cur:
            config_years = get_years(cur, mode=args.mode)
        years = [args.year] if args.year else config_years
        if not args.since:
            self.logger.info(f"Années : {years}")

        stats = ExtractionStats()
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
