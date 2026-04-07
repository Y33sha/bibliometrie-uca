-- Ajouter ScanR à l'enum source_type
-- (la vue sera recréée dans la migration suivante, après COMMIT de l'enum)
ALTER TYPE source_type ADD VALUE IF NOT EXISTS 'scanr';
