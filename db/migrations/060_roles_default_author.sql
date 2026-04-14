-- Migration 060 : rôle 'author' par défaut sur source_authorships.roles
-- Les sources non-theses n'ont pas de rôle explicite, mais sont toujours
-- des auteurs au sens classique. Évite que roles IS NULL fasse échouer
-- les filtres sa.roles && ARRAY['author'].

-- Défaut pour les nouveaux inserts (instantané, pas de verrou)
ALTER TABLE source_authorships ALTER COLUMN roles SET DEFAULT ARRAY['author']::text[];

-- Le backfill des NULL existants est fait par db/backfill_060.py
-- (trop volumineux pour un UPDATE unique dans une migration).
