-- refresh_publication_countries.sql
-- Recalcule publications.countries à partir des 3 sources (HAL, OpenAlex, WoS).
--
-- À exécuter après :
--   - normalize_hal.py / normalize_openalex.py / normalize_wos.py
--   - backfill_wos_addresses.py (qui peuple wos_documents.countries)
--
-- Usage :
--   psql -d publisher_stats -U lalecoz -f db/refresh_publication_countries.sql

UPDATE publications p
SET countries = sub.all_countries
FROM (
    SELECT p2.id,
           (SELECT array_agg(DISTINCT c ORDER BY c)
            FROM (
                SELECT unnest(hd.countries) AS c
                FROM hal_documents hd
                WHERE hd.publication_id = p2.id AND hd.countries IS NOT NULL
                UNION ALL
                SELECT unnest(od.countries)
                FROM openalex_documents od
                WHERE od.publication_id = p2.id AND od.countries IS NOT NULL
                UNION ALL
                SELECT unnest(wd.countries)
                FROM wos_documents wd
                WHERE wd.publication_id = p2.id AND wd.countries IS NOT NULL
            ) src
           ) AS all_countries
    FROM publications p2
) sub
WHERE p.id = sub.id
  AND p.countries IS DISTINCT FROM sub.all_countries;
