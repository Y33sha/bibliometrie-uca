"""Écritures `staging` à l'extraction et au cross-import : UPSERT canonique et stub introuvable.

Appelées par les adapters d'extraction et de cross-import (`infrastructure/sources/*`), et par la base de refresh stale. Le commit est à la charge de l'appelant.
"""

from collections.abc import Mapping

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue
from infrastructure.pipeline.change_detection import change_detection_hash

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
        -- Renseigne le DOI quand la ligne existait sans (doc moissonné avant que la source ne porte le DOI) ; ne clobbe jamais un DOI déjà posé.
        doi = COALESCE(staging.doi, EXCLUDED.doi),
        processed = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN FALSE
            ELSE staging.processed
        END,
        -- Suit `raw_hash` comme `processed` : un payload bulk inchangé n'écrase pas le flag (préserve l'effacement posé par refetch_truncated) ; un payload modifié le recalcule depuis le nouveau contenu.
        authors_truncated = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN EXCLUDED.authors_truncated
            ELSE staging.authors_truncated
        END,
        -- `entry_mode` n'est PAS réécrit : il garde la provenance de première création.
        -- Un document trouvé avec un vrai contenu n'est ni introuvable ni disparu : la réapparition efface les deux marqueurs d'absence, sans quoi un stub `not_found_at` (cross-import) violerait `staging_not_found_at_implies_processed` dès que `processed` repasse à FALSE.
        not_found_at = NULL,
        disappeared_at = NULL,
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
    raw_data: Mapping[str, JsonValue],
    authors_truncated: bool = False,
    entry_mode: str = "bulk",
) -> tuple[bool, bool]:
    """UPSERT canonique d'une ligne `staging`, partagé par toutes les voies d'entrée (extraction bulk **et** cross-import — un seul endroit pour la logique d'UPSERT).

    `INSERT … ON CONFLICT (source, source_id) DO UPDATE` piloté par `raw_hash` : réécrit `raw_data` (et repasse `processed=FALSE`) seulement si le hash a changé, met toujours à jour `last_seen_at`, et renseigne `doi` s'il manquait (jamais d'écrasement). Un `raw_hash=null` en base force le re-import (`NULL IS DISTINCT FROM <hash>`). Le hash est calculé via `change_detection_hash`, qui neutralise le bruit volatil propre à la source avant l'empreinte (le payload stocké reste, lui, fidèle).

    `authors_truncated` (OpenAlex : payload bulk plafonné à 100 auteurs) suit la même logique que `processed` — (re)posé seulement quand le hash change, sinon préservé (n'écrase pas l'effacement de `refetch_truncated`). Les sources non plafonnées laissent le défaut `False`.

    `entry_mode` enregistre comment la ligne est **entrée** (`bulk` à l'extraction, `cross_import_doi` / `cross_import_hal` au cross-import) ; posé à la création, jamais réécrit (provenance d'origine).

    Retourne `(inserted, changed)` : `inserted` = vraie insertion (`xmax = 0`), `changed` = contenu réécrit (hash distinct de celui déjà en base). Le commit est à la charge de l'appelant.
    """
    row = conn.execute(
        _UPSERT_STAGING_SQL,
        {
            "source": source,
            "source_id": source_id,
            "doi": clean_doi(doi),
            "raw_data": raw_data,
            "raw_hash": change_detection_hash(source, raw_data),
            "authors_truncated": authors_truncated,
            "entry_mode": entry_mode,
        },
    ).one()
    return (bool(row.inserted), bool(row.changed))


_NOT_FOUND_STUB_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, not_found_at, processed, entry_mode)
    VALUES (:source, :source_id, :doi, '{}'::jsonb, now(), TRUE, :entry_mode)
    ON CONFLICT (source, source_id) DO UPDATE SET not_found_at = now()
    """
)


def upsert_not_found_stub(
    conn: Connection,
    *,
    source: str,
    source_id: str,
    doi: str | None = None,
    entry_mode: str,
) -> None:
    """Pose un stub `staging` « introuvable » (raw_data vide, `not_found_at`, `processed`).

    Utilisé par le cross-import HAL (hal-id / NNT), dont l'identifiant natif est le hal-id : le stub est keyé par `(source, source_id)` et ré-arme `not_found_at` sur conflit (le miss est retriable — HAL peut publier le document plus tard). Ne commit pas. Les misses par DOI, eux, vivent dans `doi_lookups` (cf. `record_doi_not_found`).
    """
    conn.execute(
        _NOT_FOUND_STUB_SQL,
        {"source": source, "source_id": source_id, "doi": doi, "entry_mode": entry_mode},
    )
