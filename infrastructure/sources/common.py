"""
Fonctions partagées par les scripts d'extraction (OpenAlex, HAL, WoS, ScanR).
"""

import hashlib
import json

from sqlalchemy import Connection, text

from domain.publication import clean_doi  # noqa: F401 — réexporté pour les scripts d'extraction
from domain.sources import ALL_SOURCES_SET as VALID_SOURCES
from infrastructure.observability.log import (
    setup_logger,  # noqa: F401 — réexporté pour les scripts d'extraction
)


def compute_hash(raw_data: dict) -> str:
    """Calcule le hash MD5 du JSON canonique (clés triées, compact)."""
    canonical = json.dumps(raw_data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


# Mapping `target source → RA attendue côté doi_prefixes`. Pour ces sources,
# on filtre les DOIs candidats sur leur préfixe : un DOI non-Crossref n'a rien
# à faire dans un appel API Crossref (404 garanti, pollution `not_found=TRUE`).
# La valeur NULL côté `doi_prefixes.ra` est acceptée — préfixe pas encore
# résolu par la phase `resolve_doi_prefixes`, on tente quand même en best-effort.
# Sources absentes du mapping (hal, openalex, wos, scanr) : aucun filtre RA,
# ces APIs cherchent par DOI sans contrainte de registrar.
_TARGET_RA: dict[str, str] = {
    "crossref": "Crossref",
}


def get_cross_import_dois(conn: Connection, target: str, all_staged: bool = False) -> list[str]:
    """Retourne les DOI présents dans les autres sources staging mais absents de la cible.

    Comparaison directe sur `doi` : tous les DOIs sont stockés en minuscules
    (cf. `domain.publication._normalize_doi`), donc plus besoin d'un cas
    spécial par source. Préserve l'utilisation de l'index btree `idx_staging_doi`.

    Pour les cibles présentes dans `_TARGET_RA`, ajoute un LEFT JOIN sur
    `doi_prefixes` pour filtrer les DOIs dont la RA résolue ne correspond
    pas (les NULL — préfixe pas encore résolu — sont conservés).

    Args:
        conn: `Connection` SA ou cur psycopg.
        target: clé source cible (hal, openalex, wos, scanr, crossref)
        all_staged: si False, ne considère que les documents non normalisés (processed=FALSE)
    """
    if target not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {target}. Valides : {', '.join(VALID_SOURCES)}")

    target_ra = _TARGET_RA.get(target)
    processed_filter = "" if all_staged else " AND s.processed = FALSE"
    join_clause = (
        "LEFT JOIN doi_prefixes dp ON dp.prefix = split_part(s.doi, '/', 1)" if target_ra else ""
    )

    if isinstance(conn, Connection):
        prefix_filter = " AND (dp.ra = :target_ra OR dp.ra IS NULL)" if target_ra else ""
        query = f"""
            SELECT DISTINCT s.doi
            FROM staging s
            {join_clause}
            WHERE s.source != :target
              AND s.doi IS NOT NULL{processed_filter}{prefix_filter}
              AND s.doi NOT IN (
                  SELECT doi FROM staging WHERE source = :target AND doi IS NOT NULL
              )
            ORDER BY s.doi
        """
        params: dict[str, str] = {"target": target}
        if target_ra:
            params["target_ra"] = target_ra
        return list(conn.execute(text(query), params).scalars())

    pg_prefix_filter = " AND (dp.ra = %s OR dp.ra IS NULL)" if target_ra else ""
    query_pg = f"""
        SELECT DISTINCT s.doi
        FROM staging s
        {join_clause}
        WHERE s.source != %s
          AND s.doi IS NOT NULL{processed_filter}{pg_prefix_filter}
          AND s.doi NOT IN (
              SELECT doi FROM staging WHERE source = %s AND doi IS NOT NULL
          )
        ORDER BY s.doi
    """
    pg_params = (target, target_ra, target) if target_ra else (target, target)
    with conn.cursor() as cur:
        cur.execute(query_pg, pg_params)
        return [row["doi"] for row in cur.fetchall()]


def get_existing_ids(conn: Connection, source: str) -> set:
    """Récupère les source_id déjà en staging pour une source donnée."""
    if source not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {source}. Valides : {', '.join(VALID_SOURCES)}")

    if isinstance(conn, Connection):
        return set(
            conn.execute(
                text("SELECT source_id FROM staging WHERE source = :src"), {"src": source}
            ).scalars()
        )

    with conn.cursor() as cur:
        cur.execute("SELECT source_id FROM staging WHERE source = %s", (source,))
        return {row["source_id"] for row in cur.fetchall()}
