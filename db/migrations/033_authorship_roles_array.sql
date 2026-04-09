-- Migration : convertir role text → roles text[] sur les authorships
-- et ajouter la colonne roles sur openalex_authorships (qui n'en avait pas)

BEGIN;

-- HAL : role text → roles text[]
ALTER TABLE hal_authorships ADD COLUMN roles TEXT[];
UPDATE hal_authorships SET roles = ARRAY[role] WHERE role IS NOT NULL;
ALTER TABLE hal_authorships DROP COLUMN role;

-- WoS : role text → roles text[]
ALTER TABLE wos_authorships ADD COLUMN roles TEXT[];
UPDATE wos_authorships SET roles = ARRAY[role] WHERE role IS NOT NULL;
ALTER TABLE wos_authorships DROP COLUMN role;

-- ScanR : role text → roles text[]
ALTER TABLE scanr_authorships ADD COLUMN roles TEXT[];
UPDATE scanr_authorships SET roles = ARRAY[role] WHERE role IS NOT NULL;
ALTER TABLE scanr_authorships DROP COLUMN role;

-- OpenAlex : ajouter roles text[]
ALTER TABLE openalex_authorships ADD COLUMN roles TEXT[];

COMMIT;
