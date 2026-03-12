-- =============================================================
-- SCHÉMA CIBLE — Bibliométrie UCA v2.2
-- =============================================================
--
-- Principes fondamentaux :
--
--   1. SÉPARATION DES SOURCES : les données de chaque source (HAL, OpenAlex,
--      WoS) vivent dans leurs propres tables et ne se mélangent jamais.
--
--   2. TABLES DE VÉRITÉ : publications, persons, structures, authorships
--      sont les entités canoniques. Elles sont alimentées par déduplication
--      et mapping depuis les tables source, jamais par insertion directe.
--
--   3. MAPPINGS, PAS FUSIONS : les liens source → vérité sont des FK
--      many-to-one. On ne crée jamais d'équivalence 1:1 entre un auteur HAL
--      et un auteur OpenAlex ; chacun pointe indépendamment vers persons.
--
--   4. CLÉS INTERNES : tous les identifiants primaires sont des SERIAL.
--      Les identifiants naturels (DOI, halId, openalex_id, hal_person_id)
--      sont en colonnes UNIQUE.
--
--   5. IDENTIFIANTS CERTIFIANTS : ORCID et idHAL certifient l'unicité d'une
--      personne. Ils sont stockés dans person_identifiers (many-to-one :
--      une personne peut avoir plusieurs ORCID ou idHAL, mais chaque
--      identifiant ne désigne qu'une personne).
--
-- =============================================================


BEGIN;

-- #############################################################
-- TYPES ÉNUMÉRÉS
-- #############################################################

CREATE TYPE source_type AS ENUM ('hal', 'openalex', 'wos');

CREATE TYPE doc_type AS ENUM (
    'article', 'conference_paper', 'book', 'book_chapter',
    'thesis', 'preprint', 'review', 'editorial', 'report', 'other'
);

CREATE TYPE oa_type AS ENUM (
    'gold', 'hybrid', 'bronze', 'green', 'closed', 'unknown'
);

CREATE TYPE structure_type AS ENUM (
    'universite', 'onr', 'chu', 'ecole', 'labo', 'equipe', 'site', 'autre'
);


-- #############################################################
-- 1. TABLES DE VÉRITÉ
-- #############################################################

-- =============================================================
-- 1a. STRUCTURES
-- =============================================================

CREATE TABLE structures (
    id              SERIAL PRIMARY KEY,
    code            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    acronym         TEXT,
    type            structure_type NOT NULL,
    ror_id          TEXT,
    rnsr_id         TEXT,
    hal_collection  TEXT,                        -- collection HAL associée (labos)
    domain          TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_structures_type ON structures (type);
CREATE INDEX idx_structures_ror ON structures (ror_id) WHERE ror_id IS NOT NULL;

CREATE TABLE structure_relations (
    id              SERIAL PRIMARY KEY,
    parent_id       INT NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
    child_id        INT NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
    relation_type   TEXT NOT NULL,
    UNIQUE (parent_id, child_id, relation_type)
);

CREATE INDEX idx_struct_rel_parent ON structure_relations (parent_id);
CREATE INDEX idx_struct_rel_child ON structure_relations (child_id);

CREATE TABLE name_forms (
    id                  SERIAL PRIMARY KEY,
    structure_id        INT NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
    form_text           TEXT NOT NULL,
    form_normalized     TEXT NOT NULL,
    is_regex            BOOLEAN DEFAULT FALSE,
    requires_context_of JSONB DEFAULT NULL,
    is_active           BOOLEAN DEFAULT TRUE,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_name_forms_structure ON name_forms (structure_id);
CREATE INDEX idx_name_forms_active ON name_forms (is_active) WHERE is_active = TRUE;


-- =============================================================
-- 1b. PERSONNES
-- =============================================================

CREATE TABLE persons (
    id                      SERIAL PRIMARY KEY,
    last_name               TEXT NOT NULL,
    first_name              TEXT NOT NULL,
    last_name_normalized    TEXT NOT NULL,
    first_name_normalized   TEXT NOT NULL,
    email                   TEXT,
    role_title              TEXT,
    department_name         TEXT,
    structure_id            INT REFERENCES structures(id) ON DELETE SET NULL,
    start_date              DATE,
    end_date                DATE,
    hr_export_date          DATE,
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_persons_name ON persons (last_name_normalized, first_name_normalized);
CREATE INDEX idx_persons_email ON persons (email) WHERE email IS NOT NULL;
CREATE INDEX idx_persons_structure ON persons (structure_id) WHERE structure_id IS NOT NULL;

CREATE TABLE person_identifiers (
    id          SERIAL PRIMARY KEY,
    person_id   INT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    id_type     TEXT NOT NULL,                   -- 'orcid', 'idhal', 'researcher_id', etc.
    id_value    TEXT NOT NULL,
    verified    BOOLEAN DEFAULT FALSE,
    source      TEXT,                            -- provenance : 'hr', 'hal', 'openalex', 'manual'
    created_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (id_type, id_value)
);

CREATE INDEX idx_person_ids_person ON person_identifiers (person_id);
CREATE INDEX idx_person_ids_lookup ON person_identifiers (id_type, id_value);


-- =============================================================
-- 1c. ÉDITEURS ET REVUES
-- =============================================================

CREATE TABLE publishers (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    openalex_id     TEXT UNIQUE,
    country         TEXT,
    is_predatory    BOOLEAN DEFAULT FALSE,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_publishers_name_norm ON publishers (name_normalized);

CREATE TABLE journals (
    id               SERIAL PRIMARY KEY,
    title            TEXT NOT NULL,
    title_normalized TEXT NOT NULL,
    issn             TEXT,
    eissn            TEXT,
    issnl            TEXT,
    publisher_id     INT REFERENCES publishers(id),
    openalex_id      TEXT UNIQUE,
    is_in_doaj       BOOLEAN DEFAULT FALSE,
    is_predatory     BOOLEAN DEFAULT FALSE,
    apc_amount       NUMERIC(10,2),
    apc_currency     TEXT DEFAULT 'EUR',
    oa_model         TEXT,
    notes            TEXT,
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_journals_issnl ON journals (issnl);
CREATE INDEX idx_journals_issn ON journals (issn);
CREATE INDEX idx_journals_eissn ON journals (eissn);
CREATE INDEX idx_journals_publisher ON journals (publisher_id);


-- =============================================================
-- 1d. PUBLICATIONS
-- =============================================================

CREATE TABLE publications (
    id                  SERIAL PRIMARY KEY,
    title               TEXT NOT NULL,
    title_normalized    TEXT,
    doc_type            doc_type DEFAULT 'other',
    pub_year            SMALLINT NOT NULL,
    doi                 TEXT UNIQUE,
    oa_status           oa_type DEFAULT 'unknown',
    journal_id          INT REFERENCES journals(id),
    container_title     TEXT,
    language            TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_publications_doi ON publications (doi);
CREATE INDEX idx_publications_year ON publications (pub_year);
CREATE INDEX idx_publications_journal ON publications (journal_id);
CREATE INDEX idx_publications_title_norm ON publications (title_normalized);


-- =============================================================
-- 1e. AUTHORSHIPS (vérité : personne × publication × structure)
-- =============================================================
-- Table de vérité construite à partir des authorships source
-- (hal_authorships, openalex_authorships) en résolvant les liens
-- auteur→personne et document→publication.
-- Permet aussi les ajouts manuels (authorship attesté mais absent
-- de toutes les sources) et la curation au niveau vérité.

CREATE TABLE authorships (
    id              SERIAL PRIMARY KEY,
    publication_id  INT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
    person_id       INT REFERENCES persons(id) ON DELETE SET NULL,     -- NULL si personne non encore identifiée
    structure_id    INT REFERENCES structures(id) ON DELETE SET NULL,  -- structure UCA (NULL si non UCA ou non résolu)
    author_position SMALLINT,
    is_uca          BOOLEAN DEFAULT FALSE,
    -- Traçabilité : FK vers les authorships sources
    hal_authorship_id     INT REFERENCES hal_authorships(id) ON DELETE SET NULL,
    openalex_authorship_id INT REFERENCES openalex_authorships(id) ON DELETE SET NULL,
    wos_authorship_id     INT REFERENCES wos_authorships(id) ON DELETE SET NULL,
    source_manual   BOOLEAN DEFAULT FALSE,       -- ajout manuel (non présent dans les sources)
    -- Curation
    excluded        BOOLEAN DEFAULT FALSE,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (publication_id, person_id, structure_id)
);

CREATE INDEX idx_authorships_pub ON authorships (publication_id);
CREATE INDEX idx_authorships_person ON authorships (person_id) WHERE person_id IS NOT NULL;
CREATE INDEX idx_authorships_struct ON authorships (structure_id) WHERE structure_id IS NOT NULL;
CREATE INDEX idx_authorships_uca ON authorships (is_uca) WHERE is_uca = TRUE;


-- #############################################################
-- 2. DONNÉES SOURCE — HAL
-- #############################################################

-- =============================================================
-- 2a. Staging HAL
-- =============================================================

CREATE TABLE staging_hal (
    id              SERIAL PRIMARY KEY,
    halid           TEXT NOT NULL UNIQUE,
    doi             TEXT,
    raw_data        JSONB NOT NULL,
    collection      TEXT,                        -- collection d'origine de la requête
    processed       BOOLEAN DEFAULT FALSE,
    imported_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_staging_hal_doi ON staging_hal (doi);
CREATE INDEX idx_staging_hal_processed ON staging_hal (processed) WHERE processed = FALSE;

-- =============================================================
-- 2b. Structures HAL
-- =============================================================

CREATE TABLE hal_structures (
    id              SERIAL PRIMARY KEY,
    hal_struct_id   INT NOT NULL UNIQUE,
    name            TEXT,
    acronym         TEXT,
    type            TEXT,
    valid           TEXT,
    start_date      DATE,
    end_date        DATE,
    code            TEXT,
    rnsr            TEXT,
    ror             TEXT,
    idref           TEXT,
    isni            TEXT,
    country         TEXT,
    address         TEXT,
    url             TEXT,
    alias_ids       INT[],
    parent_ids      INT[],
    parent_names    TEXT[],
    parent_acronyms TEXT[],
    parent_types    TEXT[],
    -- Lien vers vérité
    structure_id    INT REFERENCES structures(id) ON DELETE SET NULL,
    doc_count       INT DEFAULT 0,
    enriched_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_hal_struct_local ON hal_structures (structure_id) WHERE structure_id IS NOT NULL;
CREATE INDEX idx_hal_struct_type ON hal_structures (type);
CREATE INDEX idx_hal_struct_valid ON hal_structures (valid);
CREATE INDEX idx_hal_struct_parent_ids ON hal_structures USING GIN (parent_ids);
CREATE INDEX idx_hal_struct_alias_ids ON hal_structures USING GIN (alias_ids);

-- =============================================================
-- 2c. Auteurs HAL
-- =============================================================

CREATE TABLE hal_authors (
    id              SERIAL PRIMARY KEY,
    hal_person_id   INT UNIQUE,
    hal_form_id     INT,                         -- identifiant de forme HAL (déduplique les auteurs sans compte)
    full_name       TEXT NOT NULL,
    last_name       TEXT,
    first_name      TEXT,
    idhal           TEXT,
    orcid           TEXT,
    -- Lien vers vérité
    person_id       INT REFERENCES persons(id) ON DELETE SET NULL,
    is_reliable     BOOLEAN DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX idx_hal_authors_form_id ON hal_authors (hal_form_id) WHERE hal_form_id IS NOT NULL;
CREATE INDEX idx_hal_authors_person ON hal_authors (person_id) WHERE person_id IS NOT NULL;
CREATE INDEX idx_hal_authors_idhal ON hal_authors (idhal) WHERE idhal IS NOT NULL;
CREATE INDEX idx_hal_authors_orcid ON hal_authors (orcid) WHERE orcid IS NOT NULL;
CREATE INDEX idx_hal_authors_name ON hal_authors (last_name, first_name);

-- =============================================================
-- 2d. Documents HAL
-- =============================================================

CREATE TABLE hal_documents (
    id              SERIAL PRIMARY KEY,
    halid           TEXT NOT NULL UNIQUE,
    doi             TEXT,
    title           TEXT NOT NULL,
    pub_year        SMALLINT,
    doc_type        TEXT,
    collections     TEXT[],                      -- collections HAL contenant ce document
    -- Lien vers vérité
    publication_id  INT REFERENCES publications(id) ON DELETE SET NULL,
    staging_id      INT REFERENCES staging_hal(id),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_hal_docs_doi ON hal_documents (doi) WHERE doi IS NOT NULL;
CREATE INDEX idx_hal_docs_pub ON hal_documents (publication_id) WHERE publication_id IS NOT NULL;
CREATE INDEX idx_hal_docs_collections ON hal_documents USING GIN (collections);

-- =============================================================
-- 2e. Authorships HAL
-- =============================================================

CREATE TABLE hal_authorships (
    id                  SERIAL PRIMARY KEY,
    hal_document_id     INT NOT NULL REFERENCES hal_documents(id) ON DELETE CASCADE,
    hal_author_id       INT NOT NULL REFERENCES hal_authors(id) ON DELETE CASCADE,
    author_position     SMALLINT,
    hal_struct_ids      INT[],
    -- Résolution UCA (toutes les structures UCA détectées)
    is_uca              BOOLEAN DEFAULT FALSE,
    structure_ids       INT[],                   -- structures UCA résolues (via hal_structures.structure_id)
    excluded            BOOLEAN DEFAULT FALSE,
    UNIQUE (hal_document_id, hal_author_id)
);

CREATE INDEX idx_hal_as_doc ON hal_authorships (hal_document_id);
CREATE INDEX idx_hal_as_author ON hal_authorships (hal_author_id);
CREATE INDEX idx_hal_as_uca ON hal_authorships (is_uca) WHERE is_uca = TRUE;
CREATE INDEX idx_hal_as_structs ON hal_authorships USING GIN (structure_ids) WHERE structure_ids IS NOT NULL;


-- #############################################################
-- 3. DONNÉES SOURCE — OpenAlex
-- #############################################################

-- =============================================================
-- 3a. Staging OpenAlex
-- =============================================================

CREATE TABLE staging_openalex (
    id              SERIAL PRIMARY KEY,
    openalex_id     TEXT NOT NULL UNIQUE,
    doi             TEXT,
    raw_data        JSONB NOT NULL,
    processed       BOOLEAN DEFAULT FALSE,
    imported_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_staging_oa_doi ON staging_openalex (doi);
CREATE INDEX idx_staging_oa_processed ON staging_openalex (processed) WHERE processed = FALSE;

-- =============================================================
-- 3b. Institutions OpenAlex
-- =============================================================

CREATE TABLE openalex_institutions (
    id              SERIAL PRIMARY KEY,
    openalex_id     TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    ror_id          TEXT,
    country_code    TEXT,
    type            TEXT,
    -- Lien vers vérité
    structure_id    INT REFERENCES structures(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_oa_inst_struct ON openalex_institutions (structure_id) WHERE structure_id IS NOT NULL;
CREATE INDEX idx_oa_inst_ror ON openalex_institutions (ror_id) WHERE ror_id IS NOT NULL;

-- =============================================================
-- 3c. Auteurs OpenAlex
-- =============================================================

CREATE TABLE openalex_authors (
    id              SERIAL PRIMARY KEY,
    openalex_id     TEXT NOT NULL UNIQUE,
    full_name       TEXT NOT NULL,
    last_name       TEXT,
    first_name      TEXT,
    orcid           TEXT,
    -- Lien vers vérité
    person_id       INT REFERENCES persons(id) ON DELETE SET NULL,
    is_reliable     BOOLEAN DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_oa_authors_person ON openalex_authors (person_id) WHERE person_id IS NOT NULL;
CREATE INDEX idx_oa_authors_orcid ON openalex_authors (orcid) WHERE orcid IS NOT NULL;
CREATE INDEX idx_oa_authors_name ON openalex_authors (last_name, first_name);

-- =============================================================
-- 3d. Documents OpenAlex
-- =============================================================

CREATE TABLE openalex_documents (
    id              SERIAL PRIMARY KEY,
    openalex_id     TEXT NOT NULL UNIQUE,
    doi             TEXT,
    title           TEXT NOT NULL,
    pub_year        SMALLINT,
    doc_type        TEXT,
    -- Lien vers vérité
    publication_id  INT REFERENCES publications(id) ON DELETE SET NULL,
    staging_id      INT REFERENCES staging_openalex(id),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_oa_docs_doi ON openalex_documents (doi) WHERE doi IS NOT NULL;
CREATE INDEX idx_oa_docs_pub ON openalex_documents (publication_id) WHERE publication_id IS NOT NULL;

-- =============================================================
-- 3e. Authorships OpenAlex
-- =============================================================

CREATE TABLE openalex_authorships (
    id                      SERIAL PRIMARY KEY,
    openalex_document_id    INT NOT NULL REFERENCES openalex_documents(id) ON DELETE CASCADE,
    openalex_author_id      INT NOT NULL REFERENCES openalex_authors(id) ON DELETE CASCADE,
    author_position         SMALLINT,
    raw_affiliation         TEXT,
    openalex_institution_ids TEXT[],
    -- Résolution UCA
    is_uca                  BOOLEAN DEFAULT FALSE,
    structure_ids           INT[],
    excluded                BOOLEAN DEFAULT FALSE,
    UNIQUE (openalex_document_id, openalex_author_id)
);

CREATE INDEX idx_oa_as_doc ON openalex_authorships (openalex_document_id);
CREATE INDEX idx_oa_as_author ON openalex_authorships (openalex_author_id);
CREATE INDEX idx_oa_as_uca ON openalex_authorships (is_uca) WHERE is_uca = TRUE;
CREATE INDEX idx_oa_as_structs ON openalex_authorships USING GIN (structure_ids) WHERE structure_ids IS NOT NULL;


-- #############################################################
-- 4. ADRESSES D'AFFILIATION (source-agnostique)
-- #############################################################
-- Les adresses brutes et leur résolution en structures sont
-- indépendantes de la source. Chaque source qui fournit des adresses
-- a sa propre table de liaison authorship ↔ adresse.

CREATE TABLE addresses (
    id              SERIAL PRIMARY KEY,
    raw_text        TEXT NOT NULL UNIQUE,
    normalized_text TEXT NOT NULL,
    country         TEXT,
    review_status   TEXT DEFAULT 'pending',
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_addresses_status ON addresses (review_status);

CREATE TABLE address_structures (
    id              SERIAL PRIMARY KEY,
    address_id      INT NOT NULL REFERENCES addresses(id) ON DELETE CASCADE,
    structure_id    INT NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
    matched_form_id INT REFERENCES name_forms(id) ON DELETE SET NULL,
    is_confirmed    BOOLEAN DEFAULT FALSE,
    UNIQUE (address_id, structure_id)
);

CREATE INDEX idx_addr_struct_address ON address_structures (address_id);
CREATE INDEX idx_addr_struct_structure ON address_structures (structure_id);

-- Liaison authorship OpenAlex ↔ adresses
CREATE TABLE openalex_authorship_addresses (
    id                      SERIAL PRIMARY KEY,
    openalex_authorship_id  INT NOT NULL REFERENCES openalex_authorships(id) ON DELETE CASCADE,
    address_id              INT NOT NULL REFERENCES addresses(id) ON DELETE CASCADE,
    UNIQUE (openalex_authorship_id, address_id)
);

-- Liaison authorship WoS ↔ adresses
CREATE TABLE wos_authorship_addresses (
    id                  SERIAL PRIMARY KEY,
    wos_authorship_id   INT NOT NULL REFERENCES wos_authorships(id) ON DELETE CASCADE,
    address_id          INT NOT NULL REFERENCES addresses(id) ON DELETE CASCADE,
    UNIQUE (wos_authorship_id, address_id)
);


-- #############################################################
-- 5. DONNÉES SOURCE — WoS (préparé, vide)
-- #############################################################

CREATE TABLE staging_wos (
    id              SERIAL PRIMARY KEY,
    ut              TEXT NOT NULL UNIQUE,
    doi             TEXT,
    raw_data        JSONB NOT NULL,
    processed       BOOLEAN DEFAULT FALSE,
    imported_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_staging_wos_doi ON staging_wos (doi);

-- wos_authors, wos_documents, wos_authorships, wos_institutions :
-- à créer sur le même modèle que HAL / OpenAlex.


-- #############################################################
-- 6. TABLE LEGACY (migration temporaire)
-- #############################################################
-- Ancienne table `authors` renommée. Conservée temporairement pour
-- transférer les mappings person_id vers hal_authors et openalex_authors.
-- À supprimer une fois la migration terminée.
--
-- ALTER TABLE authors RENAME TO legacy_authors;
-- (exécuté dans le script de migration, pas ici)


-- #############################################################
-- 7. VUES
-- #############################################################

-- Sources par publication (déduit des FK dans les tables documents source)
CREATE VIEW publication_sources AS
    SELECT publication_id, 'hal'::source_type AS source, halid AS source_id
    FROM hal_documents WHERE publication_id IS NOT NULL
    UNION ALL
    SELECT publication_id, 'openalex'::source_type AS source, openalex_id AS source_id
    FROM openalex_documents WHERE publication_id IS NOT NULL
;


COMMIT;
