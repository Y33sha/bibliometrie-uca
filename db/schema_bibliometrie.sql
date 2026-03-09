-- =============================================================
-- Schéma bibliométrie UCA
-- Analyse des publications par labo, revue et éditeur (2022-2025)
-- =============================================================

BEGIN;

-- ----- Types énumérés -----

CREATE TYPE source_type AS ENUM ('hal', 'openalex', 'wos');

CREATE TYPE doc_type AS ENUM (
    'article',          -- article de revue
    'conference_paper', -- communication / acte de conférence
    'book',             -- ouvrage
    'book_chapter',     -- chapitre d'ouvrage
    'thesis',           -- thèse
    'preprint',         -- prépublication
    'review',           -- article de synthèse
    'editorial',        -- éditorial
    'report',           -- rapport
    'other'
);

CREATE TYPE oa_type AS ENUM (
    'gold',       -- revue full OA
    'hybrid',     -- revue hybride, article en OA
    'bronze',     -- libre à lire mais pas de licence ouverte
    'green',      -- dépôt en archive ouverte uniquement
    'closed',     -- accès fermé
    'unknown'
);


-- =============================================================
-- TABLES DE RÉFÉRENCE
-- =============================================================

-- ----- Éditeurs -----
CREATE TABLE publishers (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    name_normalized TEXT NOT NULL,       -- nom en minuscules, sans ponctuation, pour matching
    openalex_id     TEXT UNIQUE,         -- ex: P4310320990
    country         TEXT,
    is_predatory    BOOLEAN DEFAULT FALSE,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_publishers_name_norm ON publishers (name_normalized);

-- ----- Revues / Sources -----
CREATE TABLE journals (
    id              SERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    title_normalized TEXT NOT NULL,
    issn            TEXT,                -- ISSN print
    eissn           TEXT,                -- ISSN électronique
    issnl           TEXT,                -- ISSN-L (linking), pivot pour alignement inter-sources
    publisher_id    INT REFERENCES publishers(id),
    openalex_id     TEXT UNIQUE,         -- ex: S4210231900
    is_in_doaj      BOOLEAN DEFAULT FALSE,
    is_predatory    BOOLEAN DEFAULT FALSE,
    apc_amount      NUMERIC(10,2),       -- montant APC en EUR (ou devise à préciser)
    apc_currency    TEXT DEFAULT 'EUR',
    oa_model        TEXT,                -- 'full_oa', 'hybrid', 'subscription'
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_journals_issnl ON journals (issnl);
CREATE INDEX idx_journals_issn ON journals (issn);
CREATE INDEX idx_journals_eissn ON journals (eissn);
CREATE INDEX idx_journals_publisher ON journals (publisher_id);

-- ----- Laboratoires UCA -----
CREATE TABLE laboratories (
    id              SERIAL PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE, -- ex: UMR 6602
    name            TEXT NOT NULL,        -- ex: Institut Pascal
    acronym         TEXT,                 -- ex: IP
    hal_collection  TEXT,                 -- identifiant de collection HAL, ex: INSTITUT-PASCAL
    domain          TEXT,                 -- grande discipline, ex: 'Sciences de l ingénieur'
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);


-- =============================================================
-- TABLES PRINCIPALES
-- =============================================================

-- ----- Publications (table unifiée) -----
CREATE TABLE publications (
    id              SERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    title_normalized TEXT,               -- pour dédoublonnage fuzzy
    doc_type        doc_type DEFAULT 'other',
    pub_year        SMALLINT NOT NULL,
    doi             TEXT UNIQUE,          -- pivot principal pour dédoublonnage
    oa_status       oa_type DEFAULT 'unknown',
    journal_id      INT REFERENCES journals(id),
    -- pour les chapitres / actes : titre du contenant si pas dans journals
    container_title TEXT,
    language        TEXT,                -- code langue ISO 639-1
    is_validated    BOOLEAN DEFAULT FALSE, -- passe le filtre affiliation UCA ?
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_publications_doi ON publications (doi);
CREATE INDEX idx_publications_year ON publications (pub_year);
CREATE INDEX idx_publications_journal ON publications (journal_id);
CREATE INDEX idx_publications_title_norm ON publications (title_normalized);

-- ----- Lien publication ↔ sources d'extraction -----
-- Une publication peut venir de 1 à 3 sources
CREATE TABLE publication_sources (
    id              SERIAL PRIMARY KEY,
    publication_id  INT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
    source          source_type NOT NULL,
    source_id       TEXT NOT NULL,        -- HAL: halId, OpenAlex: work id, WoS: UT
    raw_doc_type    TEXT,                 -- type de doc tel que donné par la source
    raw_title       TEXT,                 -- titre brut de la source (pour traçabilité)
    raw_json        JSONB,               -- métadonnées brutes complètes (optionnel)
    imported_at     TIMESTAMPTZ DEFAULT now(),
    UNIQUE (source, source_id)
);

CREATE INDEX idx_pubsources_publication ON publication_sources (publication_id);
CREATE INDEX idx_pubsources_source ON publication_sources (source, source_id);


-- =============================================================
-- AUTEURS ET AFFILIATIONS
-- =============================================================

-- ----- Auteurs (personnes uniques) -----
CREATE TABLE authors (
    id              SERIAL PRIMARY KEY,
    last_name       TEXT NOT NULL,
    first_name      TEXT,
    full_name       TEXT NOT NULL,        -- forme affichée
    orcid           TEXT UNIQUE,
    idhal           TEXT UNIQUE,
    openalex_id     TEXT UNIQUE,
    is_uca          BOOLEAN DEFAULT FALSE, -- auteur affilié UCA (au moins sur la période)
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_authors_orcid ON authors (orcid);
CREATE INDEX idx_authors_name ON authors (last_name, first_name);

-- ----- Lien publication ↔ auteur ↔ affiliation -----
CREATE TABLE publication_authors (
    id              SERIAL PRIMARY KEY,
    publication_id  INT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
    author_id       INT NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    author_position SMALLINT,            -- rang dans la liste d'auteurs
    is_corresponding BOOLEAN DEFAULT FALSE,
    -- Affiliation brute (variable selon la source)
    raw_affiliation TEXT,
    source          source_type,         -- d'où vient cette info d'affiliation
    -- Affiliation résolue
    is_uca_author   BOOLEAN DEFAULT FALSE, -- cet auteur est-il UCA *sur cette publi* ?
    laboratory_id   INT REFERENCES laboratories(id),
    affiliation_resolved_at TIMESTAMPTZ,
    UNIQUE (publication_id, author_id, source)  -- un auteur par publi par source
);

CREATE INDEX idx_pubauthors_publication ON publication_authors (publication_id);
CREATE INDEX idx_pubauthors_author ON publication_authors (author_id);
CREATE INDEX idx_pubauthors_lab ON publication_authors (laboratory_id);


-- =============================================================
-- TABLES DE STAGING (import brut par source)
-- =============================================================
-- Structure volontairement souple (JSONB) pour absorber les formats variés.
-- Ces tables servent de zone de transit avant normalisation.

CREATE TABLE staging_hal (
    id              SERIAL PRIMARY KEY,
    halid           TEXT NOT NULL UNIQUE,
    doi             TEXT,
    raw_data        JSONB NOT NULL,       -- réponse API HAL complète
    collection      TEXT,                 -- collection HAL d'origine
    processed       BOOLEAN DEFAULT FALSE,
    imported_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE staging_openalex (
    id              SERIAL PRIMARY KEY,
    openalex_id     TEXT NOT NULL UNIQUE,
    doi             TEXT,
    raw_data        JSONB NOT NULL,       -- réponse API OpenAlex complète
    processed       BOOLEAN DEFAULT FALSE,
    imported_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE staging_wos (
    id              SERIAL PRIMARY KEY,
    ut              TEXT NOT NULL UNIQUE,  -- WoS Unique Title (UT)
    doi             TEXT,
    raw_data        JSONB NOT NULL,
    processed       BOOLEAN DEFAULT FALSE,
    imported_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_staging_hal_doi ON staging_hal (doi);
CREATE INDEX idx_staging_oa_doi ON staging_openalex (doi);
CREATE INDEX idx_staging_wos_doi ON staging_wos (doi);


-- =============================================================
-- VUES UTILITAIRES
-- =============================================================

-- Publications validées UCA avec revue et éditeur
CREATE VIEW v_publications_full AS
SELECT
    p.id,
    p.title,
    p.doc_type,
    p.pub_year,
    p.doi,
    p.oa_status,
    j.title       AS journal_title,
    j.issnl,
    j.apc_amount,
    j.apc_currency,
    j.is_predatory AS journal_predatory,
    pub.name      AS publisher_name,
    pub.is_predatory AS publisher_predatory,
    array_agg(DISTINCT ps.source) AS sources
FROM publications p
LEFT JOIN journals j ON j.id = p.journal_id
LEFT JOIN publishers pub ON pub.id = j.publisher_id
LEFT JOIN publication_sources ps ON ps.publication_id = p.id
WHERE p.is_validated = TRUE
GROUP BY p.id, j.id, pub.id;

-- Comptage publications par labo, année, éditeur
CREATE VIEW v_stats_labo_publisher AS
SELECT
    l.code        AS lab_code,
    l.name        AS lab_name,
    p.pub_year,
    pub.name      AS publisher_name,
    COUNT(DISTINCT p.id) AS nb_publications,
    COUNT(DISTINCT p.id) FILTER (WHERE j.is_predatory OR pub.is_predatory) AS nb_predatory,
    SUM(j.apc_amount) FILTER (WHERE p.oa_status IN ('gold', 'hybrid')) AS estimated_apc_total
FROM publications p
JOIN publication_authors pa ON pa.publication_id = p.id
JOIN laboratories l ON l.id = pa.laboratory_id
LEFT JOIN journals j ON j.id = p.journal_id
LEFT JOIN publishers pub ON pub.id = j.publisher_id
WHERE p.is_validated = TRUE
  AND pa.is_uca_author = TRUE
GROUP BY l.code, l.name, p.pub_year, pub.name;

-- Comptage publications par labo, année, revue
CREATE VIEW v_stats_labo_journal AS
SELECT
    l.code        AS lab_code,
    l.name        AS lab_name,
    p.pub_year,
    j.title       AS journal_title,
    j.issnl,
    pub.name      AS publisher_name,
    j.is_predatory AS journal_predatory,
    j.apc_amount,
    COUNT(DISTINCT p.id) AS nb_publications,
    SUM(j.apc_amount) FILTER (WHERE p.oa_status IN ('gold', 'hybrid')) AS estimated_apc_total
FROM publications p
JOIN publication_authors pa ON pa.publication_id = p.id
JOIN laboratories l ON l.id = pa.laboratory_id
LEFT JOIN journals j ON j.id = p.journal_id
LEFT JOIN publishers pub ON pub.id = j.publisher_id
WHERE p.is_validated = TRUE
  AND pa.is_uca_author = TRUE
GROUP BY l.code, l.name, p.pub_year, j.id, j.title, j.issnl, pub.name, j.is_predatory, j.apc_amount;

COMMIT;
