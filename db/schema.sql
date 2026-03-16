-- Schema consolidé publisher_stats
-- Généré depuis la base de données le 2026-03-12
-- Remplace les migrations 002-028 + schema_target_v2.sql

-- ============================================================
-- Extensions
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;

CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;

-- ============================================================
-- Types énumérés
-- ============================================================

CREATE TYPE doc_type AS ENUM (
    'article',
    'conference_paper',
    'book',
    'book_chapter',
    'thesis',
    'preprint',
    'review',
    'editorial',
    'report',
    'peer_review',
    'other'
);

CREATE TYPE identifier_status AS ENUM (
    'pending',
    'confirmed',
    'rejected'
);

CREATE TYPE oa_type AS ENUM (
    'gold',
    'hybrid',
    'bronze',
    'green',
    'closed',
    'unknown',
    'diamond'
);

CREATE TYPE source_type AS ENUM (
    'hal',
    'openalex',
    'wos'
);

CREATE TYPE structure_type AS ENUM (
    'universite',
    '__epst_deprecated',
    'chu',
    'ecole',
    'labo',
    'equipe',
    'site',
    'autre',
    'onr'
);

-- ============================================================
-- Tables
-- ============================================================

CREATE TABLE address_structures (
    id SERIAL,
    address_id integer NOT NULL,
    structure_id integer NOT NULL,
    matched_form_id integer,
    is_confirmed boolean
);

CREATE TABLE addresses (
    id SERIAL,
    raw_text text NOT NULL,
    normalized_text text CONSTRAINT addresses_raw_text_normalized_not_null NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    review_status text,
    country text,
    pub_count integer DEFAULT 0
);

CREATE TABLE authorships (
    id SERIAL,
    publication_id integer NOT NULL,
    person_id integer,
    author_position smallint,
    is_uca boolean DEFAULT false,
    source_manual boolean DEFAULT false,
    excluded boolean DEFAULT false,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    structure_ids integer[],
    is_corresponding boolean,
    hal_authorship_id integer,
    openalex_authorship_id integer,
    wos_authorship_id integer
);

CREATE TABLE distinct_persons (
    id SERIAL,
    person_id_a integer NOT NULL,
    person_id_b integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT distinct_persons_ordered CHECK ((person_id_a < person_id_b))
);

CREATE TABLE distinct_publications (
    id SERIAL,
    pub_id_a integer NOT NULL,
    pub_id_b integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT distinct_pubs_ordered CHECK ((pub_id_a < pub_id_b))
);

CREATE TABLE hal_authors (
    id SERIAL,
    hal_person_id integer,
    full_name text NOT NULL,
    last_name text,
    first_name text,
    idhal text,
    orcid text,
    person_id integer,
    is_reliable boolean DEFAULT true,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    hal_form_id integer
);

CREATE TABLE hal_authorships (
    id SERIAL,
    hal_document_id integer NOT NULL,
    hal_author_id integer NOT NULL,
    author_position smallint,
    hal_struct_ids integer[],
    is_uca boolean DEFAULT false,
    excluded boolean DEFAULT false,
    structure_ids integer[]
);

CREATE TABLE hal_documents (
    id SERIAL,
    halid text NOT NULL,
    doi text,
    title text NOT NULL,
    pub_year smallint,
    doc_type text,
    collections text[],
    publication_id integer,
    staging_id integer,
    created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE hal_structures (
    hal_struct_id integer NOT NULL,
    name text,
    acronym text,
    type text,
    parent_ids integer[],
    parent_names text[],
    structure_id integer,
    doc_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    start_date date,
    end_date date,
    valid text,
    rnsr text,
    ror text,
    idref text,
    isni text,
    code text,
    country text,
    address text,
    url text,
    alias_ids integer[],
    parent_acronyms text[],
    parent_types text[],
    enriched_at timestamp with time zone,
    id SERIAL
);

CREATE TABLE journals (
    id SERIAL,
    title text NOT NULL,
    title_normalized text NOT NULL,
    issn text,
    eissn text,
    issnl text,
    publisher_id integer,
    openalex_id text,
    is_in_doaj boolean DEFAULT false,
    is_predatory boolean DEFAULT false,
    apc_amount numeric(10,2),
    apc_currency text DEFAULT 'EUR'::text,
    oa_model text,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE name_forms (
    id SERIAL,
    structure_id integer NOT NULL,
    form_text text NOT NULL,
    form_normalized text NOT NULL,
    is_regex boolean DEFAULT false,
    requires_context_of jsonb,
    is_active boolean DEFAULT true,
    notes text,
    created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE openalex_authors (
    id SERIAL,
    openalex_id text,
    full_name text NOT NULL,
    last_name text,
    first_name text,
    orcid text,
    person_id integer,
    is_reliable boolean DEFAULT true,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE openalex_authorship_addresses (
    id SERIAL,
    openalex_authorship_id integer NOT NULL,
    address_id integer NOT NULL
);

CREATE TABLE openalex_authorships (
    id SERIAL,
    openalex_document_id integer NOT NULL,
    openalex_author_id integer NOT NULL,
    author_position smallint,
    raw_affiliation text,
    openalex_institution_ids text[],
    is_uca boolean DEFAULT false,
    excluded boolean DEFAULT false,
    structure_ids integer[],
    raw_author_name text,
    raw_orcid text
);

CREATE TABLE openalex_documents (
    id SERIAL,
    openalex_id text NOT NULL,
    doi text,
    title text NOT NULL,
    pub_year smallint,
    doc_type text,
    publication_id integer,
    staging_id integer,
    created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE openalex_institutions (
    id SERIAL,
    openalex_id text NOT NULL,
    name text NOT NULL,
    ror_id text,
    country_code text,
    type text,
    structure_id integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE person_identifiers (
    id SERIAL,
    person_id integer NOT NULL,
    id_type text NOT NULL,
    id_value text NOT NULL,
    source text,
    created_at timestamp with time zone DEFAULT now(),
    status identifier_status DEFAULT 'pending'::identifier_status NOT NULL
);

CREATE TABLE persons (
    id SERIAL,
    last_name text NOT NULL,
    first_name text NOT NULL,
    last_name_normalized text NOT NULL,
    first_name_normalized text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE persons_rh (
    id SERIAL,
    person_id integer NOT NULL,
    email text,
    role_title text,
    department_name text,
    structure_id integer,
    start_date date,
    end_date date,
    hr_export_date date,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE wos_documents (
    id SERIAL,
    ut text NOT NULL,
    doi text,
    title text NOT NULL,
    pub_year smallint,
    doc_type text,
    publication_id integer,
    staging_id integer,
    created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE publications (
    id SERIAL,
    title text NOT NULL,
    title_normalized text,
    doc_type doc_type DEFAULT 'other'::doc_type,
    pub_year smallint NOT NULL,
    doi text,
    oa_status oa_type DEFAULT 'unknown'::oa_type,
    journal_id integer,
    container_title text,
    language text,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    review_status text
);

CREATE TABLE publishers (
    id SERIAL,
    name text NOT NULL,
    name_normalized text NOT NULL,
    openalex_id text,
    country text,
    is_predatory boolean DEFAULT false,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE staging_hal (
    id SERIAL,
    halid text NOT NULL,
    doi text,
    raw_data jsonb NOT NULL,
    collection text,
    processed boolean DEFAULT false,
    imported_at timestamp with time zone DEFAULT now(),
    raw_hash text
);

CREATE TABLE staging_openalex (
    id SERIAL,
    openalex_id text NOT NULL,
    doi text,
    raw_data jsonb NOT NULL,
    processed boolean DEFAULT false,
    imported_at timestamp with time zone DEFAULT now(),
    raw_hash text
);

CREATE TABLE staging_wos (
    id SERIAL,
    ut text NOT NULL,
    doi text,
    raw_data jsonb NOT NULL,
    processed boolean DEFAULT false,
    imported_at timestamp with time zone DEFAULT now()
);

CREATE TABLE structure_relations (
    id SERIAL,
    parent_id integer NOT NULL,
    child_id integer NOT NULL,
    relation_type text NOT NULL
);

CREATE TABLE structures (
    id SERIAL,
    code text NOT NULL,
    name text NOT NULL,
    acronym text,
    type structure_type NOT NULL,
    ror_id text,
    rnsr_id text,
    hal_collection text,
    created_at timestamp with time zone DEFAULT now()
);

CREATE TABLE wos_authors (
    id SERIAL,
    full_name text NOT NULL,
    last_name text,
    first_name text,
    daisng_id text,
    orcid text,
    researcher_id text,
    person_id integer,
    is_reliable boolean DEFAULT true,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);

CREATE TABLE wos_authorship_addresses (
    id SERIAL,
    wos_authorship_id integer NOT NULL,
    address_id integer NOT NULL
);

CREATE TABLE wos_authorships (
    id SERIAL,
    wos_document_id integer NOT NULL,
    wos_author_id integer NOT NULL,
    author_position smallint,
    is_corresponding boolean DEFAULT false,
    raw_affiliation text,
    is_uca boolean DEFAULT false,
    excluded boolean DEFAULT false,
    structure_ids integer[]
);

-- ============================================================
-- Index
-- ============================================================

CREATE INDEX idx_addr_struct_address ON address_structures USING btree (address_id);

CREATE INDEX idx_addr_struct_filter ON address_structures USING btree (structure_id, address_id) INCLUDE (matched_form_id, is_confirmed);

CREATE INDEX idx_addr_struct_structure ON address_structures USING btree (structure_id);

CREATE INDEX idx_addresses_normalized ON addresses USING btree (normalized_text);

CREATE INDEX idx_authorships_corresponding_uca ON authorships USING btree (publication_id) WHERE ((is_corresponding = true) AND (is_uca = true));

CREATE INDEX idx_authorships_hal_as ON authorships USING btree (hal_authorship_id) WHERE (hal_authorship_id IS NOT NULL);

CREATE INDEX idx_authorships_oa_as ON authorships USING btree (openalex_authorship_id) WHERE (openalex_authorship_id IS NOT NULL);

CREATE INDEX idx_authorships_person ON authorships USING btree (person_id) WHERE (person_id IS NOT NULL);

CREATE INDEX idx_authorships_pub ON authorships USING btree (publication_id);

CREATE INDEX idx_authorships_structs ON authorships USING gin (structure_ids) WHERE (structure_ids IS NOT NULL);

CREATE INDEX idx_authorships_uca ON authorships USING btree (is_uca) WHERE (is_uca = true);

CREATE INDEX idx_authorships_wos_as ON authorships USING btree (wos_authorship_id) WHERE (wos_authorship_id IS NOT NULL);

CREATE INDEX idx_distinct_pubs_a ON distinct_publications USING btree (pub_id_a);

CREATE INDEX idx_distinct_pubs_b ON distinct_publications USING btree (pub_id_b);

CREATE INDEX idx_hal_as_author ON hal_authorships USING btree (hal_author_id);

CREATE INDEX idx_hal_as_doc ON hal_authorships USING btree (hal_document_id);

CREATE INDEX idx_hal_as_doc_uca_structs ON hal_authorships USING btree (hal_document_id) INCLUDE (structure_ids) WHERE (is_uca = true);

CREATE INDEX idx_hal_as_structs ON hal_authorships USING gin (structure_ids) WHERE (structure_ids IS NOT NULL);

CREATE INDEX idx_hal_as_uca ON hal_authorships USING btree (is_uca) WHERE (is_uca = true);

CREATE UNIQUE INDEX idx_hal_authors_form_id ON hal_authors USING btree (hal_form_id) WHERE (hal_form_id IS NOT NULL);

CREATE INDEX idx_hal_authors_fullname_noident ON hal_authors USING btree (full_name) WHERE ((hal_person_id IS NULL) AND (idhal IS NULL));

CREATE INDEX idx_hal_authors_idhal ON hal_authors USING btree (idhal) WHERE (idhal IS NOT NULL);

CREATE INDEX idx_hal_authors_name ON hal_authors USING btree (last_name, first_name);

CREATE INDEX idx_hal_authors_orcid ON hal_authors USING btree (orcid) WHERE (orcid IS NOT NULL);

CREATE INDEX idx_hal_authors_person ON hal_authors USING btree (person_id) WHERE (person_id IS NOT NULL);

CREATE INDEX idx_hal_docs_collections ON hal_documents USING gin (collections);

CREATE INDEX idx_hal_docs_doi ON hal_documents USING btree (doi) WHERE (doi IS NOT NULL);

CREATE INDEX idx_hal_docs_pub ON hal_documents USING btree (publication_id) WHERE (publication_id IS NOT NULL);

CREATE INDEX idx_hal_struct_alias_ids ON hal_structures USING gin (alias_ids);

CREATE INDEX idx_hal_struct_local ON hal_structures USING btree (structure_id) WHERE (structure_id IS NOT NULL);

CREATE INDEX idx_hal_struct_name ON hal_structures USING btree (lower(name));

CREATE INDEX idx_hal_struct_parent_ids ON hal_structures USING gin (parent_ids);

CREATE INDEX idx_hal_struct_type ON hal_structures USING btree (type);

CREATE INDEX idx_hal_struct_valid ON hal_structures USING btree (valid);

CREATE INDEX idx_journals_eissn ON journals USING btree (eissn);

CREATE INDEX idx_journals_issn ON journals USING btree (issn);

CREATE INDEX idx_journals_issnl ON journals USING btree (issnl);

CREATE INDEX idx_journals_publisher ON journals USING btree (publisher_id);

CREATE INDEX idx_journals_titlenorm ON journals USING btree (title_normalized);

CREATE INDEX idx_name_forms_active ON name_forms USING btree (is_active) WHERE (is_active = true);

CREATE INDEX idx_name_forms_structure ON name_forms USING btree (structure_id);

CREATE INDEX idx_oa_as_author ON openalex_authorships USING btree (openalex_author_id);

CREATE INDEX idx_oa_as_doc ON openalex_authorships USING btree (openalex_document_id);

CREATE INDEX idx_oa_as_doc_uca_structs ON openalex_authorships USING btree (openalex_document_id) INCLUDE (structure_ids) WHERE (is_uca = true);

CREATE INDEX idx_oa_as_structs ON openalex_authorships USING gin (structure_ids) WHERE (structure_ids IS NOT NULL);

CREATE INDEX idx_oa_as_uca ON openalex_authorships USING btree (is_uca) WHERE (is_uca = true);

CREATE INDEX idx_oa_authors_name ON openalex_authors USING btree (last_name, first_name);

CREATE INDEX idx_oa_authors_orcid ON openalex_authors USING btree (orcid) WHERE (orcid IS NOT NULL);

CREATE INDEX idx_oa_authors_person ON openalex_authors USING btree (person_id) WHERE (person_id IS NOT NULL);

CREATE INDEX idx_oa_docs_doi ON openalex_documents USING btree (doi) WHERE (doi IS NOT NULL);

CREATE INDEX idx_oa_docs_pub ON openalex_documents USING btree (publication_id) WHERE (publication_id IS NOT NULL);

CREATE INDEX idx_oa_inst_ror ON openalex_institutions USING btree (ror_id) WHERE (ror_id IS NOT NULL);

CREATE INDEX idx_oa_inst_struct ON openalex_institutions USING btree (structure_id) WHERE (structure_id IS NOT NULL);

CREATE INDEX idx_oaa_address ON openalex_authorship_addresses USING btree (address_id);

CREATE INDEX idx_person_ids_lookup ON person_identifiers USING btree (id_type, id_value);

CREATE INDEX idx_person_ids_person ON person_identifiers USING btree (person_id);

CREATE INDEX idx_persons_name ON persons USING btree (last_name_normalized, first_name_normalized);

CREATE INDEX idx_persons_rh_department ON persons_rh USING btree (department_name);

CREATE INDEX idx_persons_rh_person_id ON persons_rh USING btree (person_id);

CREATE INDEX idx_pub_title_trgm ON publications USING gin (title_normalized gin_trgm_ops);

CREATE INDEX idx_publications_journal ON publications USING btree (journal_id);

CREATE INDEX idx_publications_review ON publications USING btree (review_status);

CREATE INDEX idx_publications_title_norm ON publications USING btree (title_normalized);

CREATE INDEX idx_publications_titlenorm_year ON publications USING btree (title_normalized, pub_year);

CREATE INDEX idx_publications_year ON publications USING btree (pub_year);

CREATE INDEX idx_publishers_name_norm ON publishers USING btree (name_normalized);

CREATE INDEX idx_publishers_name_trgm ON publishers USING gin (name gin_trgm_ops);

CREATE INDEX idx_staging_hal_doi ON staging_hal USING btree (doi);

CREATE INDEX idx_staging_oa_doi ON staging_openalex USING btree (doi);

CREATE INDEX idx_staging_wos_doi ON staging_wos USING btree (doi);

CREATE INDEX idx_struct_rel_child ON structure_relations USING btree (child_id);

CREATE INDEX idx_struct_rel_parent ON structure_relations USING btree (parent_id);

CREATE INDEX idx_structures_type ON structures USING btree (type);

CREATE INDEX idx_wos_aa_address ON wos_authorship_addresses USING btree (address_id);

CREATE INDEX idx_wos_aa_authorship ON wos_authorship_addresses USING btree (wos_authorship_id);

CREATE INDEX idx_wos_as_author ON wos_authorships USING btree (wos_author_id);

CREATE INDEX idx_wos_as_doc ON wos_authorships USING btree (wos_document_id);

CREATE INDEX idx_wos_as_doc_uca_structs ON wos_authorships USING btree (wos_document_id) INCLUDE (structure_ids) WHERE (is_uca = true);

CREATE INDEX idx_wos_as_structs ON wos_authorships USING gin (structure_ids) WHERE (structure_ids IS NOT NULL);

CREATE INDEX idx_wos_as_uca ON wos_authorships USING btree (is_uca) WHERE (is_uca = true);

CREATE INDEX idx_wos_authors_name ON wos_authors USING btree (last_name, first_name);

CREATE INDEX idx_wos_authors_orcid ON wos_authors USING btree (orcid) WHERE (orcid IS NOT NULL);

CREATE INDEX idx_wos_authors_person ON wos_authors USING btree (person_id) WHERE (person_id IS NOT NULL);

CREATE INDEX idx_wos_docs_doi ON wos_documents USING btree (doi) WHERE (doi IS NOT NULL);

CREATE INDEX idx_wos_docs_pub ON wos_documents USING btree (publication_id) WHERE (publication_id IS NOT NULL);

CREATE UNIQUE INDEX publications_doi_lower_key ON publications USING btree (lower(doi)) WHERE (doi IS NOT NULL);

-- ============================================================
-- Contraintes (FK, CHECK, UNIQUE ajoutées après création)
-- ============================================================

ALTER TABLE ONLY address_structures
    ADD CONSTRAINT address_structures_address_id_structure_id_key UNIQUE (address_id, structure_id);

ALTER TABLE ONLY address_structures
    ADD CONSTRAINT address_structures_pkey PRIMARY KEY (id);

ALTER TABLE ONLY addresses
    ADD CONSTRAINT addresses_pkey PRIMARY KEY (id);

ALTER TABLE ONLY addresses
    ADD CONSTRAINT addresses_raw_text_key UNIQUE (raw_text);

ALTER TABLE ONLY authorships
    ADD CONSTRAINT authorships_pkey PRIMARY KEY (id);

ALTER TABLE ONLY authorships
    ADD CONSTRAINT authorships_publication_person_uq UNIQUE (publication_id, person_id);

ALTER TABLE ONLY distinct_persons
    ADD CONSTRAINT distinct_persons_person_id_a_person_id_b_key UNIQUE (person_id_a, person_id_b);

ALTER TABLE ONLY distinct_persons
    ADD CONSTRAINT distinct_persons_pkey PRIMARY KEY (id);

ALTER TABLE ONLY distinct_publications
    ADD CONSTRAINT distinct_publications_pkey PRIMARY KEY (id);

ALTER TABLE ONLY distinct_publications
    ADD CONSTRAINT distinct_publications_pub_id_a_pub_id_b_key UNIQUE (pub_id_a, pub_id_b);

ALTER TABLE ONLY hal_authors
    ADD CONSTRAINT hal_authors_hal_person_id_key UNIQUE (hal_person_id);

ALTER TABLE ONLY hal_authors
    ADD CONSTRAINT hal_authors_pkey PRIMARY KEY (id);

ALTER TABLE ONLY hal_authorships
    ADD CONSTRAINT hal_authorships_hal_document_id_hal_author_id_key UNIQUE (hal_document_id, hal_author_id);

ALTER TABLE ONLY hal_authorships
    ADD CONSTRAINT hal_authorships_pkey PRIMARY KEY (id);

ALTER TABLE ONLY hal_documents
    ADD CONSTRAINT hal_documents_halid_key UNIQUE (halid);

ALTER TABLE ONLY hal_documents
    ADD CONSTRAINT hal_documents_pkey PRIMARY KEY (id);

ALTER TABLE ONLY hal_structures
    ADD CONSTRAINT hal_structures_hal_struct_id_key UNIQUE (hal_struct_id);

ALTER TABLE ONLY hal_structures
    ADD CONSTRAINT hal_structures_pkey PRIMARY KEY (id);

ALTER TABLE ONLY journals
    ADD CONSTRAINT journals_openalex_id_key UNIQUE (openalex_id);

ALTER TABLE ONLY journals
    ADD CONSTRAINT journals_pkey PRIMARY KEY (id);

ALTER TABLE ONLY name_forms
    ADD CONSTRAINT name_forms_pkey PRIMARY KEY (id);

ALTER TABLE ONLY openalex_authors
    ADD CONSTRAINT openalex_authors_openalex_id_key UNIQUE (openalex_id);

ALTER TABLE ONLY openalex_authors
    ADD CONSTRAINT openalex_authors_pkey PRIMARY KEY (id);

ALTER TABLE ONLY openalex_authorship_addresses
    ADD CONSTRAINT openalex_authorship_addresses_openalex_authorship_id_addres_key UNIQUE (openalex_authorship_id, address_id);

ALTER TABLE ONLY openalex_authorship_addresses
    ADD CONSTRAINT openalex_authorship_addresses_pkey PRIMARY KEY (id);

ALTER TABLE ONLY openalex_authorships
    ADD CONSTRAINT openalex_authorships_openalex_document_id_openalex_author_i_key UNIQUE (openalex_document_id, openalex_author_id);

ALTER TABLE ONLY openalex_authorships
    ADD CONSTRAINT openalex_authorships_pkey PRIMARY KEY (id);

ALTER TABLE ONLY openalex_documents
    ADD CONSTRAINT openalex_documents_openalex_id_key UNIQUE (openalex_id);

ALTER TABLE ONLY openalex_documents
    ADD CONSTRAINT openalex_documents_pkey PRIMARY KEY (id);

ALTER TABLE ONLY openalex_institutions
    ADD CONSTRAINT openalex_institutions_openalex_id_key UNIQUE (openalex_id);

ALTER TABLE ONLY openalex_institutions
    ADD CONSTRAINT openalex_institutions_pkey PRIMARY KEY (id);

ALTER TABLE ONLY person_identifiers
    ADD CONSTRAINT person_identifiers_id_type_id_value_key UNIQUE (id_type, id_value);

ALTER TABLE ONLY person_identifiers
    ADD CONSTRAINT person_identifiers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY persons
    ADD CONSTRAINT persons_pkey PRIMARY KEY (id);

ALTER TABLE ONLY persons_rh
    ADD CONSTRAINT persons_rh_person_id_key UNIQUE (person_id);

ALTER TABLE ONLY persons_rh
    ADD CONSTRAINT persons_rh_pkey PRIMARY KEY (id);

ALTER TABLE ONLY publications
    ADD CONSTRAINT publications_pkey PRIMARY KEY (id);

ALTER TABLE ONLY publishers
    ADD CONSTRAINT publishers_openalex_id_key UNIQUE (openalex_id);

ALTER TABLE ONLY publishers
    ADD CONSTRAINT publishers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY staging_hal
    ADD CONSTRAINT staging_hal_halid_key UNIQUE (halid);

ALTER TABLE ONLY staging_hal
    ADD CONSTRAINT staging_hal_pkey PRIMARY KEY (id);

ALTER TABLE ONLY staging_openalex
    ADD CONSTRAINT staging_openalex_openalex_id_key UNIQUE (openalex_id);

ALTER TABLE ONLY staging_openalex
    ADD CONSTRAINT staging_openalex_pkey PRIMARY KEY (id);

ALTER TABLE ONLY staging_wos
    ADD CONSTRAINT staging_wos_pkey PRIMARY KEY (id);

ALTER TABLE ONLY staging_wos
    ADD CONSTRAINT staging_wos_ut_key UNIQUE (ut);

ALTER TABLE ONLY structure_relations
    ADD CONSTRAINT structure_relations_parent_id_child_id_relation_type_key UNIQUE (parent_id, child_id, relation_type);

ALTER TABLE ONLY structure_relations
    ADD CONSTRAINT structure_relations_pkey PRIMARY KEY (id);

ALTER TABLE ONLY structures
    ADD CONSTRAINT structures_code_key UNIQUE (code);

ALTER TABLE ONLY structures
    ADD CONSTRAINT structures_pkey PRIMARY KEY (id);

ALTER TABLE ONLY wos_authors
    ADD CONSTRAINT wos_authors_daisng_id_key UNIQUE (daisng_id);

ALTER TABLE ONLY wos_authors
    ADD CONSTRAINT wos_authors_pkey PRIMARY KEY (id);

ALTER TABLE ONLY wos_authorship_addresses
    ADD CONSTRAINT wos_authorship_addresses_pkey PRIMARY KEY (id);

ALTER TABLE ONLY wos_authorship_addresses
    ADD CONSTRAINT wos_authorship_addresses_wos_authorship_id_address_id_key UNIQUE (wos_authorship_id, address_id);

ALTER TABLE ONLY wos_authorships
    ADD CONSTRAINT wos_authorships_pkey PRIMARY KEY (id);

ALTER TABLE ONLY wos_authorships
    ADD CONSTRAINT wos_authorships_wos_document_id_wos_author_id_key UNIQUE (wos_document_id, wos_author_id);

ALTER TABLE ONLY wos_documents
    ADD CONSTRAINT wos_documents_pkey PRIMARY KEY (id);

ALTER TABLE ONLY wos_documents
    ADD CONSTRAINT wos_documents_ut_key UNIQUE (ut);

ALTER TABLE ONLY address_structures
    ADD CONSTRAINT address_structures_address_id_fkey FOREIGN KEY (address_id) REFERENCES addresses(id) ON DELETE CASCADE;

ALTER TABLE ONLY address_structures
    ADD CONSTRAINT address_structures_matched_form_id_fkey FOREIGN KEY (matched_form_id) REFERENCES name_forms(id) ON DELETE SET NULL;

ALTER TABLE ONLY address_structures
    ADD CONSTRAINT address_structures_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES structures(id) ON DELETE CASCADE;

ALTER TABLE ONLY authorships
    ADD CONSTRAINT authorships_hal_authorship_id_fkey FOREIGN KEY (hal_authorship_id) REFERENCES hal_authorships(id) ON DELETE SET NULL;

ALTER TABLE ONLY authorships
    ADD CONSTRAINT authorships_openalex_authorship_id_fkey FOREIGN KEY (openalex_authorship_id) REFERENCES openalex_authorships(id) ON DELETE SET NULL;

ALTER TABLE ONLY authorships
    ADD CONSTRAINT authorships_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE SET NULL;

ALTER TABLE ONLY authorships
    ADD CONSTRAINT authorships_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE CASCADE;

ALTER TABLE ONLY authorships
    ADD CONSTRAINT authorships_wos_authorship_id_fkey FOREIGN KEY (wos_authorship_id) REFERENCES wos_authorships(id) ON DELETE SET NULL;

ALTER TABLE ONLY distinct_persons
    ADD CONSTRAINT distinct_persons_person_id_a_fkey FOREIGN KEY (person_id_a) REFERENCES persons(id) ON DELETE CASCADE;

ALTER TABLE ONLY distinct_persons
    ADD CONSTRAINT distinct_persons_person_id_b_fkey FOREIGN KEY (person_id_b) REFERENCES persons(id) ON DELETE CASCADE;

ALTER TABLE ONLY distinct_publications
    ADD CONSTRAINT distinct_publications_pub_id_a_fkey FOREIGN KEY (pub_id_a) REFERENCES publications(id) ON DELETE CASCADE;

ALTER TABLE ONLY distinct_publications
    ADD CONSTRAINT distinct_publications_pub_id_b_fkey FOREIGN KEY (pub_id_b) REFERENCES publications(id) ON DELETE CASCADE;

ALTER TABLE ONLY hal_authors
    ADD CONSTRAINT hal_authors_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE SET NULL;

ALTER TABLE ONLY hal_authorships
    ADD CONSTRAINT hal_authorships_hal_author_id_fkey FOREIGN KEY (hal_author_id) REFERENCES hal_authors(id) ON DELETE CASCADE;

ALTER TABLE ONLY hal_authorships
    ADD CONSTRAINT hal_authorships_hal_document_id_fkey FOREIGN KEY (hal_document_id) REFERENCES hal_documents(id) ON DELETE CASCADE;

ALTER TABLE ONLY hal_documents
    ADD CONSTRAINT hal_documents_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE SET NULL;

ALTER TABLE ONLY hal_documents
    ADD CONSTRAINT hal_documents_staging_id_fkey FOREIGN KEY (staging_id) REFERENCES staging_hal(id);

ALTER TABLE ONLY hal_structures
    ADD CONSTRAINT hal_structures_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES structures(id) ON DELETE SET NULL;

ALTER TABLE ONLY journals
    ADD CONSTRAINT journals_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES publishers(id);

ALTER TABLE ONLY name_forms
    ADD CONSTRAINT name_forms_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES structures(id) ON DELETE CASCADE;

ALTER TABLE ONLY openalex_authors
    ADD CONSTRAINT openalex_authors_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE SET NULL;

ALTER TABLE ONLY openalex_authorship_addresses
    ADD CONSTRAINT openalex_authorship_addresses_address_id_fkey FOREIGN KEY (address_id) REFERENCES addresses(id) ON DELETE CASCADE;

ALTER TABLE ONLY openalex_authorship_addresses
    ADD CONSTRAINT openalex_authorship_addresses_openalex_authorship_id_fkey FOREIGN KEY (openalex_authorship_id) REFERENCES openalex_authorships(id) ON DELETE CASCADE;

ALTER TABLE ONLY openalex_authorships
    ADD CONSTRAINT openalex_authorships_openalex_author_id_fkey FOREIGN KEY (openalex_author_id) REFERENCES openalex_authors(id) ON DELETE CASCADE;

ALTER TABLE ONLY openalex_authorships
    ADD CONSTRAINT openalex_authorships_openalex_document_id_fkey FOREIGN KEY (openalex_document_id) REFERENCES openalex_documents(id) ON DELETE CASCADE;

ALTER TABLE ONLY openalex_documents
    ADD CONSTRAINT openalex_documents_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE SET NULL;

ALTER TABLE ONLY openalex_documents
    ADD CONSTRAINT openalex_documents_staging_id_fkey FOREIGN KEY (staging_id) REFERENCES staging_openalex(id);

ALTER TABLE ONLY openalex_institutions
    ADD CONSTRAINT openalex_institutions_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES structures(id) ON DELETE SET NULL;

ALTER TABLE ONLY person_identifiers
    ADD CONSTRAINT person_identifiers_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE CASCADE;

ALTER TABLE ONLY persons_rh
    ADD CONSTRAINT persons_rh_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE RESTRICT;

ALTER TABLE ONLY persons_rh
    ADD CONSTRAINT persons_rh_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES structures(id);

ALTER TABLE ONLY publications
    ADD CONSTRAINT publications_journal_id_fkey FOREIGN KEY (journal_id) REFERENCES journals(id);

ALTER TABLE ONLY structure_relations
    ADD CONSTRAINT structure_relations_child_id_fkey FOREIGN KEY (child_id) REFERENCES structures(id) ON DELETE CASCADE;

ALTER TABLE ONLY structure_relations
    ADD CONSTRAINT structure_relations_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES structures(id) ON DELETE CASCADE;

ALTER TABLE ONLY wos_authors
    ADD CONSTRAINT wos_authors_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE SET NULL;

ALTER TABLE ONLY wos_authorship_addresses
    ADD CONSTRAINT wos_authorship_addresses_address_id_fkey FOREIGN KEY (address_id) REFERENCES addresses(id) ON DELETE CASCADE;

ALTER TABLE ONLY wos_authorship_addresses
    ADD CONSTRAINT wos_authorship_addresses_wos_authorship_id_fkey FOREIGN KEY (wos_authorship_id) REFERENCES wos_authorships(id) ON DELETE CASCADE;

ALTER TABLE ONLY wos_authorships
    ADD CONSTRAINT wos_authorships_wos_author_id_fkey FOREIGN KEY (wos_author_id) REFERENCES wos_authors(id) ON DELETE CASCADE;

ALTER TABLE ONLY wos_authorships
    ADD CONSTRAINT wos_authorships_wos_document_id_fkey FOREIGN KEY (wos_document_id) REFERENCES wos_documents(id) ON DELETE CASCADE;

ALTER TABLE ONLY wos_documents
    ADD CONSTRAINT wos_documents_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES publications(id) ON DELETE SET NULL;

ALTER TABLE ONLY wos_documents
    ADD CONSTRAINT wos_documents_staging_id_fkey FOREIGN KEY (staging_id) REFERENCES staging_wos(id);


