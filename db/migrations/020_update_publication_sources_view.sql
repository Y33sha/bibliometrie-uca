-- Recréer la vue publication_sources avec ScanR
CREATE OR REPLACE VIEW publication_sources AS
    SELECT publication_id, 'hal'::source_type AS source, halid AS source_id
    FROM hal_documents WHERE publication_id IS NOT NULL
    UNION ALL
    SELECT publication_id, 'openalex'::source_type AS source, openalex_id AS source_id
    FROM openalex_documents WHERE publication_id IS NOT NULL
    UNION ALL
    SELECT publication_id, 'wos'::source_type AS source, ut AS source_id
    FROM wos_documents WHERE publication_id IS NOT NULL
    UNION ALL
    SELECT publication_id, 'scanr'::source_type AS source, scanr_id AS source_id
    FROM scanr_documents WHERE publication_id IS NOT NULL;
