-- Suppression des index redondants ou jamais utilisés.
--
-- source_authorships :
--   idx_sa_source_doc (source_document_id) -> couvert par la contrainte unique (source_document_id, source_author_id)
--   idx_sa_source (source) -> 5 valeurs, sélectivité nulle
--   idx_sa_doc_pos_affil (source_document_id, author_position) WHERE ... -> 0 scans
--   idx_sa_doc_perimeter (source_document_id) INCLUDE ... WHERE in_perimeter -> 0 scans
--   idx_sa_in_perimeter (in_perimeter) WHERE in_perimeter -> 0 scans, redondant
--
-- source_authorship_addresses :
--   idx_saa_authorship (source_authorship_id) -> couvert par la contrainte unique (source_authorship_id, address_id)
--
-- source_authors :
--   idx_source_authors_source (source) -> couvert par la contrainte unique (source, source_id)
--
-- publications :
--   idx_publications_title_norm (title_normalized) -> couvert par idx_publications_titlenorm_year (title_normalized, pub_year)
--   idx_publications_doi -> doublon de publications_doi_lower_key (même définition)
--
-- source_documents :
--   idx_source_docs_source (source) -> couvert par la contrainte unique (source, source_id)
--
-- addresses :
--   idx_addr_norm_trgm -> 0 scans, trigram sur normalized_text

-- source_authorships (277 Mo)
DROP INDEX IF EXISTS idx_sa_source_doc;
DROP INDEX IF EXISTS idx_sa_source;
DROP INDEX IF EXISTS idx_sa_doc_pos_affil;
DROP INDEX IF EXISTS idx_sa_doc_perimeter;
DROP INDEX IF EXISTS idx_sa_in_perimeter;

-- source_authorship_addresses (110 Mo)
DROP INDEX IF EXISTS idx_saa_authorship;

-- source_authors (5 Mo)
DROP INDEX IF EXISTS idx_source_authors_source;

-- publications (22 Mo)
DROP INDEX IF EXISTS idx_publications_title_norm;
DROP INDEX IF EXISTS idx_publications_doi;

-- source_documents (1 Mo)
DROP INDEX IF EXISTS idx_source_docs_source;

-- addresses (49 Mo)
DROP INDEX IF EXISTS idx_addr_norm_trgm;
