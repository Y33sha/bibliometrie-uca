-- Exclure les memoires de la vue des publications actives.
-- Empeche la creation de personnes a partir d'authorships sur des memoires.

CREATE OR REPLACE VIEW v_active_publications AS
SELECT id FROM publications WHERE doc_type NOT IN ('peer_review', 'memoir');
