"""Sélection des hal-ids et des NNT à chercher dans HAL, pour la phase `fetch_missing`.

`get_missing_hal_ids` et `get_missing_nnts` bâtissent les listes d'identifiants que d'autres sources portent et que HAL n'a pas rendus.
"""

from sqlalchemy import Connection, text

from infrastructure.pipeline.fetch_missing.failed_lookups import pending_failed_lookup_sql

_HAL_ID_PENDING = pending_failed_lookup_sql(
    source_sql="'hal'", id_type="hal_id", value_sql="h.hal_id"
)

_MISSING_HAL_IDS_SQL = text(
    f"""
    SELECT DISTINCT h.hal_id
    FROM source_publications sp
    JOIN publications p ON p.id = sp.publication_id
    CROSS JOIN LATERAL jsonb_array_elements_text(sp.external_ids -> 'hal_id') AS h(hal_id)
    WHERE sp.source IN ('openalex', 'scanr')
      AND p.in_perimeter
      AND jsonb_typeof(sp.external_ids -> 'hal_id') = 'array'
      AND NOT EXISTS (
          SELECT 1 FROM staging s WHERE s.source = 'hal' AND s.source_id = h.hal_id
      )
      AND NOT {_HAL_ID_PENDING}
    """
)

_NNT_PENDING = pending_failed_lookup_sql(
    source_sql="'hal'", id_type="nnt", value_sql="sp.external_ids ->> 'nnt'"
)

_MISSING_NNTS_SQL = text(
    f"""
    SELECT sp.external_ids ->> 'nnt' AS nnt
    FROM source_publications sp
    JOIN publications p ON p.id = sp.publication_id
    WHERE sp.source = 'theses'
      AND p.in_perimeter
      AND sp.external_ids ->> 'nnt' IS NOT NULL
      AND p.doc_type != 'ongoing_thesis'
      AND NOT EXISTS (
          SELECT 1 FROM source_publications hal
          WHERE hal.publication_id = p.id AND hal.source = 'hal'
      )
      AND NOT EXISTS (
          SELECT 1 FROM source_publications hal
          WHERE hal.source = 'hal' AND hal.external_ids ->> 'nnt' = sp.external_ids ->> 'nnt'
      )
      AND NOT {_NNT_PENDING}
    """
)


def get_missing_hal_ids(conn: Connection) -> list[str]:
    """hal-ids que des `source_publications` OpenAlex ou ScanR portent dans `external_ids.hal_id`, absents du staging HAL.

    Seules comptent les publications in-périmètre : un document hors périmètre n'entraîne aucune recherche dans HAL. La sélection lit les `source_publications` du run précédent : les documents extraits pendant le run y entrent au run suivant.

    Écarte les hal-ids déjà cherchés en vain : HAL est leur source native, l'échec est définitif.
    """
    return list(conn.execute(_MISSING_HAL_IDS_SQL).scalars())


def get_missing_nnts(conn: Connection) -> list[str]:
    """NNT des `source_publications` theses.fr des publications in-périmètre, hors thèses en cours, dont la publication n'a aucune `source_publications` HAL.

    Écarte les NNT qu'un document HAL porte déjà, et ceux dont la recherche a échoué et attend encore sa reprise.
    """
    return list(conn.execute(_MISSING_NNTS_SQL).scalars())
