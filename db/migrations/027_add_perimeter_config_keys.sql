-- Migration 027 : Clés config pour l'association phase→périmètre
--
-- Permet de configurer quel périmètre est utilisé par chaque phase
-- du pipeline, au lieu d'un code hardcodé.

INSERT INTO config (key, value, description) VALUES
    ('perimeter_affiliations', '"uca_wide"',
     'Périmètre pour la résolution des affiliations (structure_ids sur authorships sources)'),
    ('perimeter_persons', '"uca"',
     'Périmètre pour la création des personnes (authorships is_uca)')
ON CONFLICT (key) DO NOTHING;
