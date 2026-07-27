"""Sélection des rows `staging` périmées et marquage des disparues (phase refresh stale).

`get_stale_rows` liste les rows dont `last_seen_at` a franchi le seuil ; `set_disappeared_by_source_id` marque celles dont le refetch a confirmé l'absence. Le commit est à la charge de l'appelant.
"""

from typing import Any

from sqlalchemy import Connection, text

from domain.sources.registry import ALL_SOURCES_SET as VALID_SOURCES

STALE_REFRESH_AFTER_DAYS = 90
"""Âge (jours) de `staging.last_seen_at` au-delà duquel une row est refetchée.

La phase « refresh stale » (fin de cross-import, à chaque run) refetche par id natif les rows dont `last_seen_at < now() - STALE_REFRESH_AFTER_DAYS` : trouvé → `last_seen_at` mis à jour + refresh `raw_data` ; 404 → `disappeared_at`. Tournant à chaque run, le seuil étale la charge (chaque passe ne ramasse que ce qui vient de franchir le délai) sans `LIMIT`.
"""

# Filtre année (`{year_clause}`) : `pub_year` vient de `source_publications` (LEFT JOIN ; NULL si absent, conservé).
_STALE_ROWS_SQL_TEMPLATE = """
    SELECT s.id, s.source_id
    FROM staging s
    LEFT JOIN source_publications sp
      ON sp.source = s.source AND sp.source_id = s.source_id
    WHERE s.source = CAST(:source AS source_type)
      AND s.not_found_at IS NULL
      AND s.disappeared_at IS NULL
      AND s.last_seen_at < now() - make_interval(days => :days)
      {year_clause}
    ORDER BY s.id
"""

_SET_DISAPPEARED_BY_SOURCE_ID_SQL = text(
    """
    UPDATE staging SET disappeared_at = now()
    WHERE source = CAST(:source AS source_type) AND source_id = :source_id
      AND disappeared_at IS NULL AND not_found_at IS NULL
    """
)


def get_stale_rows(
    conn: Connection, source: str, years: list[int] | None = None
) -> list[tuple[int, str]]:
    """Rows `(id, source_id)` de `source` dont `last_seen_at` dépasse STALE_REFRESH_AFTER_DAYS.

    Alimente la phase refresh : chaque row est refetchée par son `source_id` natif. Toute row a un `source_id` (`NOT NULL`) : la sélection ne dépend pas de la présence d'un DOI. Exclut les stubs not-found et les rows déjà marquées disparues.

    `years` borne la sélection à la fenêtre d'années du run courant, jointe depuis `source_publications.pub_year` : un run sur une période glissante ne refetche que le stale de ses propres années, sans requêtes unitaires inutiles sur des années hors de sa fenêtre bulk. `None` = aucune borne (tout le stale de la source).
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {source}. Valides : {', '.join(VALID_SOURCES)}")
    params: dict[str, Any] = {"source": source, "days": STALE_REFRESH_AFTER_DAYS}
    year_clause = ""
    if years is not None:
        year_clause = "AND (sp.pub_year IS NULL OR sp.pub_year = ANY(:years))"
        params["years"] = list(years)
    sql = text(_STALE_ROWS_SQL_TEMPLATE.format(year_clause=year_clause))
    return [(row.id, row.source_id) for row in conn.execute(sql, params)]


def set_disappeared_by_source_id(conn: Connection, source: str, source_id: str) -> None:
    """Marque `disappeared_at` sur la row `(source, source_id)` confirmée absente.

    Appelé par la phase refresh quand le refetch par id natif renvoie une absence confirmée (réponse valide, zéro record). Ne commit pas — l'appelant s'en charge.
    """
    conn.execute(_SET_DISAPPEARED_BY_SOURCE_ID_SQL, {"source": source, "source_id": source_id})
