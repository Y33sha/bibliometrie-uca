"""
Extraction des thèses UCA depuis l'API theses.fr.

Usage:
    python extract_theses.py              # extraction complète (soutenues + en cours)
    python extract_theses.py --soutenues  # thèses soutenues uniquement
    python extract_theses.py --en-cours   # thèses en cours uniquement
    python extract_theses.py --dry-run    # compter sans insérer

L'API est interrogée via etabSoutenancePpn (identifiants IdRef de l'établissement).
UCA a deux IdRef successifs : 252404955 (2021-...) et 196200032 (2017-2020).
Les résultats bruts sont stockés dans staging (source='theses', JSONB).

L'identifiant unique est :
  - le NNT (numéro national de thèse) pour les thèses soutenues
  - l'id theses.fr (ex: "s367812") pour les thèses en cours (pas de NNT)
"""

import argparse
import os
import sys
import time

import requests
from psycopg2.extras import Json

from db.connection import get_connection
from infrastructure.sources.common import compute_hash, get_existing_ids, setup_logger
from infrastructure.api_limits import THESES_DELAY, THESES_PER_PAGE
from infrastructure.api_retry import http_request_with_retry
from infrastructure.app_config import get_api_base_urls, get_theses_etab_ppns

logger = setup_logger("extract_theses", os.path.join(os.path.dirname(__file__), "logs"))


def build_query(ppn: str, status: str | None = None) -> str:
    """Construit la chaîne de recherche pour l'API theses.fr."""
    q = f"etabSoutenancePpn:({ppn})"
    if status:
        q += f" AND status:({status})"
    return q


def fetch_page(base_url: str, query: str, debut: int = 0, nombre: int = 500) -> dict:
    """Récupère une page de résultats depuis l'API theses.fr (avec retry/backoff)."""
    params = {
        "q": query,
        "debut": debut,
        "nombre": nombre or THESES_PER_PAGE,
    }
    return http_request_with_retry(
        "GET", base_url, params=params, timeout=30, label=f"theses debut={debut}",
    )


def extract_theses_id(these: dict) -> str:
    """Extrait l'identifiant unique d'une thèse.

    - Thèse soutenue : NNT (ex: "2021UCFAC022")
    - Thèse en cours : id theses.fr (ex: "s367812")
    Les deux sont dans le champ 'id' de l'API recherche,
    et le NNT est aussi dans 'nnt' (null pour les en cours).
    """
    return these.get("id", "")


def extract_doi(these: dict) -> str | None:
    """Extrait le DOI si présent."""
    doi = these.get("doi")
    if doi and isinstance(doi, str) and doi.strip():
        return doi.strip()
    return None


def extract_ppn(
    ppn: str,
    conn,
    existing_ids: set,
    base_url: str,
    status: str | None = None,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """Extrait toutes les thèses d'un établissement (par PPN).

    Retourne (total, insérés, mis à jour).
    """
    query = build_query(ppn, status)
    status_label = status or "toutes"

    # Premier appel pour le total
    data = fetch_page(base_url, query, debut=0, nombre=1)
    total = data["totalHits"]
    logger.info(f"  PPN {ppn} ({status_label}) : {total} thèses")

    if dry_run or total == 0:
        return total, 0, 0

    inserted = 0
    updated = 0
    debut = 0
    per_page = THESES_PER_PAGE

    with conn.cursor() as cur:
        while debut < total:
            data = fetch_page(base_url, query, debut=debut, nombre=per_page)
            theses = data.get("theses", [])

            if not theses:
                break

            for these in theses:
                theses_id = extract_theses_id(these)
                if not theses_id:
                    continue

                doi = extract_doi(these)
                raw_hash = compute_hash(these)

                if theses_id in existing_ids:
                    # Mettre à jour si le hash a changé
                    cur.execute(
                        """
                        UPDATE staging
                        SET raw_data = %s, doi = %s, raw_hash = %s, last_seen_at = now(),
                            processed = CASE
                                WHEN raw_hash IS DISTINCT FROM %s THEN FALSE
                                ELSE processed
                            END
                        WHERE source = 'theses' AND source_id = %s
                          AND (raw_hash IS DISTINCT FROM %s)
                    """,
                        (Json(these), doi, raw_hash, raw_hash, theses_id, raw_hash),
                    )
                    if cur.rowcount:
                        updated += 1
                else:
                    cur.execute(
                        """
                        INSERT INTO staging (source, source_id, doi, raw_data, raw_hash)
                        VALUES ('theses', %s, %s, %s, %s)
                        ON CONFLICT (source, source_id) DO NOTHING
                    """,
                        (theses_id, doi, Json(these), raw_hash),
                    )
                    if cur.rowcount:
                        inserted += 1
                        existing_ids.add(theses_id)

            conn.commit()
            debut += len(theses)

            if debut % 1000 == 0 or debut >= total:
                logger.info(
                    f"    {debut}/{total} traités ({inserted} nouveaux, {updated} mis à jour)"
                )

            time.sleep(THESES_DELAY)

    return total, inserted, updated


def main():
    parser = argparse.ArgumentParser(description="Extraction theses.fr → staging")
    parser.add_argument("--soutenues", action="store_true", help="Thèses soutenues uniquement")
    parser.add_argument("--en-cours", action="store_true", help="Thèses en cours uniquement")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans insérer")
    args = parser.parse_args()

    # Déterminer les statuts à extraire
    if args.soutenues and args.en_cours:
        statuses = ["soutenue", "enCours"]
    elif args.soutenues:
        statuses = ["soutenue"]
    elif args.en_cours:
        statuses = ["enCours"]
    else:
        statuses = ["soutenue", "enCours"]

    conn = get_connection()
    cur = conn.cursor()
    ppns = get_theses_etab_ppns(cur)
    base_url = get_api_base_urls(cur).get("theses", "https://theses.fr/api/v1/theses/recherche/")
    cur.close()

    if not ppns:
        logger.error("Aucun PPN configuré (clé 'theses_etab_ppns' dans config)")
        conn.close()
        sys.exit(1)

    logger.info("=== Extraction theses.fr démarrée ===")
    logger.info(f"Établissements PPN : {ppns}")
    logger.info(f"Statuts : {statuses}")

    try:
        existing_ids = get_existing_ids(conn, "theses") if not args.dry_run else set()
        logger.info(f"{len(existing_ids)} thèses déjà en staging")

        grand_total = 0
        grand_inserted = 0
        grand_updated = 0

        for ppn in ppns:
            for status in statuses:
                total, inserted, updated = extract_ppn(
                    ppn, conn, existing_ids, base_url, status=status, dry_run=args.dry_run
                )
                grand_total += total
                grand_inserted += inserted
                grand_updated += updated

        logger.info("\n=== Terminé ===")
        logger.info(f"Total API : {grand_total}")
        logger.info(f"Nouveaux : {grand_inserted}")
        logger.info(f"Mis à jour : {grand_updated}")
        logger.info(f"En staging : {len(existing_ids)}")

    except requests.exceptions.HTTPError as e:
        logger.error(f"Erreur API : {e}")
        logger.error(f"Réponse : {e.response.text[:500] if e.response else 'N/A'}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.warning("Interruption — les données déjà insérées sont conservées.")
        sys.exit(0)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
