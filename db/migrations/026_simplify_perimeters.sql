-- Migration 026 : Simplifier les périmètres
--
-- Remplace la table perimeter_rules par une colonne structure_ids
-- directement sur perimeters. La récursion sur les enfants est
-- toujours implicite.

-- 1. Migrer les données
ALTER TABLE perimeters ADD COLUMN IF NOT EXISTS structure_ids integer[] NOT NULL DEFAULT '{}';

UPDATE perimeters p SET structure_ids = COALESCE(sub.ids, '{}')
FROM (
    SELECT perimeter_id, array_agg(structure_id ORDER BY structure_id) AS ids
    FROM perimeter_rules
    GROUP BY perimeter_id
) sub
WHERE p.id = sub.perimeter_id;

-- 2. Supprimer la table de liaison
DROP TABLE IF EXISTS perimeter_rules;
