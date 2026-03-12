-- Migration 024 : Remplacer les booléens source_hal/source_openalex/source_wos
-- par des FK vers les tables authorships sources.
--
-- Avantages :
--   - Traçabilité : lien direct vers l'authorship source
--   - Requêtes simplifiées : plus de join via (publication_id, person_id)
--   - Diagnostic inter-sources : comparaison directe des affiliations

BEGIN;

-- ── 1. Ajouter les colonnes FK ──

ALTER TABLE authorships
    ADD COLUMN IF NOT EXISTS hal_authorship_id INT
        REFERENCES hal_authorships(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS openalex_authorship_id INT
        REFERENCES openalex_authorships(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS wos_authorship_id INT
        REFERENCES wos_authorships(id) ON DELETE SET NULL;

-- ── 2. Peupler depuis les données existantes ──

-- 2a. HAL
UPDATE authorships a
SET hal_authorship_id = sub.has_id
FROM (
    SELECT DISTINCT ON (hd.publication_id, ha.person_id)
           hd.publication_id, ha.person_id, has.id AS has_id
    FROM hal_authorships has
    JOIN hal_documents hd ON hd.id = has.hal_document_id
    JOIN hal_authors ha ON ha.id = has.hal_author_id
    WHERE hd.publication_id IS NOT NULL
      AND ha.person_id IS NOT NULL
    ORDER BY hd.publication_id, ha.person_id, has.id
) sub
WHERE a.publication_id = sub.publication_id
  AND a.person_id = sub.person_id
  AND a.source_hal = TRUE;

-- 2b. OpenAlex
UPDATE authorships a
SET openalex_authorship_id = sub.oas_id
FROM (
    SELECT DISTINCT ON (od.publication_id, oa.person_id)
           od.publication_id, oa.person_id, oas.id AS oas_id
    FROM openalex_authorships oas
    JOIN openalex_documents od ON od.id = oas.openalex_document_id
    JOIN openalex_authors oa ON oa.id = oas.openalex_author_id
    WHERE od.publication_id IS NOT NULL
      AND oa.person_id IS NOT NULL
    ORDER BY od.publication_id, oa.person_id, oas.id
) sub
WHERE a.publication_id = sub.publication_id
  AND a.person_id = sub.person_id
  AND a.source_openalex = TRUE;

-- 2c. WoS
UPDATE authorships a
SET wos_authorship_id = sub.was_id
FROM (
    SELECT DISTINCT ON (wd.publication_id, wa.person_id)
           wd.publication_id, wa.person_id, was.id AS was_id
    FROM wos_authorships was
    JOIN wos_documents wd ON wd.id = was.wos_document_id
    JOIN wos_authors wa ON wa.id = was.wos_author_id
    WHERE wd.publication_id IS NOT NULL
      AND wa.person_id IS NOT NULL
    ORDER BY wd.publication_id, wa.person_id, was.id
) sub
WHERE a.publication_id = sub.publication_id
  AND a.person_id = sub.person_id
  AND a.source_wos = TRUE;

-- ── 3. Supprimer les anciens booléens ──

ALTER TABLE authorships
    DROP COLUMN source_hal,
    DROP COLUMN source_openalex,
    DROP COLUMN source_wos;

-- ── 4. Index pour les FK ──

CREATE INDEX IF NOT EXISTS idx_authorships_hal_as ON authorships(hal_authorship_id) WHERE hal_authorship_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_authorships_oa_as ON authorships(openalex_authorship_id) WHERE openalex_authorship_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_authorships_wos_as ON authorships(wos_authorship_id) WHERE wos_authorship_id IS NOT NULL;

COMMIT;
