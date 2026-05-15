"""
Enrichissement du statut Open Access via l'API Unpaywall.

Pour les publications ayant un DOI, interroge Unpaywall et met à jour
le statut OA. Écrase les valeurs existantes, SAUF : ne remplace jamais
'diamond' par 'gold' (Unpaywall ne connaît pas le diamond OA).

L'orchestrateur dépend du port `EnrichQueries` ; le point d'entrée
CLI (argparse + connexion + rate limiter) est dans
`interfaces/cli/pipeline/enrich_oa_status.py`.

API: https://api.unpaywall.org/v2/{doi}?email=...
Rate limit: 100 000 req/jour, ~10 req/s recommandé
"""

import logging
import time

import requests
from sqlalchemy import Connection

from application.ports.pipeline.enrich import EnrichQueries
from application.ports.repositories.publication_repository import PublicationRepository

# Email requis par Unpaywall (politesse, pas d'auth)
UNPAYWALL_EMAIL = "bibliometrie@uca.fr"

# Mapping Unpaywall oa_status → notre enum oa_type
OA_MAP = {
    "gold": "gold",
    "hybrid": "hybrid",
    "bronze": "bronze",
    "green": "green",
    "closed": "closed",
}

BATCH_SIZE = 50


def fetch_oa_status(doi: str, logger: logging.Logger, *, unpaywall_base: str) -> str | None:
    """Interroge Unpaywall pour un DOI. Retourne le statut OA ou None."""
    for attempt in range(3):
        try:
            url = f"{unpaywall_base}/{doi}?email={UNPAYWALL_EMAIL}"
            resp = requests.get(url, timeout=10)

            if resp.status_code == 404:
                return None
            if resp.status_code == 429:
                wait = 5 * (attempt + 1)
                logger.warning(f"Rate limited, pause {wait}s (tentative {attempt + 1}/3)...")
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                logger.warning(f"  HTTP {resp.status_code} pour {doi}")
                return None

            data = resp.json()
            oa_status = data.get("oa_status")
            return OA_MAP.get(oa_status)

        except requests.RequestException as e:
            logger.warning(f"  Erreur réseau pour {doi}: {e}")
            return None

    logger.warning(f"  Échec après 3 tentatives pour {doi}")
    return None


def run_enrich(
    conn: Connection,
    queries: EnrichQueries,
    logger: logging.Logger,
    *,
    pub_repo: PublicationRepository,
    unpaywall_base: str,
    limit: int = 0,
    dry_run: bool = False,
    rate_delay: float = 0.1,
) -> None:
    pubs = queries.fetch_publications_with_doi(conn, limit=limit or None)
    total = len(pubs)
    logger.info(f"{total} publications avec DOI à vérifier sur Unpaywall")

    if not total:
        return

    updated = 0
    skipped = 0
    not_found = 0
    errors = 0

    for i, (pub_id, doi, current_status) in enumerate(pubs):
        if i > 0 and i % BATCH_SIZE == 0:
            if not dry_run:
                conn.commit()
            logger.info(
                f"  {i}/{total} — {updated} mis à jour, {skipped} inchangés, {not_found} non trouvés"
            )

        status = fetch_oa_status(doi, logger, unpaywall_base=unpaywall_base)

        if status:
            if current_status == "diamond" and status == "gold":
                skipped += 1
                time.sleep(rate_delay)
                continue

            if status == current_status:
                skipped += 1
                time.sleep(rate_delay)
                continue

            if dry_run:
                logger.info(f"  [DRY] {doi} : {current_status} → {status}")
            else:
                pub_repo.update_oa_status(pub_id, status)
            updated += 1
        elif status is None:
            not_found += 1
        else:
            errors += 1

        time.sleep(rate_delay)

    if not dry_run:
        conn.commit()

    logger.info(
        f"Terminé : {updated} mis à jour, {skipped} inchangés, "
        f"{not_found} non trouvés sur Unpaywall, {errors} erreurs"
    )
