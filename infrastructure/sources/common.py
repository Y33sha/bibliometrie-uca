"""
Fonctions partagées par les scripts d'extraction (OpenAlex, HAL, WoS, ScanR).
"""

import hashlib
import json
from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from domain.publications.identifiers import clean_doi  # utilisé ici + réexporté pour l'extraction
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
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, authors_truncated, entry_mode)
    VALUES (:source, :source_id, :doi, :raw_data, :raw_hash, :authors_truncated, :entry_mode)
    ON CONFLICT (source, source_id) DO UPDATE SET
        raw_data = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN EXCLUDED.raw_data
            ELSE staging.raw_data
        END,
        raw_hash = COALESCE(EXCLUDED.raw_hash, staging.raw_hash),
        -- Renseigne le DOI quand la ligne existait sans (doc moissonné avant que la
        -- source ne porte le DOI) ; ne clobbe jamais un DOI déjà posé.
        doi = COALESCE(staging.doi, EXCLUDED.doi),
        processed = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN FALSE
            ELSE staging.processed
        END,
        -- Suit `raw_hash` comme `processed` : un payload bulk inchangé n'écrase pas
        -- le flag (préserve l'effacement posé par refetch_truncated) ; un payload
        -- modifié le recalcule depuis le nouveau contenu.
        authors_truncated = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN EXCLUDED.authors_truncated
            ELSE staging.authors_truncated
        END,
        -- `entry_mode` n'est PAS réécrit : il garde la provenance de première création.
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
    authors_truncated: bool = False,
    entry_mode: str = "bulk",
) -> tuple[bool, bool]:
    """UPSERT canonique d'une ligne `staging`, partagé par toutes les voies d'entrée
    (extraction bulk **et** cross-import — un seul endroit pour la logique d'UPSERT).

    `INSERT … ON CONFLICT (source, source_id) DO UPDATE` piloté par `raw_hash` :
    réécrit `raw_data` (et repasse `processed=FALSE`) seulement si le hash a changé,
    bumpe toujours `last_seen_at`, et renseigne `doi` s'il manquait (jamais d'écrasement).
    Un `raw_hash=null` en base force le re-import (`NULL IS DISTINCT FROM <hash>`).
    Le hash est calculé ici via `compute_hash`.

    `authors_truncated` (OpenAlex : payload bulk plafonné à 100 auteurs) suit la même
    logique que `processed` — (re)posé seulement quand le hash change, sinon préservé
    (n'écrase pas l'effacement de `refetch_truncated`). Les sources non plafonnées
    laissent le défaut `False`.

    `entry_mode` enregistre comment la ligne est **entrée** (`bulk` à l'extraction,
    `cross_import_doi` / `cross_import_hal` au cross-import) ; posé à la création,
    jamais réécrit (provenance d'origine).

    Retourne `(inserted, changed)` : `inserted` = vraie insertion (`xmax = 0`),
    `changed` = contenu réécrit (hash distinct de l'ancien). Le commit est à la
    charge de l'appelant.
    """
    row = conn.execute(
        _UPSERT_STAGING_SQL,
        {
            "source": source,
            "source_id": source_id,
            "doi": clean_doi(doi),
            "raw_data": raw_data,
            "raw_hash": compute_hash(raw_data),
            "authors_truncated": authors_truncated,
            "entry_mode": entry_mode,
        },
    ).one()
    return (bool(row.inserted), bool(row.changed))


_NOT_FOUND_STUB_TEMPLATE = """
    INSERT INTO staging (source, source_id, doi, raw_data, not_found_at, processed, entry_mode)
    VALUES (:source, :source_id, :doi, '{}'::jsonb, now(), TRUE, :entry_mode)
    ON CONFLICT (source, source_id) DO __ON_CONFLICT__
"""
_NOT_FOUND_STUB_DO_NOTHING = text(_NOT_FOUND_STUB_TEMPLATE.replace("__ON_CONFLICT__", "NOTHING"))
_NOT_FOUND_STUB_REARM = text(
    _NOT_FOUND_STUB_TEMPLATE.replace("__ON_CONFLICT__", "UPDATE SET not_found_at = now()")
)


def upsert_not_found_stub(
    conn: Connection,
    *,
    source: str,
    source_id: str,
    doi: str | None = None,
    entry_mode: str,
    rearm: bool = False,
) -> None:
    """Pose un stub `staging` « introuvable » (raw_data vide, `not_found_at`, `processed`).

    Partagé par les cross-imports (crossref/datacite par DOI, HAL par hal-id/NNT).
    `rearm=True` : ré-arme `not_found_at` sur conflit (miss retriable, HAL) ; sinon
    `DO NOTHING` (miss définitif d'une source native du DOI). Ne commit pas.
    """
    sql = _NOT_FOUND_STUB_REARM if rearm else _NOT_FOUND_STUB_DO_NOTHING
    conn.execute(
        sql, {"source": source, "source_id": source_id, "doi": doi, "entry_mode": entry_mode}
    )


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

    Le DOI est normalisé par `clean_doi` avant écriture : `doi_lookups.doi`
    sert de clé d'exclusion comparée à des DOI déjà normalisés (cf.
    `get_cross_import_dois`) — toute forme non canonique manquerait le backoff.
    """
    conn.execute(
        _RECORD_DOI_NOT_FOUND_SQL,
        {"source": source, "doi": clean_doi(doi), "days": DOI_LOOKUP_RETRY_DAYS},
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
    (DOI secondaires : preprint/dépôt/édition) ∪ `publication_relations.target_doi`
    (cibles des relations entre publications : preprint/supplément/data paper… à rapatrier)
    ∪ DOI DataCite déduits de `source_publications.external_ids.arxiv_id` (préfixe
    `10.48550/arXiv.<id>` : tout dépôt arXiv expose ce DOI DataCite, modernes comme anciens
    identifiants). Les related_dois, les relations et les arxiv_id proviennent des runs
    précédents (source_publications normalisés, phase `relations`) : ceux d'un record
    fraîchement ingéré sont rattrapés au run suivant — bénin (le pipeline est convergent).

    Le SQL compare les `doi` par égalité directe, pour s'appuyer sur l'index
    btree `idx_staging_doi`. Les candidats retenus sont normalisés via `clean_doi`
    et dédoublonnés avant d'être renvoyés : les appels HTTP par DOI en aval
    reçoivent une forme canonique, quelle que soit la propreté de la valeur source.

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
    # Pool de DOI candidats centralisé dans la vue `candidate_dois` : staging +
    # related_dois + cibles de relations (source NULL) + arXiv-dérivés. La même
    # vue alimente la résolution de RA des préfixes — tout DOI interrogé ici a donc
    # son préfixe résolu en amont. L'exclusion du target se fait via
    # `source IS DISTINCT FROM` (les relations à source NULL restent candidates
    # pour toutes les cibles) et le `NOT IN (staging du target)` final.
    if isinstance(conn, Connection):
        prefix_filter = " AND (dp.ra = :target_ra OR dp.ra IS NULL)" if target_ra else ""
        query = f"""
            SELECT DISTINCT c.doi
            FROM candidate_dois c
            {join_clause}
            WHERE c.source IS DISTINCT FROM :target
              AND c.doi NOT IN (
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
        rows = conn.execute(text(query), params).scalars()
        # Re-nettoyage des candidats avant tout appel HTTP par DOI : la colonne
        # `staging.doi` peut porter du legacy non normalisé (le `clean_doi` à
        # l'écriture est récent). Idempotent ; `dict.fromkeys` dédoublonne les
        # collisions induites par la normalisation en préservant l'ordre.
        return list(dict.fromkeys(c for d in rows if (c := clean_doi(d))))

    pg_prefix_filter = " AND (dp.ra = %(target_ra)s OR dp.ra IS NULL)" if target_ra else ""
    query_pg = f"""
        SELECT DISTINCT c.doi
        FROM candidate_dois c
        {join_clause}
        WHERE c.source IS DISTINCT FROM %(target)s
          AND c.doi NOT IN (
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
        # Cf. branche SA : re-nettoyage idempotent + dédoublonnage avant le lookup HTTP.
        return list(dict.fromkeys(c for row in cur.fetchall() if (c := clean_doi(row["doi"]))))


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
