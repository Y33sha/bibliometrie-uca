-- Migration : déplacer la FK authorships ↔ source_authorships du côté source
-- Avant : authorships.hal_authorship_id, openalex_authorship_id, wos_authorship_id, scanr_authorship_id
-- Après : source_authorships.authorship_id → authorships(id)

BEGIN;

-- 1. Ajouter la colonne sur source_authorships
ALTER TABLE source_authorships ADD COLUMN authorship_id INTEGER REFERENCES authorships(id) ON DELETE SET NULL;

-- 2. Peupler depuis les 4 colonnes de authorships
UPDATE source_authorships sa
SET authorship_id = a.id
FROM authorships a
WHERE sa.source = 'hal' AND sa.id = a.hal_authorship_id;

UPDATE source_authorships sa
SET authorship_id = a.id
FROM authorships a
WHERE sa.source = 'openalex' AND sa.id = a.openalex_authorship_id;

UPDATE source_authorships sa
SET authorship_id = a.id
FROM authorships a
WHERE sa.source = 'wos' AND sa.id = a.wos_authorship_id;

UPDATE source_authorships sa
SET authorship_id = a.id
FROM authorships a
WHERE sa.source = 'scanr' AND sa.id = a.scanr_authorship_id;

-- 3. Supprimer les anciennes colonnes de authorships
ALTER TABLE authorships DROP COLUMN hal_authorship_id;
ALTER TABLE authorships DROP COLUMN openalex_authorship_id;
ALTER TABLE authorships DROP COLUMN wos_authorship_id;
ALTER TABLE authorships DROP COLUMN scanr_authorship_id;

-- 4. Index
CREATE INDEX idx_sa_authorship ON source_authorships (authorship_id) WHERE authorship_id IS NOT NULL;

COMMIT;
