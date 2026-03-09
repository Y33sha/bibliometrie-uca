-- =============================================================
-- Migration 014b : Modification des tables existantes (schéma v2)
-- =============================================================
-- Modifie les tables existantes pour les aligner sur le schéma cible.
-- Aucune table n'est supprimée ici (c'est le rôle de migration_015).
--
-- Modifications :
--   1. hal_structures : PK hal_struct_id → id SERIAL + hal_struct_id UNIQUE
--   2. structures : drop laboratory_id
--   3. structure_relations : relation_type ENUM → TEXT
--   4. publications : drop is_validated
--   5. addresses : renommer raw_text_normalized → normalized_text, ajouter country
--   6. authors → legacy_authors
--
-- Prérequis : migration_014a appliquée.
-- =============================================================

BEGIN;


-- =============================================================
-- 1. hal_structures : PK hal_struct_id → id SERIAL
-- =============================================================
-- Actuellement hal_struct_id est la PK (INT, pas auto-incrémenté).
-- On veut : id SERIAL PK + hal_struct_id INT NOT NULL UNIQUE.
-- Aucune FK externe ne pointe vers hal_structures, donc pas de cascade.

-- Ajouter la colonne id
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS id SERIAL;

-- Supprimer l'ancienne PK
ALTER TABLE hal_structures DROP CONSTRAINT IF EXISTS hal_structures_pkey;

-- Nouvelle PK sur id
ALTER TABLE hal_structures ADD PRIMARY KEY (id);

-- Contrainte UNIQUE + NOT NULL sur hal_struct_id
ALTER TABLE hal_structures ALTER COLUMN hal_struct_id SET NOT NULL;
ALTER TABLE hal_structures ADD CONSTRAINT hal_structures_hal_struct_id_key UNIQUE (hal_struct_id);

-- Supprimer la contrainte NOT NULL sur name (le schéma cible l'accepte NULL
-- pour les structures INCOMING sans nom)
ALTER TABLE hal_structures ALTER COLUMN name DROP NOT NULL;


-- =============================================================
-- 2. structures : drop laboratory_id
-- =============================================================
-- La FK vers l'ancienne table laboratories n'a plus de raison d'être.

ALTER TABLE structures DROP COLUMN IF EXISTS laboratory_id;


-- =============================================================
-- 3. structure_relations : relation_type ENUM → TEXT
-- =============================================================
-- L'ENUM relation_type est trop rigide. On passe en TEXT.

ALTER TABLE structure_relations
    ALTER COLUMN relation_type TYPE TEXT USING relation_type::TEXT;

-- L'ENUM sera supprimée en phase cleanup (d'autres colonnes pourraient
-- encore la référencer temporairement).


-- =============================================================
-- 4. publications : drop is_validated
-- =============================================================
-- Les vues existantes dépendent de cette colonne, il faut les supprimer d'abord.
-- Elles sont de toute façon obsolètes (schéma v1).

DROP VIEW IF EXISTS v_publications_full;
DROP VIEW IF EXISTS v_stats_labo_publisher;
DROP VIEW IF EXISTS v_stats_labo_journal;

ALTER TABLE publications DROP COLUMN IF EXISTS is_validated;


-- =============================================================
-- 5. addresses : harmoniser avec le schéma cible
-- =============================================================

-- Renommer raw_text_normalized → normalized_text
ALTER TABLE addresses RENAME COLUMN raw_text_normalized TO normalized_text;

-- Ajouter country
ALTER TABLE addresses ADD COLUMN IF NOT EXISTS country TEXT;

-- Les colonnes is_uca et resolved_at seront supprimées en phase cleanup
-- (elles peuvent encore servir de référence pendant la migration data).


-- =============================================================
-- 6. authors → legacy_authors
-- =============================================================
-- Renommer la table. Les index et contraintes suivent automatiquement
-- (PostgreSQL renomme la table mais pas les objets associés, ce qui est OK).

ALTER TABLE authors RENAME TO legacy_authors;

-- Renommer l'index principal pour la lisibilité
ALTER INDEX IF EXISTS idx_authors_orcid RENAME TO idx_legacy_authors_orcid;
ALTER INDEX IF EXISTS idx_authors_name RENAME TO idx_legacy_authors_name;


COMMIT;
