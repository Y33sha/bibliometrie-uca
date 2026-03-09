-- =============================================================
-- Migration 006 : Index de performance pour la normalisation
-- 
-- Ces index accélèrent considérablement la normalisation HAL
-- (lookup auteurs, publications, revues par nom normalisé).
-- Sans eux, le traitement passe de ~30s/50 works à <1s/50.
-- =============================================================

BEGIN;

-- Auteurs : lookup par full_name (utilisé dans upsert_author)
CREATE INDEX IF NOT EXISTS idx_authors_fullname
    ON authors (full_name);

-- Auteurs : lookup composite full_name + first_name (IS NOT DISTINCT FROM)
CREATE INDEX IF NOT EXISTS idx_authors_fullname_firstname
    ON authors (full_name, first_name);

-- Auteurs : lookup par idHAL
CREATE INDEX IF NOT EXISTS idx_authors_idhal
    ON authors (idhal);

-- Publications : dédoublonnage par titre normalisé + année
CREATE INDEX IF NOT EXISTS idx_publications_titlenorm_year
    ON publications (title_normalized, pub_year);

-- Journals : lookup par titre normalisé (fallback quand pas d'ISSN)
CREATE INDEX IF NOT EXISTS idx_journals_titlenorm
    ON journals (title_normalized);

-- Publication_authors : accélérer resolve_laboratories (filtre partiel)
CREATE INDEX IF NOT EXISTS idx_pubauthors_pubid_source
    ON publication_authors (publication_id, source)
    WHERE laboratory_id IS NULL;

COMMIT;
