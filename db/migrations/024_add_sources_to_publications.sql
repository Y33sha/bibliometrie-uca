-- Migration 024 : Colonne sources (source_type[]) sur publications
--
-- Remplace la vue publication_sources pour les filtres par source.
-- Maintenue par update_sources() dans services/publications.py.

ALTER TABLE publications
    ADD COLUMN IF NOT EXISTS sources source_type[] NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_publications_sources
    ON publications USING gin (sources);

-- Rétro-remplissage depuis les 4 tables source
UPDATE publications p SET sources = COALESCE(sub.srcs, '{}')
FROM (
    SELECT pub_id, array_agg(DISTINCT src ORDER BY src) AS srcs
    FROM (
        SELECT publication_id AS pub_id, 'hal'::source_type AS src
        FROM hal_documents WHERE publication_id IS NOT NULL
        UNION ALL
        SELECT publication_id, 'openalex'::source_type
        FROM openalex_documents WHERE publication_id IS NOT NULL
        UNION ALL
        SELECT publication_id, 'wos'::source_type
        FROM wos_documents WHERE publication_id IS NOT NULL
        UNION ALL
        SELECT publication_id, 'scanr'::source_type
        FROM scanr_documents WHERE publication_id IS NOT NULL
    ) t
    GROUP BY pub_id
) sub
WHERE p.id = sub.pub_id;
