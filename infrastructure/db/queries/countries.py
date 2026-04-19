"""Query service : recalcul des pays des publications.

Trois étapes (write-only) appelées par l'orchestrateur pipeline
`application/pipeline/countries/refresh_publication_countries.py` :

1. HAL  : `source_structures.country` → `source_publications.countries`
2. OA/WoS/ScanR : `addresses.countries` → `source_publications.countries`
3. Union de tous les `source_publications.countries` → `publications.countries`
"""

from typing import Any


def refresh_hal_source_countries(cur: Any) -> int:
    """Propage `source_structures.country` vers `source_publications.countries` (HAL).

    Pour chaque document HAL, collecte les pays des structures de ses auteurs
    (via `source_authorships.source_struct_ids` → `source_structures.country`).
    Retourne le nombre de lignes mises à jour.
    """
    cur.execute("""
        UPDATE source_publications sd
        SET countries = sub.doc_countries
        FROM (
            SELECT sa.source_publication_id,
                   array_agg(DISTINCT ss.country ORDER BY ss.country) AS doc_countries
            FROM source_authorships sa,
                 LATERAL unnest(sa.source_struct_ids) AS ssid(val)
            JOIN source_structures ss ON ss.id = ssid.val
            WHERE sa.source = 'hal'
              AND ss.country IS NOT NULL
            GROUP BY sa.source_publication_id
        ) sub
        WHERE sd.id = sub.source_publication_id
          AND sd.source = 'hal'
          AND sd.countries IS DISTINCT FROM sub.doc_countries
    """)
    return cur.rowcount


def refresh_address_source_countries(cur: Any) -> int:
    """Propage `addresses.countries` vers `source_publications.countries` (OA/WoS/ScanR).

    Pour chaque document non-HAL, collecte les pays des adresses de ses auteurs
    (via `source_authorship_addresses` → `addresses.countries`).
    Retourne le nombre de lignes mises à jour.
    """
    cur.execute("""
        UPDATE source_publications sd
        SET countries = sub.doc_countries
        FROM (
            SELECT sa.source_publication_id,
                   array_agg(DISTINCT c::text ORDER BY c::text) AS doc_countries
            FROM source_authorships sa
            JOIN source_authorship_addresses saa ON saa.source_authorship_id = sa.id
            JOIN addresses a ON a.id = saa.address_id,
            LATERAL unnest(a.countries) AS c
            WHERE a.countries IS NOT NULL
            GROUP BY sa.source_publication_id
        ) sub
        WHERE sd.id = sub.source_publication_id
          AND sd.countries IS DISTINCT FROM sub.doc_countries
    """)
    return cur.rowcount


def refresh_publication_countries(cur: Any) -> int:
    """Calcule `publications.countries` comme union des `source_publications.countries`.

    Retourne le nombre de lignes mises à jour.
    """
    cur.execute("""
        UPDATE publications p
        SET countries = sub.all_countries
        FROM (
            SELECT sd.publication_id AS pub_id,
                   array_agg(DISTINCT c ORDER BY c) AS all_countries
            FROM source_publications sd,
            LATERAL unnest(sd.countries) AS c
            WHERE sd.countries IS NOT NULL
              AND sd.publication_id IS NOT NULL
            GROUP BY sd.publication_id
        ) sub
        WHERE p.id = sub.pub_id
          AND p.countries IS DISTINCT FROM sub.all_countries
    """)
    return cur.rowcount
