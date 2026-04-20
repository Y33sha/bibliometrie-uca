"""
Extraction des publications depuis l'API Web of Science Expanded.

Usage:
    python extract_wos.py              # extraction complète 2022-2026
    python extract_wos.py --year 2024  # une seule année
    python extract_wos.py --dry-run    # compte les résultats sans insérer

L'API WoS est interrogée via le champ OG (Organization-Enhanced) + année.
Les résultats bruts sont stockés dans staging (JSONB).
Les records déjà présents (même UT) sont ignorés.

Query:  OG=(Universite Clermont Auvergne OR CHU Clermont Ferrand
            OR Polytechnic Institute of Clermont Auvergne)
        AND PY=<year>
"""

import argparse
import os
import time
from typing import Any

import requests
from psycopg2.extras import Json, execute_values

from infrastructure.api_limits import WOS_DELAY, WOS_PER_PAGE
from infrastructure.api_retry import http_request_with_retry
from infrastructure.app_config import (
    get_api_base_urls,
    get_extraction_api_ids,
    get_wos_api_key,
    get_years,
)
from infrastructure.sources.base import (
    ExtractionConfigError,
    ExtractionStats,
    SourceExtractor,
    run_extractor,
)
from infrastructure.sources.common import compute_hash, setup_logger

# ----- Logging -----
logger = setup_logger("extract_wos", os.path.join(os.path.dirname(__file__), "logs"))

# ----- Constantes techniques -----
BREATHER_EVERY = 10  # pause longue toutes les N pages
BREATHER_SECS = 15  # durée de la pause longue (secondes)

# Initialisées dans main() depuis la config DB
BASE_URL = ""
HEADERS: dict[str, str] = {}


def build_query(year: int, affiliations: list[str] | None = None) -> str:
    """Construit la requête WoS Advanced Search pour une année."""
    orgs = " OR ".join(affiliations or [])
    return f"OG=({orgs}) AND PY=({year})"


def extract_doi(rec: dict) -> str | None:
    """Extrait le DOI depuis les identifiants du record."""
    try:
        identifiers = (
            rec.get("dynamic_data", {})
            .get("cluster_related", {})
            .get("identifiers", {})
            .get("identifier", [])
        )
        # L'API retourne tantôt une liste, tantôt un dict unique
        if isinstance(identifiers, dict):
            identifiers = [identifiers]
        if not isinstance(identifiers, list):
            return None
        for ident in identifiers:
            if isinstance(ident, dict) and ident.get("type") == "doi":
                val = ident.get("value")
                return str(val).strip() if val is not None else None
    except (KeyError, TypeError, AttributeError):
        pass
    return None


def extract_ut(rec: dict) -> str:
    """Extrait le WoS UID (ex: WOS:000819841500009)."""
    return rec["UID"]


def _fetch_with_retry(url: str, params: dict, label: str = "") -> dict:
    """Requête GET avec retry (gère 429, body vide, erreurs réseau)."""
    return http_request_with_retry(
        "GET",
        url,
        params=params,
        headers=HEADERS,
        timeout=60,
        retry_on_empty_body=True,
        initial_backoff=2.0,  # WoS plus conservateur
        label=label,
    )


def fetch_page(year: int, first_record: int) -> dict:
    """Récupère une page de résultats via une requête de recherche complète.

    Note : la pagination via queryId ne fonctionne pas de façon fiable
    (réponses vides), on refait une recherche avec firstRecord à chaque page.
    """
    params = {
        "databaseId": "WOS",
        "usrQuery": build_query(year),
        "count": WOS_PER_PAGE,
        "firstRecord": first_record,
    }
    return _fetch_with_retry(BASE_URL, params, label=f"({year}, rec {first_record})")


def get_records(data: dict) -> list[dict]:
    """Extrait la liste de records depuis la réponse API."""
    try:
        return data["Data"]["Records"]["records"]["REC"]
    except (KeyError, TypeError):
        return []


def get_records_found(data: dict) -> int:
    """Extrait le nombre total de records trouvés."""
    try:
        return data["QueryResult"]["RecordsFound"]
    except (KeyError, TypeError):
        return 0


def get_existing_uts(conn: Any) -> set:
    """Récupère les UT déjà en base pour éviter les doublons."""
    from infrastructure.sources.common import get_existing_ids

    return get_existing_ids(conn, "wos")


def insert_batch(conn: Any, batch: list[tuple]) -> Any:
    """Insère un batch de records dans staging.
    Si le record existe et le hash a changé, met à jour raw_data et remet processed = FALSE.
    """
    query = """
        INSERT INTO staging (source, source_id, doi, raw_data, raw_hash)
        VALUES %s
        ON CONFLICT (source, source_id) DO UPDATE SET
            raw_data = CASE
                WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN EXCLUDED.raw_data ELSE staging.raw_data END,
            raw_hash = COALESCE(EXCLUDED.raw_hash, staging.raw_hash),
            processed = CASE
                WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN FALSE ELSE staging.processed END,
            last_seen_at = now()
    """
    with conn.cursor() as cur:
        execute_values(cur, query, batch, template="(%s, %s, %s, %s::jsonb, %s)")
    conn.commit()


def extract_year(year: int, conn: Any, existing_uts: set, dry_run: bool = False) -> int:
    """Extrait toutes les publications d'une année. Retourne le nb insérés."""
    logger.info(f"Requête WoS : {build_query(year)}")

    # Premier appel
    time.sleep(WOS_DELAY)
    data = fetch_page(year, 1)
    if not data:
        logger.error(f"Impossible d'exécuter la requête pour {year}")
        return 0

    total_count = get_records_found(data)
    logger.info(f"Année {year} : {total_count} records trouvés")

    if dry_run or total_count == 0:
        return 0

    total_inserted = 0
    first_record = 1
    consecutive_failures = 0

    while first_record <= total_count:
        # Première page déjà récupérée
        if first_record > 1:
            time.sleep(WOS_DELAY)
            data = fetch_page(year, first_record)

        records = get_records(data)
        if not records:
            consecutive_failures += 1
            if consecutive_failures >= 3:
                logger.error(
                    f"3 pages vides consécutives à firstRecord={first_record}, "
                    f"arrêt de l'année {year}"
                )
                break
            logger.warning(
                f"Page vide à firstRecord={first_record}, nouvelle tentative après pause..."
            )
            time.sleep(5)
            continue

        consecutive_failures = 0

        # Préparer le batch
        batch = []
        for rec in records:
            ut = extract_ut(rec)
            doi = extract_doi(rec)
            h = compute_hash(rec)
            batch.append(("wos", ut, doi, Json(rec), h))
            existing_uts.add(ut)

        # Insérer
        if batch:
            insert_batch(conn, batch)
            total_inserted += len(batch)

        page_num = (first_record - 1) // WOS_PER_PAGE + 1
        logger.info(
            f"  Page {page_num} : {len(records)} records, "
            f"{len(batch)} insérés "
            f"({min(first_record + len(records) - 1, total_count)}/{total_count})"
        )

        first_record += len(records)

        # Pause longue toutes les N pages pour laisser l'API souffler
        if page_num % BREATHER_EVERY == 0 and first_record <= total_count:
            logger.info(f"  Pause de {BREATHER_SECS}s (toutes les {BREATHER_EVERY} pages)...")
            time.sleep(BREATHER_SECS)

        # Limite API : firstRecord ne peut pas dépasser 100 000
        if first_record > 100_000:
            logger.warning(
                "Limite API atteinte (100 000 records). "
                "Réduire la requête si des résultats manquent."
            )
            break

    logger.info(
        f"Année {year} terminée : {total_inserted} records insérés sur {total_count} trouvés"
    )
    return total_inserted


def log_remaining_quota(resp_headers: dict) -> Any:
    """Log les quotas restants si disponibles dans les headers."""
    remaining = resp_headers.get("X-REC-AmtPerYear-Remaining")
    if remaining:
        logger.info(f"Quota annuel restant : {remaining} records")


class WosExtractor(SourceExtractor):
    SOURCE = "wos"
    DESCRIPTION = "Extraction WoS → staging"

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--year", type=int, help="Année spécifique (sinon toutes)")
        parser.add_argument(
            "--mode", choices=["full", "weekly"], default="full", help="Mode (défaut: full)"
        )

    def load_config(self, cur: Any) -> dict[str, Any]:
        global BASE_URL, HEADERS
        affiliations = get_extraction_api_ids(cur, "wos")
        if not affiliations:
            raise ExtractionConfigError(
                "aucune affiliation WoS configurée "
                "(structures.api_ids->'wos' vide pour le périmètre d'extraction)"
            )
        api_key = get_wos_api_key(cur)
        BASE_URL = get_api_base_urls(cur).get("wos", "https://api.clarivate.com/api/wos")
        HEADERS = {"X-ApiKey": api_key, "Accept": "application/json"}
        return {
            "affiliations": affiliations,
            "base_url": BASE_URL,
        }

    def setup_logging(self, args: argparse.Namespace, config: dict[str, Any]) -> None:
        self.logger.info(f"Affiliations : {config['affiliations']}")
        # Vérifier le quota
        try:
            test_resp = requests.get(
                config["base_url"],
                headers=HEADERS,
                params={
                    "databaseId": "WOS",
                    "usrQuery": "OG=(test)",
                    "count": "0",
                    "firstRecord": "1",
                },
                timeout=30,
            )
            if test_resp.status_code == 200:
                remaining = test_resp.headers.get("X-REC-AmtPerYear-Remaining")
                if remaining:
                    self.logger.info(f"Quota annuel restant : {remaining} records")
            elif test_resp.status_code in (401, 403):
                self.logger.error(
                    f"Erreur d'authentification ({test_resp.status_code}). Vérifier la clé API."
                )
                self.logger.error(f"Réponse : {test_resp.text[:300]}")
                raise SystemExit(1)
        except requests.RequestException as e:
            self.logger.warning(f"Impossible de vérifier le quota : {e}")

    def extract_all(
        self, args: argparse.Namespace, config: dict[str, Any], existing_ids: set
    ) -> ExtractionStats:
        with self.conn.cursor() as cur:
            config_years = get_years(cur, mode=args.mode)
        years = [args.year] if args.year else config_years
        self.logger.info(f"Années : {years}")

        stats = ExtractionStats()
        for i, year in enumerate(years):
            try:
                inserted = extract_year(year, self.conn, existing_ids, dry_run=args.dry_run)
                stats.add(new=inserted)
            except Exception as e:
                self.logger.error(f"Erreur sur l'année {year} : {e} — passage à la suivante")
            if i < len(years) - 1:
                self.logger.info("Pause de 30s avant l'année suivante...")
                time.sleep(30)
        return stats

    def log_summary(self, stats: ExtractionStats, args: argparse.Namespace) -> None:
        self.logger.info(f"=== Terminé : {stats.new} records insérés au total ===")


def main() -> None:
    run_extractor(WosExtractor, logger)


if __name__ == "__main__":
    main()
