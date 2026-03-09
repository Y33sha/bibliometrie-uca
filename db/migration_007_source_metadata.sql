-- =============================================================
-- Migration 007 : Métadonnées structurées par source
--
-- Ajoute des colonnes à publication_sources pour préserver
-- les métadonnées de chaque source (HAL, OpenAlex) séparément,
-- permettant la comparaison et la détection de divergences.
--
-- raw_title et raw_doc_type existaient déjà.
-- =============================================================

BEGIN;

-- Titre de la revue / source selon cette source
ALTER TABLE publication_sources
    ADD COLUMN IF NOT EXISTS journal_title_source TEXT;

-- Statut OA selon cette source
ALTER TABLE publication_sources
    ADD COLUMN IF NOT EXISTS oa_status_source TEXT;

-- URL vers le document selon cette source
ALTER TABLE publication_sources
    ADD COLUMN IF NOT EXISTS url_source TEXT;

-- Année de publication selon cette source
ALTER TABLE publication_sources
    ADD COLUMN IF NOT EXISTS pub_year_source SMALLINT;

COMMIT;
