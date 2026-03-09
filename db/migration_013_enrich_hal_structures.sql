-- =============================================================
-- Migration 013 : Enrichissement de hal_structures
-- =============================================================
-- Ajoute les métadonnées complètes de l'API ref/structure HAL :
-- dates, identifiants externes, statut, adresse, alias, etc.
-- Permet de naviguer l'arbre hiérarchique (parents, alias/phases)
-- et d'identifier automatiquement les structures enfants de l'UCA.
-- =============================================================

BEGIN;

-- Dates de validité
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS start_date DATE;
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS end_date DATE;

-- Statut HAL
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS valid TEXT;  -- 'VALID', 'OLD'

-- Identifiants externes
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS rnsr TEXT;       -- code RNSR
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS ror TEXT;        -- identifiant ROR
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS idref TEXT;      -- identifiant IdRef
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS isni TEXT;       -- identifiant ISNI
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS code TEXT;       -- code UMR/EA/etc

-- Localisation
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS country TEXT;
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS address TEXT;
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS url TEXT;

-- Alias = les autres docid HAL qui désignent la même structure (phases)
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS alias_ids INT[];

-- Parents enrichis (types et acronymes)
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS parent_acronyms TEXT[];
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS parent_types TEXT[];

-- Métadonnées de gestion
ALTER TABLE hal_structures ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMPTZ;

-- Index pour requêtes hiérarchiques
CREATE INDEX IF NOT EXISTS idx_hal_struct_type ON hal_structures (type);
CREATE INDEX IF NOT EXISTS idx_hal_struct_valid ON hal_structures (valid);
CREATE INDEX IF NOT EXISTS idx_hal_struct_parent_ids ON hal_structures USING GIN (parent_ids);
CREATE INDEX IF NOT EXISTS idx_hal_struct_alias_ids ON hal_structures USING GIN (alias_ids);

COMMIT;
