"""
Fonctions partagées par les scripts d'extraction (OpenAlex, HAL, WoS, ScanR).
"""

import hashlib
import json

from sqlalchemy import Connection, text

from domain.publications.identifiers import (
    clean_doi,  # noqa: F401 — réexporté pour les scripts d'extraction
)
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
# à faire dans un appel API Crossref (404 garanti, pollution `not_found_at`).
# La valeur NULL côté `doi_prefixes.ra` est acceptée — préfixe pas encore
# résolu par la phase `resolve_doi_prefixes`, on tente quand même en best-effort.
# Sources absentes du mapping (hal, openalex, wos, scanr) : aucun filtre RA,
# ces APIs cherchent par DOI sans contrainte de registrar.
_TARGET_RA: dict[str, str] = {
    "crossref": "Crossref",
}


DOI_LOOKUP_RETRY_DAYS = 30
"""Délai (jours) avant de re-tenter un DOI introuvable sur une source non native.

Un DOI absent d'une source *autre que sa source native* n'est pas
définitivement absent : la source peut l'indexer plus tard. On mémorise le
miss dans `doi_lookups` avec `next_retry = now() + DOI_LOOKUP_RETRY_DAYS`,
ce qui borne le pool de re-tentatives — sans ce backoff, ces DOI seraient
réinterrogés à chaque run (coût API non borné, croissant avec le temps).

Vit ici (infrastructure) et non dans `domain/` : c'est une politique du
pipeline d'extraction, pas une règle métier du domaine.
"""

_RECORD_DOI_NOT_FOUND_SQL = text(
    """
    INSERT INTO doi_lookups (source, doi, not_found_at, next_retry)
    VALUES (CAST(:source AS source_type), :doi, now(), now() + make_interval(days => :days))
    ON CONFLICT (source, doi) DO UPDATE SET
        not_found_at = now(),
        next_retry = now() + make_interval(days => :days)
    """
)


def record_doi_not_found(conn: Connection, source: str, doi: str) -> None:
    """Mémorise (ou ré-arme) un miss cross-import dans `doi_lookups`.

    Appelé par les adapters `fetch_missing_doi` non natifs (hal, openalex,
    wos, scanr) quand un DOI cherché est absent de la source. Le miss est
    temporaire : `next_retry` repousse la prochaine tentative de
    `DOI_LOOKUP_RETRY_DAYS` jours. Ne commit pas — l'appelant s'en charge.
    """
    conn.execute(
        _RECORD_DOI_NOT_FOUND_SQL,
        {"source": source, "doi": doi, "days": DOI_LOOKUP_RETRY_DAYS},
    )


def get_cross_import_dois(conn: Connection, target: str) -> list[str]:
    """Retourne les DOI présents dans les autres sources staging mais absents de la cible.

    Comparaison directe sur `doi` : tous les DOIs sont stockés en minuscules
    (cf. `domain.publication._normalize_doi`), donc plus besoin d'un cas
    spécial par source. Préserve l'utilisation de l'index btree `idx_staging_doi`.

    Exclut les DOI en backoff dans `doi_lookups` (miss cross-import récent
    sur la cible dont `next_retry` n'est pas encore atteint). Le pool est
    ainsi auto-borné et convergent : 1er pass tente tout, les misses reçoivent
    un `next_retry`, les passes suivantes ne retentent que les DOI dont le
    délai est écoulé.

    Pour les cibles présentes dans `_TARGET_RA`, ajoute un LEFT JOIN sur
    `doi_prefixes` pour filtrer les DOIs dont la RA résolue ne correspond
    pas (les NULL — préfixe pas encore résolu — sont conservés).

    Args:
        conn: `Connection` SA ou cur psycopg.
        target: clé source cible (hal, openalex, wos, scanr, crossref)
    """
    if target not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {target}. Valides : {', '.join(VALID_SOURCES)}")

    target_ra = _TARGET_RA.get(target)
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
              AND s.doi IS NOT NULL{prefix_filter}
              AND s.doi NOT IN (
                  SELECT doi FROM staging WHERE source = :target AND doi IS NOT NULL
              )
              AND NOT EXISTS (
                  SELECT 1 FROM doi_lookups l
                  WHERE l.source = :target AND l.doi = s.doi AND l.next_retry > now()
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
          AND s.doi IS NOT NULL{pg_prefix_filter}
          AND s.doi NOT IN (
              SELECT doi FROM staging WHERE source = %s AND doi IS NOT NULL
          )
          AND NOT EXISTS (
              SELECT 1 FROM doi_lookups l
              WHERE l.source = %s AND l.doi = s.doi AND l.next_retry > now()
          )
        ORDER BY s.doi
    """
    pg_params = (target, target_ra, target, target) if target_ra else (target, target, target)
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
