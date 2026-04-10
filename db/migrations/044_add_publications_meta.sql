-- Migration 044 : Ajout du champ meta JSONB sur publications
--
-- Champ extensible pour les métadonnées spécifiques à certains doc_types.
-- Exemple pour les thèses : {"date_soutenance": "2024-03-15", "date_inscription": "2021-09-01"}

ALTER TABLE publications ADD COLUMN IF NOT EXISTS meta JSONB;

CREATE INDEX IF NOT EXISTS idx_publications_meta ON publications USING gin (meta) WHERE (meta IS NOT NULL);

-- Peupler les dates de thèse depuis le staging theses.fr
UPDATE publications p
SET meta = jsonb_build_object(
    'date_soutenance',
    CASE WHEN st.raw_data->>'dateSoutenance' IS NOT NULL
         THEN to_char(to_date(st.raw_data->>'dateSoutenance', 'DD/MM/YYYY'), 'YYYY-MM-DD')
    END,
    'date_inscription',
    CASE WHEN st.raw_data->>'datePremiereInscriptionDoctorat' IS NOT NULL
         THEN to_char(to_date(st.raw_data->>'datePremiereInscriptionDoctorat', 'DD/MM/YYYY'), 'YYYY-MM-DD')
    END
)
FROM source_documents sd
JOIN staging st ON st.id = sd.staging_id
WHERE sd.publication_id = p.id
  AND sd.source = 'theses'
  AND (st.raw_data->>'dateSoutenance' IS NOT NULL
       OR st.raw_data->>'datePremiereInscriptionDoctorat' IS NOT NULL);
