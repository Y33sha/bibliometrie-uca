-- =============================================================
-- Migration 015 — Nettoyage post-migration v2
-- =============================================================
-- Supprime les anciennes tables devenues inutiles, nettoie les
-- colonnes temporaires, et crée la vue publication_sources.
--
-- ⚠ IRRÉVERSIBLE — s'assurer que les étapes 2.1 à 2.7 sont
--   complètes et vérifiées avant exécution.
-- =============================================================

BEGIN;

-- Supprimer les vues qui référencent les anciennes tables
DROP VIEW IF EXISTS v_publications_full;
DROP VIEW IF EXISTS v_stats_labo_publisher;
DROP VIEW IF EXISTS v_stats_labo_journal;

-- Supprimer les anciennes tables (ordre : respecter les FK)
DROP TABLE IF EXISTS publication_author_addresses;
DROP TABLE IF EXISTS address_laboratories;
DROP TABLE IF EXISTS publication_authors;
DROP TABLE IF EXISTS publication_sources;
DROP TABLE IF EXISTS legacy_authors;
DROP TABLE IF EXISTS confusing_forms;
DROP TABLE IF EXISTS laboratories;

-- Nettoyer les colonnes temporaires sur addresses
ALTER TABLE addresses DROP COLUMN IF EXISTS is_uca;
ALTER TABLE addresses DROP COLUMN IF EXISTS resolved_at;

-- Supprimer les types ENUM obsolètes
DROP TYPE IF EXISTS relation_type;

-- Créer la vue publication_sources
CREATE VIEW publication_sources AS
    SELECT publication_id, 'hal'::source_type AS source, halid AS source_id
    FROM hal_documents WHERE publication_id IS NOT NULL
    UNION ALL
    SELECT publication_id, 'openalex'::source_type AS source, openalex_id AS source_id
    FROM openalex_documents WHERE publication_id IS NOT NULL;

COMMIT;
