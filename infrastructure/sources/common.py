"""
Fonctions partagées par les scripts d'extraction (OpenAlex, HAL, WoS, ScanR).
"""

import hashlib
import json
from typing import Any

from domain.publication import clean_doi  # noqa: F401 — réexporté pour les scripts d'extraction
from infrastructure.log import setup_logger  # noqa: F401 — réexporté pour les scripts d'extraction


def compute_hash(raw_data: dict) -> str:
    """Calcule le hash MD5 du JSON canonique (clés triées, compact)."""
    canonical = json.dumps(raw_data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


from domain.sources import ALL_SOURCES_SET as VALID_SOURCES


def get_cross_import_dois(conn: Any, target: str, all_staged: bool = False) -> list[str]:
    """Retourne les DOI présents dans les autres sources staging mais absents de la cible.

    Comparaison directe sur `doi` : tous les DOIs sont stockés en minuscules
    (cf. `domain.publication._normalize_doi`), donc plus besoin d'un cas
    spécial par source. Préserve l'utilisation de l'index btree `idx_staging_doi`.

    Args:
        conn: connexion psycopg3
        target: clé source cible (hal, openalex, wos, scanr)
        all_staged: si False, ne considère que les documents non normalisés (processed=FALSE)
    """
    if target not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {target}. Valides : {', '.join(VALID_SOURCES)}")

    processed_filter = "" if all_staged else " AND processed = FALSE"

    query = f"""
        SELECT DISTINCT doi FROM staging
        WHERE source != %s AND doi IS NOT NULL{processed_filter}
          AND doi NOT IN (
              SELECT doi FROM staging WHERE source = %s AND doi IS NOT NULL
          )
        ORDER BY doi
    """

    with conn.cursor() as cur:
        cur.execute(query, (target, target))
        return [row["doi"] for row in cur.fetchall()]


def get_existing_ids(conn: Any, source: str) -> set:
    """Récupère les source_id déjà en staging pour une source donnée."""
    if source not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {source}. Valides : {', '.join(VALID_SOURCES)}")

    with conn.cursor() as cur:
        cur.execute("SELECT source_id FROM staging WHERE source = %s", (source,))
        return {row["source_id"] for row in cur.fetchall()}
