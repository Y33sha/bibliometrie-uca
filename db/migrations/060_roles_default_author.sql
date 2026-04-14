-- Migration 060 : rôle 'author' par défaut sur source_authorships.roles
-- Les sources non-theses n'ont pas de rôle explicite, mais sont toujours
-- des auteurs au sens classique. Évite que roles IS NULL fasse échouer
-- les filtres sa.roles && ARRAY['author'].

-- Défaut pour les nouveaux inserts
ALTER TABLE source_authorships ALTER COLUMN roles SET DEFAULT ARRAY['author']::text[];

-- Remplir les NULL existants
UPDATE source_authorships SET roles = ARRAY['author']::text[]
WHERE roles IS NULL;
