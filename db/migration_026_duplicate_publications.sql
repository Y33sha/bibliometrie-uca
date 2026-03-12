-- Migration 026 : Détection des doublons de publications cross-source
-- Table pour marquer des paires comme distinctes + vue matérialisée des candidats

BEGIN;

-- 1. Table des paires confirmées comme distinctes
CREATE TABLE distinct_publications (
    id          SERIAL PRIMARY KEY,
    pub_id_a    INT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
    pub_id_b    INT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT distinct_pubs_ordered CHECK (pub_id_a < pub_id_b),
    UNIQUE (pub_id_a, pub_id_b)
);
CREATE INDEX idx_distinct_pubs_a ON distinct_publications (pub_id_a);
CREATE INDEX idx_distinct_pubs_b ON distinct_publications (pub_id_b);

-- 2. Index trigram sur title_normalized (nécessaire pour l'opérateur %)
CREATE INDEX IF NOT EXISTS idx_pub_title_trgm
    ON publications USING GIN (title_normalized gin_trgm_ops);

COMMIT;

-- 3. Vue matérialisée (hors transaction pour permettre CONCURRENTLY plus tard)
CREATE MATERIALIZED VIEW duplicate_candidates AS
WITH pub_sources AS (
    SELECT p.id AS pub_id, p.title_normalized, p.doi, p.pub_year, p.doc_type,
           EXISTS (SELECT 1 FROM hal_documents hd WHERE hd.publication_id = p.id) AS has_hal,
           EXISTS (SELECT 1 FROM openalex_documents od WHERE od.publication_id = p.id) AS has_oa,
           EXISTS (SELECT 1 FROM wos_documents wd WHERE wd.publication_id = p.id) AS has_wos
    FROM publications p
    WHERE p.title_normalized IS NOT NULL AND p.title_normalized <> ''
)
SELECT LEAST(a.pub_id, b.pub_id) AS pub_id_a,
       GREATEST(a.pub_id, b.pub_id) AS pub_id_b,
       similarity(a.title_normalized, b.title_normalized) AS title_sim
FROM pub_sources a
JOIN pub_sources b
  ON a.pub_id < b.pub_id
 AND ABS(a.pub_year - b.pub_year) <= 1
 AND a.title_normalized % b.title_normalized
WHERE
    NOT (a.has_hal AND b.has_hal)
    AND NOT (a.has_oa AND b.has_oa)
    AND NOT (a.has_wos AND b.has_wos)
    AND NOT (a.doi IS NOT NULL AND b.doi IS NOT NULL AND a.doi = b.doi)
    AND (a.doc_type IS NULL OR b.doc_type IS NULL OR a.doc_type = b.doc_type)
    AND similarity(a.title_normalized, b.title_normalized) >= 0.4
    AND NOT EXISTS (
        SELECT 1 FROM distinct_publications dp
        WHERE dp.pub_id_a = LEAST(a.pub_id, b.pub_id)
          AND dp.pub_id_b = GREATEST(a.pub_id, b.pub_id)
    )
;

CREATE UNIQUE INDEX ON duplicate_candidates (pub_id_a, pub_id_b);
CREATE INDEX ON duplicate_candidates (title_sim DESC);
