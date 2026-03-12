-- Migration 025 : person_identifiers.rejected → status (enum)
-- Remplace le booléen rejected par une colonne status à 3 valeurs.

BEGIN;

-- 1. Créer le type enum
CREATE TYPE identifier_status AS ENUM ('pending', 'confirmed', 'rejected');

-- 2. Ajouter la nouvelle colonne
ALTER TABLE person_identifiers ADD COLUMN status identifier_status NOT NULL DEFAULT 'pending';

-- 3. Migrer les données existantes
UPDATE person_identifiers SET status = 'rejected' WHERE rejected = TRUE;
-- rejected = FALSE ou NULL → 'pending' (valeur par défaut, pas confirmé)

-- 4. Supprimer l'ancienne colonne
ALTER TABLE person_identifiers DROP COLUMN rejected;

COMMIT;
