-- Index partiel pour accelerer la requete des orphan authorships
-- (source_authorships sans person_id, in_perimeter).
-- Reduit le temps de reponse de ~3.5s a ~0.2s.

CREATE INDEX IF NOT EXISTS idx_sa_orphan_perimeter
ON source_authorships (source_document_id, source_author_id)
WHERE person_id IS NULL AND in_perimeter = TRUE;
