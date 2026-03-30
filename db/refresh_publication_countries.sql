-- refresh_publication_countries.sql
-- Recalcule publications.countries à partir de HAL (structures) et des adresses (OA + WoS).
--
-- Sources des pays :
--   - HAL : hal_documents.countries (vient de hal_structures.country, peuplé par normalisation)
--   - OpenAlex : calculé depuis les adresses (openalex_authorship_addresses → addresses.countries)
--   - WoS : calculé depuis les adresses (wos_authorship_addresses → addresses.countries)
--
-- On n'utilise PAS openalex_documents.countries ni les pays du staging OA
-- (dérivés de l'algo OpenAlex, souvent fautifs).
--
-- Usage :
--   psql -d publisher_stats -U lalecoz -f db/refresh_publication_countries.sql

UPDATE publications p
SET countries = sub.all_countries
FROM (
    SELECT p2.id,
           (SELECT array_agg(DISTINCT c ORDER BY c)
            FROM (
                -- HAL : pays des structures HAL
                SELECT unnest(hd.countries) AS c
                FROM hal_documents hd
                WHERE hd.publication_id = p2.id AND hd.countries IS NOT NULL
                UNION ALL
                -- OpenAlex : pays des adresses résolues
                SELECT unnest(a.countries) AS c
                FROM openalex_authorship_addresses oaa
                JOIN addresses a ON a.id = oaa.address_id
                JOIN openalex_authorships oas ON oas.id = oaa.openalex_authorship_id
                JOIN openalex_documents od ON od.id = oas.openalex_document_id
                WHERE od.publication_id = p2.id AND a.countries IS NOT NULL
                UNION ALL
                -- WoS : pays des adresses résolues
                SELECT unnest(a.countries) AS c
                FROM wos_authorship_addresses waa
                JOIN addresses a ON a.id = waa.address_id
                JOIN wos_authorships was ON was.id = waa.wos_authorship_id
                JOIN wos_documents wd ON wd.id = was.wos_document_id
                WHERE wd.publication_id = p2.id AND a.countries IS NOT NULL
            ) src
           ) AS all_countries
    FROM publications p2
) sub
WHERE p.id = sub.id
  AND p.countries IS DISTINCT FROM sub.all_countries;
