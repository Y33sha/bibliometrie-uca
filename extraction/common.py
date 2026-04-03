"""
Fonctions partagées par les scripts d'extraction (OpenAlex, HAL, WoS).
"""

import hashlib
import json
import logging
import os

from utils.doi import clean_doi  # noqa: F401 — réexporté pour les scripts d'extraction


def compute_hash(raw_data: dict) -> str:
    """Calcule le hash MD5 du JSON canonique (clés triées, compact)."""
    canonical = json.dumps(raw_data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


def get_existing_ids(conn, table: str, column: str) -> set:
    """Récupère les identifiants déjà en staging pour éviter les doublons.

    Paramètres validés contre une liste blanche pour éviter toute injection SQL.
    """
    allowed = {
        ("staging_openalex", "openalex_id"),
        ("staging_hal", "halid"),
        ("staging_wos", "ut"),
    }
    if (table, column) not in allowed:
        raise ValueError(f"Combinaison table/colonne non autorisée : {table}.{column}")

    with conn.cursor() as cur:
        cur.execute(f"SELECT {column} FROM {table}")
        return {row[0] for row in cur.fetchall()}


def setup_logger(name: str, log_dir: str) -> logging.Logger:
    """Configure un logger avec sortie console + fichier.

    Crée le répertoire de logs si nécessaire.
    """
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{name}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file),
        ],
    )
    return logging.getLogger(name)
