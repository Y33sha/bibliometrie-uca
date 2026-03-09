-- =============================================================
-- Migration 017 : Index de performance pour stats et publications
-- =============================================================
--
-- Les pages /stats et /publications reposent sur des requêtes
-- complexes avec EXISTS (PUB_IS_UCA), des jointures publication →
-- journal → publisher, et des agrégations par oa_status.
--
-- Cette migration ajoute des index composites ciblés pour
-- accélérer ces requêtes.
-- =============================================================

-- 1. PUB_IS_UCA : index composites pour les sous-requêtes EXISTS
--    Remplacent les index partiels simples (is_uca) qui n'incluent
--    pas la colonne de jointure → évite le table lookup.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hal_as_uca_doc
    ON hal_authorships (hal_document_id)
    WHERE is_uca = TRUE;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_oa_as_uca_doc
    ON openalex_authorships (openalex_document_id)
    WHERE is_uca = TRUE;

-- 2. publications : index composite pour le filtre doc_type + année
--    Quasi toutes les requêtes stats filtrent sur doc_type IN ('article','review')
--    et optionnellement sur pub_year.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_publications_doctype_year
    ON publications (doc_type, pub_year);

-- 3. publications : index composite journal_id + oa_status
--    Utilisé par les agrégations OA groupées par journal/publisher.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_publications_journal_oa
    ON publications (journal_id, oa_status);

-- 4. journals : index composite publisher_id incluant oa_model
--    Le filtre oa_model IS DISTINCT FROM 'repository' est systématique.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_journals_publisher_oamodel
    ON journals (publisher_id, oa_model);

-- 5. publication_sources : index composite (publication_id, source)
--    Chaque ligne de /api/publications fait 2 sous-requêtes sur cette table.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pubsources_pub_source
    ON publication_sources (publication_id, source);

-- 6. publishers : ILIKE search → trigram index
--    Accélère la recherche textuelle dans /api/pub-stats/publishers.
--    Nécessite l'extension pg_trgm (généralement déjà installée).
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_publishers_name_trgm
        ON publishers USING GIN (name gin_trgm_ops);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pg_trgm extension not available, skipping trigram index';
END $$;
