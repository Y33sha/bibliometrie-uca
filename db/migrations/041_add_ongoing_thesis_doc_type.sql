-- Ajouter le type de document "thèse en cours" à l'enum doc_type
ALTER TYPE doc_type ADD VALUE IF NOT EXISTS 'ongoing_thesis' AFTER 'thesis';
