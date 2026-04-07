"""
Fonctions partagées par les scripts d'extraction (OpenAlex, HAL, WoS).
"""

import hashlib
import json
import os

from utils.doi import clean_doi  # noqa: F401 — réexporté pour les scripts d'extraction
from utils.log import setup_logger  # noqa: F401 — réexporté pour les scripts d'extraction


def compute_hash(raw_data: dict) -> str:
    """Calcule le hash MD5 du JSON canonique (clés triées, compact)."""
    canonical = json.dumps(raw_data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


# Registre des tables staging avec leur colonne DOI
STAGING_SOURCES = {
    "hal":       "staging_hal",
    "openalex":  "staging_openalex",
    "wos":       "staging_wos",
    "scanr":     "staging_scanr",
}


def get_cross_import_dois(conn, target: str, all_staged: bool = False) -> list[str]:
    """Retourne les DOI présents dans les autres sources staging mais absents de la cible.

    Args:
        conn: connexion psycopg2
        target: clé source cible (hal, openalex, wos, scanr)
        all_staged: si False, ne considère que les documents non normalisés (processed=FALSE)
    """
    if target not in STAGING_SOURCES:
        raise ValueError(f"Source inconnue : {target}. Valides : {', '.join(STAGING_SOURCES)}")

    target_table = STAGING_SOURCES[target]
    other_tables = [t for k, t in STAGING_SOURCES.items() if k != target]

    processed_filter = "" if all_staged else " AND processed = FALSE"

    # UNION des DOI des autres sources
    unions = "\nUNION\n".join(
        f"SELECT doi FROM {table} WHERE doi IS NOT NULL{processed_filter}"
        for table in other_tables
    )

    # ScanR stocke les DOI en casse variable → comparaison case-insensitive
    if target == "scanr":
        exclude = f"SELECT lower(doi) FROM {target_table} WHERE doi IS NOT NULL"
        query = f"""
            SELECT DISTINCT doi FROM (
                {unions}
            ) src
            WHERE lower(doi) NOT IN ({exclude})
            ORDER BY doi
        """
    else:
        exclude = f"SELECT doi FROM {target_table} WHERE doi IS NOT NULL"
        query = f"""
            SELECT DISTINCT doi FROM (
                {unions}
            ) src
            WHERE doi NOT IN ({exclude})
            ORDER BY doi
        """

    with conn.cursor() as cur:
        cur.execute(query)
        return [row[0] for row in cur.fetchall()]


def get_existing_ids(conn, table: str, column: str) -> set:
    """Récupère les identifiants déjà en staging pour éviter les doublons.

    Paramètres validés contre une liste blanche pour éviter toute injection SQL.
    """
    allowed = {
        ("staging_openalex", "openalex_id"),
        ("staging_hal", "halid"),
        ("staging_wos", "ut"),
        ("staging_scanr", "scanr_id"),
    }
    if (table, column) not in allowed:
        raise ValueError(f"Combinaison table/colonne non autorisée : {table}.{column}")

    with conn.cursor() as cur:
        cur.execute(f"SELECT {column} FROM {table}")
        return {row[0] for row in cur.fetchall()}
