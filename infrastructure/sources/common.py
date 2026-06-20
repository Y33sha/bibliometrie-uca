"""
Fonctions partagées par les scripts d'extraction (OpenAlex, HAL, WoS, ScanR).
"""

import hashlib
import json
from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from domain.publications.identifiers import (
    clean_doi,  # noqa: F401 — réexporté pour les scripts d'extraction
)
from domain.sources.registry import ALL_SOURCES_SET as VALID_SOURCES
from infrastructure.observability.log import (
    setup_logger,  # noqa: F401 — réexporté pour les scripts d'extraction
)


def canonical_json_bytes(raw_data: dict) -> bytes:
    """Sérialise un payload en JSON canonique (clés triées, compact, UTF-8).

    Forme unique partagée par `compute_hash` (empreinte du payload) et le raw
    store (contenu écrit) : garantit `md5(canonical_json_bytes(d)) ==
    compute_hash(d)`, donc le hash du contenu raw store égale `staging.raw_hash`.
    """
    return json.dumps(raw_data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def compute_hash(raw_data: dict) -> str:
    """Calcule le hash MD5 du JSON canonique (clés triées, compact)."""
    return hashlib.md5(canonical_json_bytes(raw_data)).hexdigest()


_UPSERT_STAGING_SQL = text(
    """
    WITH old AS (
        SELECT raw_hash AS old_hash FROM staging
        WHERE source = :source AND source_id = :source_id
    )
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash)
    VALUES (:source, :source_id, :doi, :raw_data, :raw_hash)
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
    RETURNING (xmax = 0) AS inserted,
              ((SELECT old_hash FROM old) IS DISTINCT FROM :raw_hash) AS changed
    """
).bindparams(bindparam("raw_data", type_=JSONB))


def upsert_staging(
    conn: Connection,
    *,
    source: str,
    source_id: str,
    doi: str | None,
    raw_data: dict[str, Any],
) -> tuple[bool, bool]:
    """UPSERT canonique d'une ligne `staging`, partagé par toutes les sources bulk.

    `INSERT … ON CONFLICT (source, source_id) DO UPDATE` piloté par `raw_hash` :
    réécrit `raw_data` (et repasse `processed=FALSE`) seulement si le hash a changé,
    bumpe toujours `last_seen_at`. Un `raw_hash=null` en base force le re-import
    (`NULL IS DISTINCT FROM <hash>`). Le hash est calculé ici via `compute_hash`.

    Retourne `(inserted, changed)` : `inserted` = vraie insertion (`xmax = 0`),
    `changed` = contenu réécrit (hash distinct de l'ancien). Le commit est à la
    charge de l'appelant.
    """
    row = conn.execute(
        _UPSERT_STAGING_SQL,
        {
            "source": source,
            "source_id": source_id,
            "doi": doi,
            "raw_data": raw_data,
            "raw_hash": compute_hash(raw_data),
        },
    ).one()
    return (bool(row.inserted), bool(row.changed))


# Mapping `target source → RA attendue côté doi_prefixes`. Pour ces sources,
# on filtre les DOIs candidats sur leur préfixe : un DOI non-Crossref n'a rien
# à faire dans un appel API Crossref (404 garanti, pollution `not_found_at`).
# La valeur NULL côté `doi_prefixes.ra` est acceptée — préfixe pas encore
# résolu par la phase `resolve_doi_prefixes`, on tente quand même en best-effort.
# Sources absentes du mapping (hal, openalex, wos, scanr) : aucun filtre RA,
# ces APIs cherchent par DOI sans contrainte de registrar.
_TARGET_RA: dict[str, str] = {
    "crossref": "Crossref",
    "datacite": "DataCite",
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

STALE_REFRESH_AFTER_DAYS = 90
"""Âge (jours) de `staging.last_seen_at` au-delà duquel une row est refetchée.

La phase « refresh stale » (fin de cross-import, à chaque run) refetche par id
natif les rows dont `last_seen_at < now() - STALE_REFRESH_AFTER_DAYS` : trouvé
→ bump `last_seen_at` + refresh `raw_data` ; 404 → `disappeared_at`. Tournant à
chaque run, le seuil étale la charge (chaque passe ne ramasse que ce qui vient
de franchir le délai) sans `LIMIT`.

Même nature que [`DOI_LOOKUP_RETRY_DAYS`] : politique de fraîcheur du pipeline,
pas une règle métier — d'où sa place ici et non dans `domain/`.
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


_STALE_DOIS_SQL = text(
    """
    SELECT DISTINCT doi
    FROM staging
    WHERE source = CAST(:source AS source_type)
      AND doi IS NOT NULL
      AND not_found_at IS NULL
      AND disappeared_at IS NULL
      AND last_seen_at < now() - make_interval(days => :days)
    ORDER BY doi
    """
)

_SET_DISAPPEARED_SQL = text(
    """
    UPDATE staging SET disappeared_at = now()
    WHERE source = CAST(:source AS source_type) AND doi = :doi
      AND disappeared_at IS NULL AND not_found_at IS NULL
    """
)

_MARK_UNDISCOVERABLE_STALE_SQL = text(
    """
    UPDATE staging SET disappeared_at = now()
    WHERE doi IS NULL
      AND not_found_at IS NULL
      AND disappeared_at IS NULL
      AND last_seen_at < now() - make_interval(days => :days)
    """
)


def get_stale_dois(conn: Connection, source: str) -> list[str]:
    """DOI des rows `source` à `last_seen_at` ancien (> STALE_REFRESH_AFTER_DAYS).

    Sert de `reader` à `run_async` pour la phase refresh : ces DOI seront
    refetchés par l'adapter de la source. Exclut les stubs not-found et les
    rows déjà marquées disparues.
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {source}. Valides : {', '.join(VALID_SOURCES)}")
    return list(
        conn.execute(
            _STALE_DOIS_SQL, {"source": source, "days": STALE_REFRESH_AFTER_DAYS}
        ).scalars()
    )


def set_disappeared_by_doi(conn: Connection, source: str, doi: str) -> None:
    """Marque `disappeared_at` sur la row `(source, doi)` confirmée absente.

    Appelé par la phase refresh quand le refetch d'un DOI stale renvoie un
    404 confirmé (sentinelle). Ne commit pas — l'appelant s'en charge.
    """
    conn.execute(_SET_DISAPPEARED_SQL, {"source": source, "doi": doi})


def mark_undiscoverable_stale_disappeared(conn: Connection) -> int:
    """Marque disparues les rows stale **sans DOI** (non refetchables).

    Ces rows ne peuvent pas être refetchées par DOI ; comme leur source est
    re-moissonnée par le bulk, rester stale > STALE_REFRESH_AFTER_DAYS signifie
    qu'elles ont vraiment disparu. Retourne le nombre de rows marquées.
    Ne commit pas — l'appelant s'en charge.
    """
    result = conn.execute(_MARK_UNDISCOVERABLE_STALE_SQL, {"days": STALE_REFRESH_AFTER_DAYS})
    return result.rowcount


def get_cross_import_dois(conn: Connection, target: str) -> list[str]:
    """Retourne les DOI présents dans les autres sources mais absents de la cible.

    Pool = `staging.doi` (DOI primaire) ∪ `source_publications.external_ids.related_dois`
    (DOI secondaires : preprint/dépôt/édition). Les related_dois proviennent des
    source_publications normalisés (runs précédents) : ceux d'un record fraîchement
    ingéré ne sont pas encore normalisés au moment du cross_imports et sont rattrapés
    au run suivant — bénin (le pipeline est convergent).

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
        "LEFT JOIN doi_prefixes dp ON dp.prefix = split_part(c.doi, '/', 1)" if target_ra else ""
    )
    # Pool de DOI candidats : primaires (staging.doi) + secondaires (related_dois
    # des source_publications normalisés). Partagé par les deux branches.
    candidates_cte = """
        WITH candidates AS (
            SELECT s.doi
            FROM staging s
            WHERE s.source != {t} AND s.doi IS NOT NULL
            UNION
            SELECT d AS doi
            FROM source_publications sp
            CROSS JOIN LATERAL
                jsonb_array_elements_text(sp.external_ids->'related_dois') AS d
            WHERE sp.source != {t}
              AND jsonb_typeof(sp.external_ids->'related_dois') = 'array'
        )
    """

    if isinstance(conn, Connection):
        prefix_filter = " AND (dp.ra = :target_ra OR dp.ra IS NULL)" if target_ra else ""
        query = f"""
            {candidates_cte.format(t=":target")}
            SELECT DISTINCT c.doi
            FROM candidates c
            {join_clause}
            WHERE c.doi NOT IN (
                      SELECT doi FROM staging WHERE source = :target AND doi IS NOT NULL
                  ){prefix_filter}
              AND NOT EXISTS (
                  SELECT 1 FROM doi_lookups l
                  WHERE l.source = :target AND l.doi = c.doi AND l.next_retry > now()
              )
            ORDER BY c.doi
        """
        params: dict[str, str] = {"target": target}
        if target_ra:
            params["target_ra"] = target_ra
        return list(conn.execute(text(query), params).scalars())

    pg_prefix_filter = " AND (dp.ra = %(target_ra)s OR dp.ra IS NULL)" if target_ra else ""
    query_pg = f"""
        {candidates_cte.format(t="%(target)s")}
        SELECT DISTINCT c.doi
        FROM candidates c
        {join_clause}
        WHERE c.doi NOT IN (
                  SELECT doi FROM staging WHERE source = %(target)s AND doi IS NOT NULL
              ){pg_prefix_filter}
          AND NOT EXISTS (
              SELECT 1 FROM doi_lookups l
              WHERE l.source = %(target)s AND l.doi = c.doi AND l.next_retry > now()
          )
        ORDER BY c.doi
    """
    pg_params = {"target": target, "target_ra": target_ra} if target_ra else {"target": target}
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
