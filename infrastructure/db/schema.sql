--
-- PostgreSQL database dump
--

\restrict nyWysq9wv77WJm4sNl5wnRR6y9JxN3Z8OVNO2pXNylFUduji3jiznQ0YXf3Koy5

-- Dumped from database version 18.6 (Ubuntu 18.6-1.pgdg22.04+2)
-- Dumped by pg_dump version 18.6 (Ubuntu 18.6-1.pgdg22.04+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: ops; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ops;


--
-- Name: persons; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA persons;


--
-- Name: publications; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA publications;


--
-- Name: publishing; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA publishing;


--
-- Name: ref; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA ref;


--
-- Name: sources; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA sources;


--
-- Name: structures; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA structures;


--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: unaccent; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;


--
-- Name: EXTENSION unaccent; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION unaccent IS 'text search dictionary that removes accents';


--
-- Name: doc_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.doc_type AS ENUM (
    'article',
    'conference_paper',
    'conference',
    'book',
    'book_chapter',
    'thesis',
    'ongoing_thesis',
    'preprint',
    'review',
    'editorial',
    'report',
    'peer_review',
    'other',
    'dataset',
    'software',
    'patent',
    'hdr',
    'memoir',
    'poster',
    'letter',
    'erratum',
    'retraction',
    'book_review',
    'data_paper',
    'proceedings',
    'media'
);


--
-- Name: hal_structure_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.hal_structure_status AS ENUM (
    'VALID',
    'OLD',
    'INCOMING'
);


--
-- Name: identifier_origin; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.identifier_origin AS ENUM (
    'manual',
    'auto'
);


--
-- Name: identifier_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.identifier_status AS ENUM (
    'pending',
    'confirmed',
    'rejected',
    'authenticated'
);


--
-- Name: issn_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.issn_status AS ENUM (
    'active',
    'malformed',
    'cancelled',
    'related_title',
    'supplement',
    'unverified'
);


--
-- Name: issn_support; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.issn_support AS ENUM (
    'print',
    'electronic',
    'other'
);


--
-- Name: journal_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.journal_type AS ENUM (
    'journal',
    'proceedings',
    'repository',
    'book_series',
    'preprint_server',
    'media',
    'ebook_platform',
    'unknown'
);


--
-- Name: license_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.license_type AS ENUM (
    'cc-by',
    'cc-by-sa',
    'cc-by-nd',
    'cc-by-nc',
    'cc-by-nc-sa',
    'cc-by-nc-nd',
    'public-domain',
    'licence-ouverte',
    'open-source',
    'repository-distribution',
    'publisher-open',
    'other-oa',
    'all-rights-reserved',
    'other'
);


--
-- Name: merged_entity; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.merged_entity AS ENUM (
    'person',
    'journal',
    'publisher',
    'monograph',
    'publication'
);


--
-- Name: oa_model; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.oa_model AS ENUM (
    'subscription',
    'full_oa',
    'diamond',
    'repository'
);


--
-- Name: oa_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.oa_type AS ENUM (
    'gold',
    'hybrid',
    'bronze',
    'green',
    'closed',
    'unknown',
    'diamond',
    'embargoed'
);


--
-- Name: perimeter_evidence; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.perimeter_evidence AS ENUM (
    'address',
    'rh_identity',
    'hal_structure',
    'ror',
    'thesis_institution'
);


--
-- Name: person_exclusion; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.person_exclusion AS ENUM (
    'not_a_person',
    'out_of_perimeter'
);


--
-- Name: publisher_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.publisher_type AS ENUM (
    'commercial',
    'learned_society',
    'academic_institution',
    'repository',
    'aggregator',
    'media',
    'unknown'
);


--
-- Name: relation_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.relation_type AS ENUM (
    'is_preprint_of',
    'has_preprint',
    'is_supplement_to',
    'has_supplement',
    'is_part_of',
    'has_part',
    'is_correction_of',
    'has_correction',
    'is_retraction_of',
    'has_retraction',
    'is_concern_about',
    'has_concern',
    'is_translation_of',
    'has_translation',
    'describes',
    'is_described_by',
    'is_related_to'
);


--
-- Name: resolution_mode; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.resolution_mode AS ENUM (
    'identifier',
    'name',
    'cross_source'
);


--
-- Name: ror_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.ror_status AS ENUM (
    'active',
    'inactive',
    'withdrawn'
);


--
-- Name: ror_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.ror_type AS ENUM (
    'archive',
    'company',
    'education',
    'facility',
    'funder',
    'government',
    'healthcare',
    'nonprofit',
    'other'
);


--
-- Name: source_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.source_type AS ENUM (
    'hal',
    'openalex',
    'wos',
    'scanr',
    'theses',
    'crossref',
    'datacite'
);


--
-- Name: structure_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.structure_type AS ENUM (
    'universite',
    'chu',
    'ecole',
    'labo',
    'equipe',
    'site',
    'autre',
    'onr',
    'admin'
);


--
-- Name: normalize_name_form(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.normalize_name_form(input text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE
    s text := input;
BEGIN
    IF s IS NULL THEN
        RETURN NULL;
    END IF;

    -- Retrait des balises MathML/HTML. Une balise de mise en forme (<sub>, <i>, <mml:mi> …)
    -- disparaît : CO<sub>2</sub> donne CO2. Les autres balises deviennent un espace.
    -- Premier caractère = lettre ou '/' : les indices de Miller <111>/<110> (cristallographie)
    -- restent dans le texte.
    s := regexp_replace(s, '</?([A-Za-z][A-Za-z0-9.-]*:)?(sub|sup|i|b|em|strong|u|span|small|tt|sc|scp|italic|bold|underline|monospace|overline|roman|strike|math|mi|mn|mo|ms|mtext|mrow|msub|msup|msubsup|mfrac|msqrt|mroot|mover|munder|munderover|mstyle|mspace|mpadded|mphantom|mfenced|menclose|semantics|inline-formula)(\s[^>]*|/)?>', '', 'gi');
    s := regexp_replace(s, '</?[A-Za-z][^>]*>', ' ', 'g');

    -- I turc avec point : PG lower()+unaccent le perd ("İstanbul" → "stanbul").
    s := replace(s, E'İ', 'i');

    -- Fractions vulgaires → chiffres espacés (comme "1/4" tapé à la main).
    s := replace(s, E'¼', '1 4');
    s := replace(s, E'½', '1 2');
    s := replace(s, E'¾', '3 4');
    s := replace(s, E'⅐', '1 7');
    s := replace(s, E'⅑', '1 9');
    s := replace(s, E'⅒', '1 10');
    s := replace(s, E'⅓', '1 3');
    s := replace(s, E'⅔', '2 3');
    s := replace(s, E'⅕', '1 5');
    s := replace(s, E'⅖', '2 5');
    s := replace(s, E'⅗', '3 5');
    s := replace(s, E'⅘', '4 5');
    s := replace(s, E'⅙', '1 6');
    s := replace(s, E'⅚', '5 6');
    s := replace(s, E'⅛', '1 8');
    s := replace(s, E'⅜', '3 8');
    s := replace(s, E'⅝', '5 8');
    s := replace(s, E'⅞', '7 8');

    s := translate(s,
        E'‐‑‒–—―­‘’‚′“”',
        E'-------\x27\x27\x27\x27""'
    );

    -- Chiffres exposants/indices → chiffres ASCII (attachés). L'exposant moins `⁻`
    -- tombe dans le passage [^a-z0-9] → espace.
    s := translate(s,
        E'⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉',
        '01234567890123456789'
    );

    RETURN trim(regexp_replace(
        unaccent(lower(trim(s))),
        '[^a-z0-9]+', ' ', 'g'
    ));
END;
$$;


--
-- Name: protect_authenticated_identifier(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.protect_authenticated_identifier() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.status = 'authenticated'
               AND current_setting('app.orcid_authenticated_import', true) IS DISTINCT FROM 'on' THEN
                RAISE EXCEPTION
                    'le statut authenticated ne peut etre pose que par l''import des ORCID authentifies';
            END IF;
            IF TG_OP = 'UPDATE'
               AND OLD.status = 'authenticated'
               AND NEW.status <> 'authenticated' THEN
                RAISE EXCEPTION
                    'le statut authenticated est immuable : degradation interdite (id=%)', OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_log; Type: TABLE; Schema: ops; Owner: -
--

CREATE TABLE ops.audit_log (
    id bigint NOT NULL,
    event_type text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id integer,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    user_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE audit_log; Type: COMMENT; Schema: ops; Owner: -
--

COMMENT ON TABLE ops.audit_log IS 'Trace des opérations destructives/décisionnelles déclenchées via l''admin HTTP. Les opérations du pipeline ne sont pas auditées.';


--
-- Name: COLUMN audit_log.event_type; Type: COMMENT; Schema: ops; Owner: -
--

COMMENT ON COLUMN ops.audit_log.event_type IS 'Type d''événement, notation pointée : person.merged, publication.excluded, structure.deleted, etc.';


--
-- Name: COLUMN audit_log.aggregate_type; Type: COMMENT; Schema: ops; Owner: -
--

COMMENT ON COLUMN ops.audit_log.aggregate_type IS 'Type de l''entité affectée : person, publication, structure, journal, publisher, authorship.';


--
-- Name: COLUMN audit_log.aggregate_id; Type: COMMENT; Schema: ops; Owner: -
--

COMMENT ON COLUMN ops.audit_log.aggregate_id IS 'ID de l''entité affectée, NULL si l''entité a été supprimée et n''a pas d''équivalent survivant.';


--
-- Name: COLUMN audit_log.payload; Type: COMMENT; Schema: ops; Owner: -
--

COMMENT ON COLUMN ops.audit_log.payload IS 'Données utiles pour l''audit : source_id d''une fusion, champs modifiés, raison, etc.';


--
-- Name: COLUMN audit_log.user_id; Type: COMMENT; Schema: ops; Owner: -
--

COMMENT ON COLUMN ops.audit_log.user_id IS 'Utilisateur admin authentifié ayant déclenché l''opération (middleware auth). NULL théoriquement impossible quand l''entrée est écrite.';


--
-- Name: audit_log_id_seq; Type: SEQUENCE; Schema: ops; Owner: -
--

CREATE SEQUENCE ops.audit_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: ops; Owner: -
--

ALTER SEQUENCE ops.audit_log_id_seq OWNED BY ops.audit_log.id;


--
-- Name: config; Type: TABLE; Schema: ops; Owner: -
--

CREATE TABLE ops.config (
    key text NOT NULL,
    value jsonb NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT config_cap_is_non_negative_integer CHECK (((key <> ALL (ARRAY['unpaywall_max_per_run'::text, 'fetch_missing_max_per_source'::text])) OR ((jsonb_typeof(value) = 'number'::text) AND ((value)::numeric >= (0)::numeric) AND ((value)::numeric = trunc((value)::numeric))))),
    CONSTRAINT config_delay_is_positive_integer CHECK (((key <> ALL (ARRAY['doaj_refresh_after_days'::text, 'fetch_missing_retry_after_days'::text, 'fetch_stale_after_days'::text, 'unpaywall_recheck_after_days'::text])) OR ((jsonb_typeof(value) = 'number'::text) AND ((value)::numeric >= (1)::numeric) AND ((value)::numeric = trunc((value)::numeric))))),
    CONSTRAINT config_year_is_in_range CHECK (((key <> 'pipeline_start_year_full'::text) OR ((jsonb_typeof(value) = 'number'::text) AND (((value)::numeric >= (1970)::numeric) AND ((value)::numeric <= (2100)::numeric)) AND ((value)::numeric = trunc((value)::numeric)))))
);


--
-- Name: pipeline_phase_executions; Type: TABLE; Schema: ops; Owner: -
--

CREATE TABLE ops.pipeline_phase_executions (
    id bigint NOT NULL,
    run_id bigint NOT NULL,
    phase text NOT NULL,
    started_at timestamp with time zone NOT NULL,
    ended_at timestamp with time zone NOT NULL,
    mode text NOT NULL,
    sources text[] DEFAULT '{}'::text[] NOT NULL,
    status text NOT NULL,
    signals jsonb DEFAULT '[]'::jsonb NOT NULL,
    metrics jsonb DEFAULT '{}'::jsonb NOT NULL,
    details jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT pipeline_phase_executions_status_check CHECK ((status = ANY (ARRAY['ok'::text, 'warning'::text, 'error'::text])))
);


--
-- Name: pipeline_phase_executions_id_seq; Type: SEQUENCE; Schema: ops; Owner: -
--

ALTER TABLE ops.pipeline_phase_executions ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME ops.pipeline_phase_executions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: confirmed_authorships; Type: TABLE; Schema: persons; Owner: -
--

CREATE TABLE persons.confirmed_authorships (
    source_authorship_id integer NOT NULL,
    person_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: distinct_persons; Type: TABLE; Schema: persons; Owner: -
--

CREATE TABLE persons.distinct_persons (
    id integer NOT NULL,
    person_id_a integer NOT NULL,
    person_id_b integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT distinct_persons_ordered CHECK ((person_id_a < person_id_b))
);


--
-- Name: distinct_persons_id_seq; Type: SEQUENCE; Schema: persons; Owner: -
--

CREATE SEQUENCE persons.distinct_persons_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: distinct_persons_id_seq; Type: SEQUENCE OWNED BY; Schema: persons; Owner: -
--

ALTER SEQUENCE persons.distinct_persons_id_seq OWNED BY persons.distinct_persons.id;


--
-- Name: person_identifiers; Type: TABLE; Schema: persons; Owner: -
--

CREATE TABLE persons.person_identifiers (
    id integer NOT NULL,
    person_id integer NOT NULL,
    id_type text NOT NULL,
    id_value text NOT NULL,
    source public.identifier_origin NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    status public.identifier_status DEFAULT 'pending'::public.identifier_status NOT NULL
);


--
-- Name: person_identifiers_id_seq; Type: SEQUENCE; Schema: persons; Owner: -
--

CREATE SEQUENCE persons.person_identifiers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: person_identifiers_id_seq; Type: SEQUENCE OWNED BY; Schema: persons; Owner: -
--

ALTER SEQUENCE persons.person_identifiers_id_seq OWNED BY persons.person_identifiers.id;


--
-- Name: person_name_forms; Type: TABLE; Schema: persons; Owner: -
--

CREATE TABLE persons.person_name_forms (
    name_form text NOT NULL,
    person_id integer NOT NULL,
    sources text[] DEFAULT '{}'::text[] NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    status public.identifier_status DEFAULT 'pending'::public.identifier_status NOT NULL
);


--
-- Name: persons; Type: TABLE; Schema: persons; Owner: -
--

CREATE TABLE persons.persons (
    id integer NOT NULL,
    last_name text NOT NULL,
    first_name text NOT NULL,
    last_name_normalized text NOT NULL,
    first_name_normalized text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    exclusion public.person_exclusion
);


--
-- Name: COLUMN persons.exclusion; Type: COMMENT; Schema: persons; Owner: -
--

COMMENT ON COLUMN persons.persons.exclusion IS 'Motif d''exclusion décidé à la main : not_a_person (fausse entité), out_of_perimeter (personne réelle rattachée au périmètre par erreur). Nul pour une personne retenue.';


--
-- Name: persons_id_seq; Type: SEQUENCE; Schema: persons; Owner: -
--

CREATE SEQUENCE persons.persons_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: persons_id_seq; Type: SEQUENCE OWNED BY; Schema: persons; Owner: -
--

ALTER SEQUENCE persons.persons_id_seq OWNED BY persons.persons.id;


--
-- Name: persons_rh; Type: TABLE; Schema: persons; Owner: -
--

CREATE TABLE persons.persons_rh (
    id integer NOT NULL,
    person_id integer NOT NULL,
    email text,
    role_title text,
    department_name text,
    start_date date,
    end_date date,
    hr_export_date date,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: persons_rh_id_seq; Type: SEQUENCE; Schema: persons; Owner: -
--

CREATE SEQUENCE persons.persons_rh_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: persons_rh_id_seq; Type: SEQUENCE OWNED BY; Schema: persons; Owner: -
--

ALTER SEQUENCE persons.persons_rh_id_seq OWNED BY persons.persons_rh.id;


--
-- Name: rejected_authorships; Type: TABLE; Schema: persons; Owner: -
--

CREATE TABLE persons.rejected_authorships (
    source_publication_id integer CONSTRAINT rejected_authorships_by_notice_source_publication_id_not_null NOT NULL,
    person_id integer CONSTRAINT rejected_authorships_by_notice_person_id_not_null NOT NULL,
    created_at timestamp with time zone DEFAULT now() CONSTRAINT rejected_authorships_by_notice_created_at_not_null NOT NULL
);


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: merge_redirects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.merge_redirects (
    entity public.merged_entity NOT NULL,
    absorbed_id integer NOT NULL,
    kept_id integer NOT NULL,
    merged_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE merge_redirects; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.merge_redirects IS 'Identifiant d''une entité absorbée par une fusion, et identifiant de l''entité conservée. Une redirection en chaîne mène directement à la dernière entité conservée.';


--
-- Name: pipeline_run_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pipeline_run_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: authorships; Type: TABLE; Schema: publications; Owner: -
--

CREATE TABLE publications.authorships (
    id integer NOT NULL,
    publication_id integer NOT NULL,
    person_id integer NOT NULL,
    author_position smallint,
    created_at timestamp with time zone DEFAULT now(),
    is_corresponding boolean,
    roles text[],
    perimeter_evidence public.perimeter_evidence[] DEFAULT '{}'::public.perimeter_evidence[] NOT NULL,
    in_perimeter boolean GENERATED ALWAYS AS ((cardinality(perimeter_evidence) > 0)) STORED NOT NULL
);


--
-- Name: hal_structure_aliases; Type: TABLE; Schema: ref; Owner: -
--

CREATE TABLE ref.hal_structure_aliases (
    alias_id integer NOT NULL,
    hal_structure_id integer NOT NULL
);


--
-- Name: TABLE hal_structure_aliases; Type: COMMENT; Schema: ref; Owner: -
--

COMMENT ON TABLE ref.hal_structure_aliases IS 'Fiches en double du référentiel HAL, fondues dans une structure conservée.';


--
-- Name: hal_structure_relations; Type: TABLE; Schema: ref; Owner: -
--

CREATE TABLE ref.hal_structure_relations (
    parent_id integer NOT NULL,
    child_id integer NOT NULL,
    CONSTRAINT hal_structure_relations_no_self_reference CHECK ((parent_id <> child_id))
);


--
-- Name: TABLE hal_structure_relations; Type: COMMENT; Schema: ref; Owner: -
--

COMMENT ON TABLE ref.hal_structure_relations IS 'Relations parent/enfant entre structures du référentiel HAL.';


--
-- Name: hal_structures; Type: TABLE; Schema: ref; Owner: -
--

CREATE TABLE ref.hal_structures (
    hal_structure_id integer NOT NULL,
    name text NOT NULL,
    acronym text,
    structure_type text NOT NULL,
    country_code character(2),
    status public.hal_structure_status NOT NULL,
    ror_id text,
    start_date date,
    end_date date,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    parent_ids integer[] DEFAULT '{}'::integer[] NOT NULL,
    structure_id integer
);


--
-- Name: TABLE hal_structures; Type: COMMENT; Schema: ref; Owner: -
--

COMMENT ON TABLE ref.hal_structures IS 'Structures du référentiel HAL (ref/structure). Référentiel externe : son ROR, ou structure_id, le relie au référentiel interne.';


--
-- Name: source_authorship_addresses; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.source_authorship_addresses (
    id integer NOT NULL,
    source_authorship_id integer NOT NULL,
    address_id integer NOT NULL
);


--
-- Name: source_authorship_hal_structures; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.source_authorship_hal_structures (
    source_authorship_id integer NOT NULL,
    hal_structure_id integer NOT NULL
);


--
-- Name: source_authorship_rors; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.source_authorship_rors (
    source_authorship_id integer NOT NULL,
    ror_id text NOT NULL,
    address_id integer
);


--
-- Name: TABLE source_authorship_rors; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON TABLE sources.source_authorship_rors IS 'ROR attribués par la source à une signature, rattachés à l''adresse de leur affiliation, ou à la seule signature quand l''affiliation est sans texte (address_id vide). ror_id est sans clé étrangère vers ror_organizations : une source peut citer un ROR absent du dump importé.';


--
-- Name: address_structures; Type: TABLE; Schema: structures; Owner: -
--

CREATE TABLE structures.address_structures (
    id integer NOT NULL,
    address_id integer NOT NULL,
    structure_id integer NOT NULL,
    matched_form_id integer,
    is_confirmed boolean
);


--
-- Name: perimeter_structures; Type: TABLE; Schema: structures; Owner: -
--

CREATE TABLE structures.perimeter_structures (
    perimeter_id integer NOT NULL,
    structure_id integer NOT NULL
);


--
-- Name: perimeters; Type: TABLE; Schema: structures; Owner: -
--

CREATE TABLE structures.perimeters (
    id integer NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    root_structure_ids integer[] DEFAULT '{}'::integer[] CONSTRAINT perimeters_structure_ids_not_null NOT NULL
);


--
-- Name: structures; Type: TABLE; Schema: structures; Owner: -
--

CREATE TABLE structures.structures (
    id integer NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    acronym text,
    structure_type public.structure_type CONSTRAINT structures_type_not_null NOT NULL,
    ror_id text,
    rnsr_id text,
    hal_collection text,
    created_at timestamp with time zone DEFAULT now(),
    api_ids jsonb
);


--
-- Name: source_authorship_structures; Type: MATERIALIZED VIEW; Schema: sources; Owner: -
--

CREATE MATERIALIZED VIEW sources.source_authorship_structures AS
 WITH RECURSIVE perimeter AS (
         SELECT ps.structure_id
           FROM structures.perimeter_structures ps
          WHERE (ps.perimeter_id = ( SELECT perimeters.id
                   FROM structures.perimeters
                  WHERE (perimeters.code = ( SELECT (config.value #>> '{}'::text[])
                           FROM ops.config
                          WHERE (config.key = 'perimeter_extraction'::text)))))
        ), hal_match AS (
         SELECT hs.hal_structure_id,
            s.id AS structure_id
           FROM (ref.hal_structures hs
             JOIN structures.structures s ON ((s.ror_id = hs.ror_id)))
        UNION
         SELECT hal_structures.hal_structure_id,
            hal_structures.structure_id
           FROM ref.hal_structures
          WHERE (hal_structures.structure_id IS NOT NULL)
        ), hal_ancestors AS (
         SELECT hal_structure_relations.child_id,
            hal_structure_relations.parent_id AS ancestor_id,
            1 AS depth
           FROM ref.hal_structure_relations
        UNION
         SELECT a.child_id,
            r.parent_id,
            (a.depth + 1)
           FROM (hal_ancestors a
             JOIN ref.hal_structure_relations r ON ((r.child_id = a.ancestor_id)))
          WHERE (a.depth < 10)
        ), hal_direct AS (
         SELECT DISTINCT sah.source_authorship_id,
            COALESCE(al.hal_structure_id, sah.hal_structure_id) AS hal_structure_id
           FROM (sources.source_authorship_hal_structures sah
             LEFT JOIN ref.hal_structure_aliases al ON ((al.alias_id = sah.hal_structure_id)))
        ), hal_lowest AS (
         SELECT hal_direct.source_authorship_id,
            hal_direct.hal_structure_id
           FROM hal_direct
        EXCEPT
         SELECT d.source_authorship_id,
            a.ancestor_id
           FROM (hal_direct d
             JOIN hal_ancestors a ON ((a.child_id = d.hal_structure_id)))
        ), hal_walk AS (
         SELECT hal_structures.hal_structure_id AS origin_id,
            hal_structures.hal_structure_id,
            0 AS depth
           FROM ref.hal_structures
        UNION
         SELECT w.origin_id,
            r.parent_id,
            (w.depth + 1)
           FROM (hal_walk w
             JOIN ref.hal_structure_relations r ON ((r.child_id = w.hal_structure_id)))
          WHERE ((w.depth < 10) AND (NOT (EXISTS ( SELECT 1
                   FROM hal_match m
                  WHERE (m.hal_structure_id = w.hal_structure_id)))))
        ), hal_reach AS (
         SELECT DISTINCT w.origin_id,
            m.structure_id
           FROM (hal_walk w
             JOIN hal_match m ON ((m.hal_structure_id = w.hal_structure_id)))
          WHERE (m.structure_id IN ( SELECT perimeter.structure_id
                   FROM perimeter))
        )
 SELECT saa.source_authorship_id,
    ast.structure_id,
    'address'::public.perimeter_evidence AS evidence
   FROM (sources.source_authorship_addresses saa
     JOIN structures.address_structures ast ON ((ast.address_id = saa.address_id)))
  WHERE ((ast.is_confirmed IS DISTINCT FROM false) AND (ast.structure_id IN ( SELECT perimeter.structure_id
           FROM perimeter)))
UNION
 SELECT sar.source_authorship_id,
    s.id AS structure_id,
    'ror'::public.perimeter_evidence AS evidence
   FROM (sources.source_authorship_rors sar
     JOIN structures.structures s ON ((s.ror_id = sar.ror_id)))
  WHERE ((s.id IN ( SELECT perimeter.structure_id
           FROM perimeter)) AND ((sar.address_id IS NULL) OR (EXISTS ( SELECT 1
           FROM structures.address_structures ast
          WHERE ((ast.address_id = sar.address_id) AND (ast.is_confirmed IS DISTINCT FROM false) AND (ast.structure_id IN ( SELECT perimeter.structure_id
                   FROM perimeter)))))))
UNION
 SELECT l.source_authorship_id,
    r.structure_id,
    'hal_structure'::public.perimeter_evidence AS evidence
   FROM (hal_lowest l
     JOIN hal_reach r ON ((r.origin_id = l.hal_structure_id)))
  WITH NO DATA;


--
-- Name: source_authorships; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.source_authorships (
    id integer NOT NULL,
    source public.source_type NOT NULL,
    source_publication_id integer NOT NULL,
    author_position smallint,
    person_id integer,
    is_corresponding boolean DEFAULT false,
    roles text[] DEFAULT ARRAY['author'::text],
    raw_author_name text,
    created_at timestamp with time zone DEFAULT now(),
    countries_dirty boolean DEFAULT true NOT NULL,
    identity_id integer NOT NULL,
    resolution_mode public.resolution_mode,
    neutralized_identifiers jsonb,
    content_hash text,
    raw_last_name text,
    raw_first_name text,
    perimeter_evidence public.perimeter_evidence[] DEFAULT '{}'::public.perimeter_evidence[] NOT NULL,
    in_perimeter boolean GENERATED ALWAYS AS ((cardinality(perimeter_evidence) > 0)) STORED NOT NULL,
    CONSTRAINT source_authorships_name_form CHECK (((num_nonnulls(raw_author_name, raw_last_name) = 1) AND ((raw_first_name IS NULL) OR (raw_last_name IS NOT NULL))))
);
ALTER TABLE ONLY sources.source_authorships ALTER COLUMN source_publication_id SET (n_distinct=-0.0134);


--
-- Name: COLUMN source_authorships.neutralized_identifiers; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_authorships.neutralized_identifiers IS 'Identifiants de l''identité que la résolution des personnes ignore pour cette signature, avec leur motif : {"orcid": "shared"}.';


--
-- Name: COLUMN source_authorships.content_hash; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_authorships.content_hash IS 'Empreinte des champs écrits par la normalisation, adresses comprises.';


--
-- Name: source_publications; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.source_publications (
    id integer NOT NULL,
    source public.source_type NOT NULL,
    source_id text NOT NULL,
    doi text,
    title text NOT NULL,
    pub_year smallint,
    doc_type text,
    publication_id integer,
    staging_id integer,
    created_at timestamp with time zone DEFAULT now(),
    countries text[],
    hal_collections text[],
    external_ids jsonb DEFAULT '{}'::jsonb NOT NULL,
    urls text[],
    journal_id integer,
    oa_status text,
    language text,
    container_title text,
    is_retracted boolean,
    abstract text,
    keywords text[],
    topics jsonb,
    biblio jsonb,
    meta jsonb,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    raw_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    title_normalized text,
    keys_dirty boolean DEFAULT true NOT NULL,
    embargo_until date,
    monograph_id integer,
    authors_hash text,
    impact jsonb,
    license public.license_type,
    CONSTRAINT source_publications_external_ids_is_object CHECK ((jsonb_typeof(external_ids) = 'object'::text)),
    CONSTRAINT source_publications_impact_is_object CHECK (((impact IS NULL) OR (jsonb_typeof(impact) = 'object'::text))),
    CONSTRAINT source_publications_raw_metadata_is_object CHECK ((jsonb_typeof(raw_metadata) = 'object'::text))
);


--
-- Name: COLUMN source_publications.authors_hash; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_publications.authors_hash IS 'Empreinte de la partie auteurs du payload source, à la dernière synchronisation des signatures.';


--
-- Name: authorship_structures; Type: MATERIALIZED VIEW; Schema: publications; Owner: -
--

CREATE MATERIALIZED VIEW publications.authorship_structures AS
 SELECT DISTINCT a.id AS authorship_id,
    sas.structure_id
   FROM (((sources.source_authorship_structures sas
     JOIN sources.source_authorships sa ON ((sa.id = sas.source_authorship_id)))
     JOIN sources.source_publications sp ON ((sp.id = sa.source_publication_id)))
     JOIN publications.authorships a ON (((a.publication_id = sp.publication_id) AND (a.person_id = sa.person_id))))
  WHERE (NOT (EXISTS ( SELECT 1
           FROM persons.persons pe
          WHERE ((pe.id = a.person_id) AND (pe.exclusion IS NOT NULL)))))
  WITH NO DATA;


--
-- Name: authorships_id_seq; Type: SEQUENCE; Schema: publications; Owner: -
--

CREATE SEQUENCE publications.authorships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: authorships_id_seq; Type: SEQUENCE OWNED BY; Schema: publications; Owner: -
--

ALTER SEQUENCE publications.authorships_id_seq OWNED BY publications.authorships.id;


--
-- Name: publication_relations; Type: TABLE; Schema: publications; Owner: -
--

CREATE TABLE publications.publication_relations (
    from_publication_id integer NOT NULL,
    relation_type public.relation_type NOT NULL,
    target_doi text,
    target_publication_id integer,
    source text NOT NULL,
    id bigint NOT NULL,
    CONSTRAINT publication_relations_target_present CHECK (((target_publication_id IS NOT NULL) OR (target_doi IS NOT NULL)))
);


--
-- Name: publication_relations_id_seq; Type: SEQUENCE; Schema: publications; Owner: -
--

ALTER TABLE publications.publication_relations ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME publications.publication_relations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: publication_structures; Type: MATERIALIZED VIEW; Schema: publications; Owner: -
--

CREATE MATERIALIZED VIEW publications.publication_structures AS
 SELECT DISTINCT a.publication_id,
    aus.structure_id
   FROM (publications.authorships a
     JOIN publications.authorship_structures aus ON ((aus.authorship_id = a.id)))
  WHERE (a.roles && ARRAY['author'::text])
  WITH NO DATA;


--
-- Name: publication_subjects; Type: TABLE; Schema: publications; Owner: -
--

CREATE TABLE publications.publication_subjects (
    publication_id integer NOT NULL,
    subject_id integer NOT NULL,
    source public.source_type NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    rejected boolean DEFAULT false NOT NULL
);


--
-- Name: publications; Type: TABLE; Schema: publications; Owner: -
--

CREATE TABLE publications.publications (
    id integer NOT NULL,
    title text NOT NULL,
    title_normalized text,
    doc_type public.doc_type DEFAULT 'other'::public.doc_type,
    pub_year smallint NOT NULL,
    doi text,
    oa_status public.oa_type DEFAULT 'unknown'::public.oa_type,
    journal_id integer,
    container_title text,
    language text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    countries text[],
    sources public.source_type[] DEFAULT '{}'::public.source_type[] NOT NULL,
    meta jsonb,
    is_retracted boolean DEFAULT false NOT NULL,
    unpaywall_checked_at timestamp with time zone,
    subjects_ingested_at timestamp with time zone,
    monograph_id integer,
    license public.license_type,
    deposit_license public.license_type,
    perimeter_evidence public.perimeter_evidence[] DEFAULT '{}'::public.perimeter_evidence[] NOT NULL,
    in_perimeter boolean GENERATED ALWAYS AS ((cardinality(perimeter_evidence) > 0)) STORED NOT NULL
);


--
-- Name: publications_detail; Type: TABLE; Schema: publications; Owner: -
--

CREATE TABLE publications.publications_detail (
    publication_id integer NOT NULL,
    abstract text,
    keywords text[],
    topics jsonb,
    biblio jsonb
);


--
-- Name: publications_id_seq; Type: SEQUENCE; Schema: publications; Owner: -
--

CREATE SEQUENCE publications.publications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: publications_id_seq; Type: SEQUENCE OWNED BY; Schema: publications; Owner: -
--

ALTER SEQUENCE publications.publications_id_seq OWNED BY publications.publications.id;


--
-- Name: subject_cooccurrences; Type: MATERIALIZED VIEW; Schema: publications; Owner: -
--

CREATE MATERIALIZED VIEW publications.subject_cooccurrences AS
 SELECT ps1.subject_id AS subject_a_id,
    ps2.subject_id AS subject_b_id,
    (count(DISTINCT ps1.publication_id))::integer AS count
   FROM (publications.publication_subjects ps1
     JOIN publications.publication_subjects ps2 ON (((ps1.publication_id = ps2.publication_id) AND (ps1.subject_id < ps2.subject_id))))
  WHERE ((NOT ps1.rejected) AND (NOT ps2.rejected))
  GROUP BY ps1.subject_id, ps2.subject_id
 HAVING (count(DISTINCT ps1.publication_id) >= 2)
  WITH NO DATA;


--
-- Name: subjects; Type: TABLE; Schema: publications; Owner: -
--

CREATE TABLE publications.subjects (
    id integer NOT NULL,
    label text NOT NULL,
    language text,
    created_at timestamp with time zone DEFAULT now(),
    usage_count integer DEFAULT 0 NOT NULL
);


--
-- Name: subjects_id_seq; Type: SEQUENCE; Schema: publications; Owner: -
--

CREATE SEQUENCE publications.subjects_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: subjects_id_seq; Type: SEQUENCE OWNED BY; Schema: publications; Owner: -
--

ALTER SEQUENCE publications.subjects_id_seq OWNED BY publications.subjects.id;


--
-- Name: apc_payments; Type: TABLE; Schema: publishing; Owner: -
--

CREATE TABLE publishing.apc_payments (
    id integer NOT NULL,
    lab_name text,
    publisher_name text,
    journal_name text,
    issn text,
    doi text,
    amount_eur_ht numeric(12,2),
    billing_year smallint,
    pub_year smallint,
    budget text,
    institution text,
    coman_id integer,
    source_file text,
    remarks text,
    publication_id integer,
    journal_id integer,
    publisher_id integer,
    created_at timestamp with time zone DEFAULT now(),
    budget_structure_id integer,
    lab_structure_id integer,
    open_access_fee boolean NOT NULL
);


--
-- Name: COLUMN apc_payments.open_access_fee; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.apc_payments.open_access_fee IS 'Vrai pour un frais d''open access (Open APC), faux pour un autre frais de publication (enquête, frais hors OA).';


--
-- Name: apc_payments_id_seq; Type: SEQUENCE; Schema: publishing; Owner: -
--

CREATE SEQUENCE publishing.apc_payments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: apc_payments_id_seq; Type: SEQUENCE OWNED BY; Schema: publishing; Owner: -
--

ALTER SEQUENCE publishing.apc_payments_id_seq OWNED BY publishing.apc_payments.id;


--
-- Name: doi_prefixes; Type: TABLE; Schema: publishing; Owner: -
--

CREATE TABLE publishing.doi_prefixes (
    prefix text NOT NULL,
    ra text NOT NULL,
    publisher_id integer,
    publisher_name_raw text,
    publisher_name_normalized text,
    crossref_member_id integer,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    client_name_raw text,
    client_name_normalized text,
    datacite_client_symbol text,
    crossref_checked_at timestamp with time zone,
    datacite_checked_at timestamp with time zone
);


--
-- Name: journal_doi_namespaces; Type: TABLE; Schema: publishing; Owner: -
--

CREATE TABLE publishing.journal_doi_namespaces (
    namespace text NOT NULL,
    journal_id integer NOT NULL,
    dois integer NOT NULL,
    share double precision NOT NULL
);


--
-- Name: journal_issns; Type: TABLE; Schema: publishing; Owner: -
--

CREATE TABLE publishing.journal_issns (
    id integer NOT NULL,
    issn text NOT NULL,
    journal_id integer,
    support public.issn_support,
    linking boolean DEFAULT false NOT NULL,
    status public.issn_status DEFAULT 'active'::public.issn_status NOT NULL,
    replaced_by text,
    sudoc_checked_at timestamp with time zone
);


--
-- Name: TABLE journal_issns; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON TABLE publishing.journal_issns IS 'ISSN des revues. Sans revue : ISSN vérifié au Sudoc, dont la publication est absente de la base.';


--
-- Name: COLUMN journal_issns.issn; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.journal_issns.issn IS 'Forme normalisée si la valeur est valide, valeur reçue sinon (statut malformed).';


--
-- Name: COLUMN journal_issns.support; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.journal_issns.support IS 'Support de l''ISSN. NULL : inconnu.';


--
-- Name: COLUMN journal_issns.linking; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.journal_issns.linking IS 'Vrai pour l''ISSN-L de la revue.';


--
-- Name: COLUMN journal_issns.status; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.journal_issns.status IS 'active ; malformed (forme ou clé de contrôle fausse) ; cancelled ; related_title (titre précédent ou suivant) ; supplement ; unverified (valeur mise de côté, motif inconnu).';


--
-- Name: COLUMN journal_issns.replaced_by; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.journal_issns.replaced_by IS 'ISSN successeur : titre suivant, forme corrigée d''une valeur mal formée.';


--
-- Name: COLUMN journal_issns.sudoc_checked_at; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.journal_issns.sudoc_checked_at IS 'Date de la vérification de l''ISSN au Sudoc. NULL : jamais vérifié.';


--
-- Name: journal_issns_id_seq; Type: SEQUENCE; Schema: publishing; Owner: -
--

CREATE SEQUENCE publishing.journal_issns_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: journal_issns_id_seq; Type: SEQUENCE OWNED BY; Schema: publishing; Owner: -
--

ALTER SEQUENCE publishing.journal_issns_id_seq OWNED BY publishing.journal_issns.id;


--
-- Name: journal_name_forms; Type: TABLE; Schema: publishing; Owner: -
--

CREATE TABLE publishing.journal_name_forms (
    id integer NOT NULL,
    journal_id integer NOT NULL,
    form_normalized text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    publisher_id integer
);


--
-- Name: journal_name_forms_id_seq; Type: SEQUENCE; Schema: publishing; Owner: -
--

CREATE SEQUENCE publishing.journal_name_forms_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: journal_name_forms_id_seq; Type: SEQUENCE OWNED BY; Schema: publishing; Owner: -
--

ALTER SEQUENCE publishing.journal_name_forms_id_seq OWNED BY publishing.journal_name_forms.id;


--
-- Name: journals; Type: TABLE; Schema: publishing; Owner: -
--

CREATE TABLE publishing.journals (
    id integer NOT NULL,
    title text NOT NULL,
    title_normalized text NOT NULL,
    publisher_id integer,
    openalex_id text,
    is_in_doaj boolean DEFAULT false,
    apc_amount numeric(10,2),
    apc_currency text DEFAULT 'EUR'::text,
    oa_model public.oa_model,
    created_at timestamp with time zone DEFAULT now(),
    journal_type public.journal_type DEFAULT 'unknown'::public.journal_type,
    is_academic boolean DEFAULT true,
    doaj_payload jsonb,
    doaj_imported_at timestamp with time zone,
    pub_count integer DEFAULT 0 NOT NULL,
    manual_fields text[] DEFAULT '{}'::text[] NOT NULL
);


--
-- Name: journals_id_seq; Type: SEQUENCE; Schema: publishing; Owner: -
--

CREATE SEQUENCE publishing.journals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: journals_id_seq; Type: SEQUENCE OWNED BY; Schema: publishing; Owner: -
--

ALTER SEQUENCE publishing.journals_id_seq OWNED BY publishing.journals.id;


--
-- Name: monographs; Type: TABLE; Schema: publishing; Owner: -
--

CREATE TABLE publishing.monographs (
    id integer NOT NULL,
    title text NOT NULL,
    title_normalized text NOT NULL,
    proceedings boolean DEFAULT false NOT NULL,
    year integer,
    isbn text,
    publisher_id integer,
    journal_id integer,
    created_at timestamp with time zone DEFAULT now(),
    eisbn text
);


--
-- Name: COLUMN monographs.proceedings; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.monographs.proceedings IS 'Vrai pour un volume d''actes de congrès, faux pour un livre.';


--
-- Name: COLUMN monographs.year; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.monographs.year IS 'Année de publication. Elle classe les volumes d''actes d''un même congrès.';


--
-- Name: COLUMN monographs.journal_id; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.monographs.journal_id IS 'Collection dont la monographie fait partie, quand cette collection porte un ISSN.';


--
-- Name: monographs_id_seq; Type: SEQUENCE; Schema: publishing; Owner: -
--

CREATE SEQUENCE publishing.monographs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: monographs_id_seq; Type: SEQUENCE OWNED BY; Schema: publishing; Owner: -
--

ALTER SEQUENCE publishing.monographs_id_seq OWNED BY publishing.monographs.id;


--
-- Name: publisher_name_forms; Type: TABLE; Schema: publishing; Owner: -
--

CREATE TABLE publishing.publisher_name_forms (
    id integer NOT NULL,
    publisher_id integer NOT NULL,
    form_normalized text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: publisher_name_forms_id_seq; Type: SEQUENCE; Schema: publishing; Owner: -
--

CREATE SEQUENCE publishing.publisher_name_forms_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: publisher_name_forms_id_seq; Type: SEQUENCE OWNED BY; Schema: publishing; Owner: -
--

ALTER SEQUENCE publishing.publisher_name_forms_id_seq OWNED BY publishing.publisher_name_forms.id;


--
-- Name: publishers; Type: TABLE; Schema: publishing; Owner: -
--

CREATE TABLE publishing.publishers (
    id integer NOT NULL,
    name text NOT NULL,
    name_normalized text NOT NULL,
    openalex_id text,
    country text,
    created_at timestamp with time zone DEFAULT now(),
    publisher_type public.publisher_type DEFAULT 'unknown'::public.publisher_type NOT NULL,
    pub_count integer DEFAULT 0 NOT NULL
);


--
-- Name: publishers_id_seq; Type: SEQUENCE; Schema: publishing; Owner: -
--

CREATE SEQUENCE publishing.publishers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: publishers_id_seq; Type: SEQUENCE OWNED BY; Schema: publishing; Owner: -
--

ALTER SEQUENCE publishing.publishers_id_seq OWNED BY publishing.publishers.id;


--
-- Name: countries; Type: TABLE; Schema: ref; Owner: -
--

CREATE TABLE ref.countries (
    code character(2) NOT NULL,
    name text NOT NULL
);


--
-- Name: language_forms; Type: TABLE; Schema: ref; Owner: -
--

CREATE TABLE ref.language_forms (
    form_normalized text NOT NULL,
    language_code text NOT NULL
);


--
-- Name: TABLE language_forms; Type: COMMENT; Schema: ref; Owner: -
--

COMMENT ON TABLE ref.language_forms IS 'Formes sous lesquelles les sources désignent une langue, en minuscules : codes à deux et trois lettres, nom anglais.';


--
-- Name: languages; Type: TABLE; Schema: ref; Owner: -
--

CREATE TABLE ref.languages (
    code text NOT NULL,
    name text NOT NULL
);


--
-- Name: TABLE languages; Type: COMMENT; Schema: ref; Owner: -
--

COMMENT ON TABLE ref.languages IS 'Référentiel des langues. code : ISO 639-1, ou ISO 639-3 pour une langue sans code à deux lettres. name : nom français, affiché.';


--
-- Name: place_name_forms; Type: TABLE; Schema: ref; Owner: -
--

CREATE TABLE ref.place_name_forms (
    id integer CONSTRAINT country_name_forms_id_not_null NOT NULL,
    iso_code text CONSTRAINT country_name_forms_iso_code_not_null NOT NULL,
    form_normalized text CONSTRAINT country_name_forms_form_normalized_not_null NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    kind text DEFAULT 'country'::text NOT NULL,
    CONSTRAINT place_name_forms_kind_check CHECK ((kind = ANY (ARRAY['country'::text, 'institution'::text, 'city'::text])))
);


--
-- Name: place_name_forms_id_seq; Type: SEQUENCE; Schema: ref; Owner: -
--

CREATE SEQUENCE ref.place_name_forms_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: place_name_forms_id_seq; Type: SEQUENCE OWNED BY; Schema: ref; Owner: -
--

ALTER SEQUENCE ref.place_name_forms_id_seq OWNED BY ref.place_name_forms.id;


--
-- Name: ror_dump_imports; Type: TABLE; Schema: ref; Owner: -
--

CREATE TABLE ref.ror_dump_imports (
    version text NOT NULL,
    imported_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE ror_dump_imports; Type: COMMENT; Schema: ref; Owner: -
--

COMMENT ON TABLE ref.ror_dump_imports IS 'Imports du dump ROR : nom de l''archive importée et date de l''import.';


--
-- Name: ror_organizations; Type: TABLE; Schema: ref; Owner: -
--

CREATE TABLE ref.ror_organizations (
    ror_id text NOT NULL,
    name text NOT NULL,
    country_code character(2) NOT NULL,
    types public.ror_type[] NOT NULL,
    status public.ror_status NOT NULL
);


--
-- Name: TABLE ror_organizations; Type: COMMENT; Schema: ref; Owner: -
--

COMMENT ON TABLE ref.ror_organizations IS 'Organisations du Research Organization Registry, chargées depuis son dump. Référentiel externe en lecture seule : structures.ror_id le relie au référentiel interne.';


--
-- Name: ror_relations; Type: TABLE; Schema: ref; Owner: -
--

CREATE TABLE ref.ror_relations (
    parent_ror_id text NOT NULL,
    child_ror_id text NOT NULL,
    CONSTRAINT ror_relations_no_self_reference CHECK ((parent_ror_id <> child_ror_id))
);


--
-- Name: TABLE ror_relations; Type: COMMENT; Schema: ref; Owner: -
--

COMMENT ON TABLE ref.ror_relations IS 'Relations parent/enfant entre organisations du Research Organization Registry.';


--
-- Name: author_identifying_keys; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.author_identifying_keys (
    id integer NOT NULL,
    person_identifiers jsonb,
    last_name_normalized text NOT NULL,
    first_name_normalized text,
    author_name_normalized text GENERATED ALWAYS AS (
CASE
    WHEN (COALESCE(first_name_normalized, ''::text) = ''::text) THEN last_name_normalized
    WHEN (last_name_normalized = ''::text) THEN first_name_normalized
    ELSE ((first_name_normalized || ' '::text) || last_name_normalized)
END) STORED,
    key_hash text GENERATED ALWAYS AS (md5(((((COALESCE(last_name_normalized, ''::text) || ''::text) || COALESCE(first_name_normalized, ''::text)) || ''::text) || COALESCE((person_identifiers)::text, ''::text)))) STORED
);


--
-- Name: author_identifying_keys_id_seq; Type: SEQUENCE; Schema: sources; Owner: -
--

CREATE SEQUENCE sources.author_identifying_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: author_identifying_keys_id_seq; Type: SEQUENCE OWNED BY; Schema: sources; Owner: -
--

ALTER SEQUENCE sources.author_identifying_keys_id_seq OWNED BY sources.author_identifying_keys.id;


--
-- Name: candidate_dois; Type: VIEW; Schema: sources; Owner: -
--

CREATE VIEW sources.candidate_dois AS
 SELECT sp.doi,
    sp.source
   FROM (sources.source_publications sp
     JOIN publications.publications p ON ((p.id = sp.publication_id)))
  WHERE (p.in_perimeter AND (sp.doi IS NOT NULL))
UNION
 SELECT d.value AS doi,
    sp.source
   FROM ((sources.source_publications sp
     JOIN publications.publications p ON ((p.id = sp.publication_id)))
     CROSS JOIN LATERAL jsonb_array_elements_text((sp.external_ids -> 'related_dois'::text)) d(value))
  WHERE (p.in_perimeter AND (jsonb_typeof((sp.external_ids -> 'related_dois'::text)) = 'array'::text))
UNION
 SELECT pr.target_doi AS doi,
    NULL::public.source_type AS source
   FROM (publications.publication_relations pr
     JOIN publications.publications p ON ((p.id = pr.from_publication_id)))
  WHERE (p.in_perimeter AND (pr.target_doi IS NOT NULL))
UNION
 SELECT ('10.48550/arxiv.'::text || lower((sp.external_ids ->> 'arxiv_id'::text))) AS doi,
    sp.source
   FROM (sources.source_publications sp
     JOIN publications.publications p ON ((p.id = sp.publication_id)))
  WHERE (p.in_perimeter AND ((sp.external_ids ->> 'arxiv_id'::text) IS NOT NULL));


--
-- Name: failed_lookups; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.failed_lookups (
    source public.source_type NOT NULL,
    id_type text NOT NULL,
    id_value text NOT NULL,
    not_found_at timestamp with time zone NOT NULL,
    next_retry timestamp with time zone,
    CONSTRAINT failed_lookups_id_type_check CHECK ((id_type = ANY (ARRAY['doi'::text, 'hal_id'::text, 'nnt'::text])))
);


--
-- Name: TABLE failed_lookups; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON TABLE sources.failed_lookups IS 'Identifiants cherchés en vain dans une source par la phase fetch_missing. next_retry porte la date de la prochaine tentative. Il est NULL quand l''identifiant est natif de la source (le DOI pour Crossref et DataCite, le hal-id pour HAL) : l''échec est alors définitif.';


--
-- Name: source_authorship_addresses_id_seq; Type: SEQUENCE; Schema: sources; Owner: -
--

CREATE SEQUENCE sources.source_authorship_addresses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_authorship_addresses_id_seq; Type: SEQUENCE OWNED BY; Schema: sources; Owner: -
--

ALTER SEQUENCE sources.source_authorship_addresses_id_seq OWNED BY sources.source_authorship_addresses.id;


--
-- Name: source_authorships_id_seq; Type: SEQUENCE; Schema: sources; Owner: -
--

CREATE SEQUENCE sources.source_authorships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_authorships_id_seq; Type: SEQUENCE OWNED BY; Schema: sources; Owner: -
--

ALTER SEQUENCE sources.source_authorships_id_seq OWNED BY sources.source_authorships.id;


--
-- Name: source_publications_id_seq; Type: SEQUENCE; Schema: sources; Owner: -
--

CREATE SEQUENCE sources.source_publications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_publications_id_seq; Type: SEQUENCE OWNED BY; Schema: sources; Owner: -
--

ALTER SEQUENCE sources.source_publications_id_seq OWNED BY sources.source_publications.id;


--
-- Name: staging; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.staging (
    id integer NOT NULL,
    source public.source_type NOT NULL,
    source_id text NOT NULL,
    doi text,
    raw_data jsonb NOT NULL,
    processed boolean DEFAULT false,
    imported_at timestamp with time zone DEFAULT now(),
    raw_hash text,
    last_seen_at timestamp with time zone DEFAULT now(),
    disappeared_at timestamp with time zone,
    authors_truncated boolean DEFAULT false NOT NULL,
    entry_mode text DEFAULT 'bulk'::text NOT NULL,
    CONSTRAINT staging_entry_mode_check CHECK ((entry_mode = ANY (ARRAY['bulk'::text, 'fetch_missing_doi'::text, 'fetch_missing_hal'::text, 'manual_export'::text, 'person_identifier'::text])))
);


--
-- Name: TABLE staging; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON TABLE sources.staging IS 'Documents moissonnés, en transit vers les tables sources. Deux états : à traiter (processed FALSE, raw_data porte le payload de la source), normalisée (processed TRUE, raw_data vidé).';


--
-- Name: COLUMN staging.raw_hash; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.staging.raw_hash IS 'Empreinte md5 servant de clé de détection de changement à l''UPSERT. Calculée via `change_detection_hash`, qui neutralise le bruit volatil propre à la source avant l''empreinte (HAL : horodatage de génération du TEI `label_xml`) — le payload stocké reste, lui, fidèle à la source. L''empreinte ne coïncide donc pas avec `md5(raw_data)` pour les sources normalisées. Cas particulier OpenAlex : `fetch_truncated` n''écrit PAS `raw_hash` quand il complète les authorships d''une publication tronquée à 100 — la ligne garde le hash du payload bulk pour que le bulk suivant ne déclenche pas de réécriture inutile.';


--
-- Name: staging_id_seq; Type: SEQUENCE; Schema: sources; Owner: -
--

CREATE SEQUENCE sources.staging_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: staging_id_seq; Type: SEQUENCE OWNED BY; Schema: sources; Owner: -
--

ALTER SEQUENCE sources.staging_id_seq OWNED BY sources.staging.id;


--
-- Name: address_structures_id_seq; Type: SEQUENCE; Schema: structures; Owner: -
--

CREATE SEQUENCE structures.address_structures_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: address_structures_id_seq; Type: SEQUENCE OWNED BY; Schema: structures; Owner: -
--

ALTER SEQUENCE structures.address_structures_id_seq OWNED BY structures.address_structures.id;


--
-- Name: addresses; Type: TABLE; Schema: structures; Owner: -
--

CREATE TABLE structures.addresses (
    id integer NOT NULL,
    raw_text text NOT NULL,
    normalized_text text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    pub_count integer DEFAULT 0,
    countries character(2)[],
    suggested_countries character(2)[],
    countries_dirty boolean DEFAULT false NOT NULL
);


--
-- Name: addresses_id_seq; Type: SEQUENCE; Schema: structures; Owner: -
--

CREATE SEQUENCE structures.addresses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: addresses_id_seq; Type: SEQUENCE OWNED BY; Schema: structures; Owner: -
--

ALTER SEQUENCE structures.addresses_id_seq OWNED BY structures.addresses.id;


--
-- Name: perimeters_id_seq; Type: SEQUENCE; Schema: structures; Owner: -
--

CREATE SEQUENCE structures.perimeters_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: perimeters_id_seq; Type: SEQUENCE OWNED BY; Schema: structures; Owner: -
--

ALTER SEQUENCE structures.perimeters_id_seq OWNED BY structures.perimeters.id;


--
-- Name: structure_name_forms; Type: TABLE; Schema: structures; Owner: -
--

CREATE TABLE structures.structure_name_forms (
    id integer NOT NULL,
    structure_id integer NOT NULL,
    form_text text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    is_word_boundary boolean DEFAULT false NOT NULL,
    requires_context_of integer[],
    is_excluding boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_structure_name_forms_short_word_boundary CHECK (((char_length(form_text) > 6) OR is_word_boundary))
);


--
-- Name: structure_name_forms_id_seq; Type: SEQUENCE; Schema: structures; Owner: -
--

CREATE SEQUENCE structures.structure_name_forms_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: structure_name_forms_id_seq; Type: SEQUENCE OWNED BY; Schema: structures; Owner: -
--

ALTER SEQUENCE structures.structure_name_forms_id_seq OWNED BY structures.structure_name_forms.id;


--
-- Name: structure_tutelles; Type: TABLE; Schema: structures; Owner: -
--

CREATE TABLE structures.structure_tutelles (
    id integer NOT NULL,
    parent_id integer NOT NULL,
    child_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT structure_tutelles_no_self_reference CHECK ((parent_id <> child_id))
);


--
-- Name: structure_tutelles_id_seq; Type: SEQUENCE; Schema: structures; Owner: -
--

CREATE SEQUENCE structures.structure_tutelles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: structure_tutelles_id_seq; Type: SEQUENCE OWNED BY; Schema: structures; Owner: -
--

ALTER SEQUENCE structures.structure_tutelles_id_seq OWNED BY structures.structure_tutelles.id;


--
-- Name: structures_id_seq; Type: SEQUENCE; Schema: structures; Owner: -
--

CREATE SEQUENCE structures.structures_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: structures_id_seq; Type: SEQUENCE OWNED BY; Schema: structures; Owner: -
--

ALTER SEQUENCE structures.structures_id_seq OWNED BY structures.structures.id;


--
-- Name: audit_log id; Type: DEFAULT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.audit_log ALTER COLUMN id SET DEFAULT nextval('ops.audit_log_id_seq'::regclass);


--
-- Name: distinct_persons id; Type: DEFAULT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.distinct_persons ALTER COLUMN id SET DEFAULT nextval('persons.distinct_persons_id_seq'::regclass);


--
-- Name: person_identifiers id; Type: DEFAULT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.person_identifiers ALTER COLUMN id SET DEFAULT nextval('persons.person_identifiers_id_seq'::regclass);


--
-- Name: persons id; Type: DEFAULT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.persons ALTER COLUMN id SET DEFAULT nextval('persons.persons_id_seq'::regclass);


--
-- Name: persons_rh id; Type: DEFAULT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.persons_rh ALTER COLUMN id SET DEFAULT nextval('persons.persons_rh_id_seq'::regclass);


--
-- Name: authorships id; Type: DEFAULT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.authorships ALTER COLUMN id SET DEFAULT nextval('publications.authorships_id_seq'::regclass);


--
-- Name: publications id; Type: DEFAULT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publications ALTER COLUMN id SET DEFAULT nextval('publications.publications_id_seq'::regclass);


--
-- Name: subjects id; Type: DEFAULT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.subjects ALTER COLUMN id SET DEFAULT nextval('publications.subjects_id_seq'::regclass);


--
-- Name: apc_payments id; Type: DEFAULT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.apc_payments ALTER COLUMN id SET DEFAULT nextval('publishing.apc_payments_id_seq'::regclass);


--
-- Name: journal_issns id; Type: DEFAULT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.journal_issns ALTER COLUMN id SET DEFAULT nextval('publishing.journal_issns_id_seq'::regclass);


--
-- Name: journal_name_forms id; Type: DEFAULT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.journal_name_forms ALTER COLUMN id SET DEFAULT nextval('publishing.journal_name_forms_id_seq'::regclass);


--
-- Name: journals id; Type: DEFAULT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.journals ALTER COLUMN id SET DEFAULT nextval('publishing.journals_id_seq'::regclass);


--
-- Name: monographs id; Type: DEFAULT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.monographs ALTER COLUMN id SET DEFAULT nextval('publishing.monographs_id_seq'::regclass);


--
-- Name: publisher_name_forms id; Type: DEFAULT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.publisher_name_forms ALTER COLUMN id SET DEFAULT nextval('publishing.publisher_name_forms_id_seq'::regclass);


--
-- Name: publishers id; Type: DEFAULT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.publishers ALTER COLUMN id SET DEFAULT nextval('publishing.publishers_id_seq'::regclass);


--
-- Name: place_name_forms id; Type: DEFAULT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.place_name_forms ALTER COLUMN id SET DEFAULT nextval('ref.place_name_forms_id_seq'::regclass);


--
-- Name: author_identifying_keys id; Type: DEFAULT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.author_identifying_keys ALTER COLUMN id SET DEFAULT nextval('sources.author_identifying_keys_id_seq'::regclass);


--
-- Name: source_authorship_addresses id; Type: DEFAULT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorship_addresses ALTER COLUMN id SET DEFAULT nextval('sources.source_authorship_addresses_id_seq'::regclass);


--
-- Name: source_authorships id; Type: DEFAULT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorships ALTER COLUMN id SET DEFAULT nextval('sources.source_authorships_id_seq'::regclass);


--
-- Name: source_publications id; Type: DEFAULT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_publications ALTER COLUMN id SET DEFAULT nextval('sources.source_publications_id_seq'::regclass);


--
-- Name: staging id; Type: DEFAULT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.staging ALTER COLUMN id SET DEFAULT nextval('sources.staging_id_seq'::regclass);


--
-- Name: address_structures id; Type: DEFAULT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.address_structures ALTER COLUMN id SET DEFAULT nextval('structures.address_structures_id_seq'::regclass);


--
-- Name: addresses id; Type: DEFAULT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.addresses ALTER COLUMN id SET DEFAULT nextval('structures.addresses_id_seq'::regclass);


--
-- Name: perimeters id; Type: DEFAULT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.perimeters ALTER COLUMN id SET DEFAULT nextval('structures.perimeters_id_seq'::regclass);


--
-- Name: structure_name_forms id; Type: DEFAULT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structure_name_forms ALTER COLUMN id SET DEFAULT nextval('structures.structure_name_forms_id_seq'::regclass);


--
-- Name: structure_tutelles id; Type: DEFAULT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structure_tutelles ALTER COLUMN id SET DEFAULT nextval('structures.structure_tutelles_id_seq'::regclass);


--
-- Name: structures id; Type: DEFAULT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structures ALTER COLUMN id SET DEFAULT nextval('structures.structures_id_seq'::regclass);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: config config_pkey; Type: CONSTRAINT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.config
    ADD CONSTRAINT config_pkey PRIMARY KEY (key);


--
-- Name: pipeline_phase_executions pipeline_phase_executions_pkey; Type: CONSTRAINT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.pipeline_phase_executions
    ADD CONSTRAINT pipeline_phase_executions_pkey PRIMARY KEY (id);


--
-- Name: confirmed_authorships confirmed_authorships_pkey; Type: CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.confirmed_authorships
    ADD CONSTRAINT confirmed_authorships_pkey PRIMARY KEY (source_authorship_id);


--
-- Name: distinct_persons distinct_persons_person_id_a_person_id_b_key; Type: CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.distinct_persons
    ADD CONSTRAINT distinct_persons_person_id_a_person_id_b_key UNIQUE (person_id_a, person_id_b);


--
-- Name: distinct_persons distinct_persons_pkey; Type: CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.distinct_persons
    ADD CONSTRAINT distinct_persons_pkey PRIMARY KEY (id);


--
-- Name: person_identifiers person_identifiers_id_type_id_value_key; Type: CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.person_identifiers
    ADD CONSTRAINT person_identifiers_id_type_id_value_key UNIQUE (id_type, id_value);


--
-- Name: person_identifiers person_identifiers_pkey; Type: CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.person_identifiers
    ADD CONSTRAINT person_identifiers_pkey PRIMARY KEY (id);


--
-- Name: person_name_forms person_name_forms_pkey; Type: CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.person_name_forms
    ADD CONSTRAINT person_name_forms_pkey PRIMARY KEY (name_form, person_id);


--
-- Name: persons persons_pkey; Type: CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.persons
    ADD CONSTRAINT persons_pkey PRIMARY KEY (id);


--
-- Name: persons_rh persons_rh_person_id_key; Type: CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.persons_rh
    ADD CONSTRAINT persons_rh_person_id_key UNIQUE (person_id);


--
-- Name: persons_rh persons_rh_pkey; Type: CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.persons_rh
    ADD CONSTRAINT persons_rh_pkey PRIMARY KEY (id);


--
-- Name: rejected_authorships rejected_authorships_pkey; Type: CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.rejected_authorships
    ADD CONSTRAINT rejected_authorships_pkey PRIMARY KEY (source_publication_id, person_id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: merge_redirects merge_redirects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.merge_redirects
    ADD CONSTRAINT merge_redirects_pkey PRIMARY KEY (entity, absorbed_id);


--
-- Name: authorships authorships_pkey; Type: CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.authorships
    ADD CONSTRAINT authorships_pkey PRIMARY KEY (id);


--
-- Name: authorships authorships_publication_person_uq; Type: CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.authorships
    ADD CONSTRAINT authorships_publication_person_uq UNIQUE (publication_id, person_id);


--
-- Name: publication_relations publication_relations_pkey; Type: CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publication_relations
    ADD CONSTRAINT publication_relations_pkey PRIMARY KEY (id);


--
-- Name: publication_relations publication_relations_uq; Type: CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publication_relations
    ADD CONSTRAINT publication_relations_uq UNIQUE NULLS NOT DISTINCT (from_publication_id, relation_type, target_publication_id, target_doi);


--
-- Name: publication_subjects publication_subjects_pkey; Type: CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publication_subjects
    ADD CONSTRAINT publication_subjects_pkey PRIMARY KEY (publication_id, subject_id, source);


--
-- Name: publications_detail publications_detail_pkey; Type: CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publications_detail
    ADD CONSTRAINT publications_detail_pkey PRIMARY KEY (publication_id);


--
-- Name: publications publications_pkey; Type: CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publications
    ADD CONSTRAINT publications_pkey PRIMARY KEY (id);


--
-- Name: subjects subjects_pkey; Type: CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.subjects
    ADD CONSTRAINT subjects_pkey PRIMARY KEY (id);


--
-- Name: apc_payments apc_payments_payment_key; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.apc_payments
    ADD CONSTRAINT apc_payments_payment_key UNIQUE (doi, institution, amount_eur_ht, open_access_fee);


--
-- Name: apc_payments apc_payments_pkey; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.apc_payments
    ADD CONSTRAINT apc_payments_pkey PRIMARY KEY (id);


--
-- Name: doi_prefixes doi_prefixes_pkey; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.doi_prefixes
    ADD CONSTRAINT doi_prefixes_pkey PRIMARY KEY (prefix);


--
-- Name: journal_doi_namespaces journal_doi_namespaces_pkey; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.journal_doi_namespaces
    ADD CONSTRAINT journal_doi_namespaces_pkey PRIMARY KEY (namespace);


--
-- Name: journal_issns journal_issns_pkey; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.journal_issns
    ADD CONSTRAINT journal_issns_pkey PRIMARY KEY (id);


--
-- Name: journal_name_forms journal_name_forms_pkey; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.journal_name_forms
    ADD CONSTRAINT journal_name_forms_pkey PRIMARY KEY (id);


--
-- Name: journals journals_openalex_id_key; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.journals
    ADD CONSTRAINT journals_openalex_id_key UNIQUE (openalex_id);


--
-- Name: journals journals_pkey; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.journals
    ADD CONSTRAINT journals_pkey PRIMARY KEY (id);


--
-- Name: monographs monographs_eisbn_key; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.monographs
    ADD CONSTRAINT monographs_eisbn_key UNIQUE (eisbn);


--
-- Name: monographs monographs_isbn_key; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.monographs
    ADD CONSTRAINT monographs_isbn_key UNIQUE (isbn);


--
-- Name: monographs monographs_pkey; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.monographs
    ADD CONSTRAINT monographs_pkey PRIMARY KEY (id);


--
-- Name: publisher_name_forms publisher_name_forms_form_normalized_key; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.publisher_name_forms
    ADD CONSTRAINT publisher_name_forms_form_normalized_key UNIQUE (form_normalized);


--
-- Name: publisher_name_forms publisher_name_forms_pkey; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.publisher_name_forms
    ADD CONSTRAINT publisher_name_forms_pkey PRIMARY KEY (id);


--
-- Name: publishers publishers_openalex_id_key; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.publishers
    ADD CONSTRAINT publishers_openalex_id_key UNIQUE (openalex_id);


--
-- Name: publishers publishers_pkey; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.publishers
    ADD CONSTRAINT publishers_pkey PRIMARY KEY (id);


--
-- Name: journal_name_forms uq_jnl_nf_form_publisher; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.journal_name_forms
    ADD CONSTRAINT uq_jnl_nf_form_publisher UNIQUE (form_normalized, publisher_id);


--
-- Name: journal_issns uq_journal_issns_issn_journal; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.journal_issns
    ADD CONSTRAINT uq_journal_issns_issn_journal UNIQUE NULLS NOT DISTINCT (issn, journal_id);


--
-- Name: countries countries_pkey; Type: CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.countries
    ADD CONSTRAINT countries_pkey PRIMARY KEY (code);


--
-- Name: hal_structure_aliases hal_structure_aliases_pkey; Type: CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.hal_structure_aliases
    ADD CONSTRAINT hal_structure_aliases_pkey PRIMARY KEY (alias_id);


--
-- Name: hal_structure_relations hal_structure_relations_pkey; Type: CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.hal_structure_relations
    ADD CONSTRAINT hal_structure_relations_pkey PRIMARY KEY (parent_id, child_id);


--
-- Name: hal_structures hal_structures_pkey; Type: CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.hal_structures
    ADD CONSTRAINT hal_structures_pkey PRIMARY KEY (hal_structure_id);


--
-- Name: language_forms language_forms_pkey; Type: CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.language_forms
    ADD CONSTRAINT language_forms_pkey PRIMARY KEY (form_normalized);


--
-- Name: languages languages_pkey; Type: CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.languages
    ADD CONSTRAINT languages_pkey PRIMARY KEY (code);


--
-- Name: place_name_forms place_name_forms_form_normalized_key; Type: CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.place_name_forms
    ADD CONSTRAINT place_name_forms_form_normalized_key UNIQUE (form_normalized);


--
-- Name: place_name_forms place_name_forms_pkey; Type: CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.place_name_forms
    ADD CONSTRAINT place_name_forms_pkey PRIMARY KEY (id);


--
-- Name: ror_dump_imports ror_dump_imports_pkey; Type: CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.ror_dump_imports
    ADD CONSTRAINT ror_dump_imports_pkey PRIMARY KEY (version);


--
-- Name: ror_organizations ror_organizations_pkey; Type: CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.ror_organizations
    ADD CONSTRAINT ror_organizations_pkey PRIMARY KEY (ror_id);


--
-- Name: ror_relations ror_relations_pkey; Type: CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.ror_relations
    ADD CONSTRAINT ror_relations_pkey PRIMARY KEY (parent_ror_id, child_ror_id);


--
-- Name: author_identifying_keys author_identifying_keys_key; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.author_identifying_keys
    ADD CONSTRAINT author_identifying_keys_key UNIQUE NULLS NOT DISTINCT (last_name_normalized, first_name_normalized, person_identifiers);


--
-- Name: author_identifying_keys author_identifying_keys_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.author_identifying_keys
    ADD CONSTRAINT author_identifying_keys_pkey PRIMARY KEY (id);


--
-- Name: failed_lookups failed_lookups_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.failed_lookups
    ADD CONSTRAINT failed_lookups_pkey PRIMARY KEY (source, id_type, id_value);


--
-- Name: source_authorship_addresses source_authorship_addresses_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorship_addresses
    ADD CONSTRAINT source_authorship_addresses_pkey PRIMARY KEY (id);


--
-- Name: source_authorship_addresses source_authorship_addresses_source_authorship_id_address_id_key; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorship_addresses
    ADD CONSTRAINT source_authorship_addresses_source_authorship_id_address_id_key UNIQUE (source_authorship_id, address_id);


--
-- Name: source_authorship_hal_structures source_authorship_hal_structures_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorship_hal_structures
    ADD CONSTRAINT source_authorship_hal_structures_pkey PRIMARY KEY (source_authorship_id, hal_structure_id);


--
-- Name: source_authorship_rors source_authorship_rors_key; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorship_rors
    ADD CONSTRAINT source_authorship_rors_key UNIQUE NULLS NOT DISTINCT (source_authorship_id, ror_id, address_id);


--
-- Name: source_authorships source_authorships_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorships
    ADD CONSTRAINT source_authorships_pkey PRIMARY KEY (id);


--
-- Name: source_authorships source_authorships_pub_pos_key; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorships
    ADD CONSTRAINT source_authorships_pub_pos_key UNIQUE (source_publication_id, author_position) DEFERRABLE;


--
-- Name: source_publications source_publications_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_publications
    ADD CONSTRAINT source_publications_pkey PRIMARY KEY (id);


--
-- Name: source_publications source_publications_source_source_id_key; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_publications
    ADD CONSTRAINT source_publications_source_source_id_key UNIQUE (source, source_id);


--
-- Name: staging staging_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.staging
    ADD CONSTRAINT staging_pkey PRIMARY KEY (id);


--
-- Name: staging staging_source_source_id_key; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.staging
    ADD CONSTRAINT staging_source_source_id_key UNIQUE (source, source_id);


--
-- Name: address_structures address_structures_address_id_structure_id_key; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.address_structures
    ADD CONSTRAINT address_structures_address_id_structure_id_key UNIQUE (address_id, structure_id);


--
-- Name: address_structures address_structures_pkey; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.address_structures
    ADD CONSTRAINT address_structures_pkey PRIMARY KEY (id);


--
-- Name: addresses addresses_pkey; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.addresses
    ADD CONSTRAINT addresses_pkey PRIMARY KEY (id);


--
-- Name: perimeter_structures perimeter_structures_pkey; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.perimeter_structures
    ADD CONSTRAINT perimeter_structures_pkey PRIMARY KEY (perimeter_id, structure_id);


--
-- Name: perimeters perimeters_code_key; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.perimeters
    ADD CONSTRAINT perimeters_code_key UNIQUE (code);


--
-- Name: perimeters perimeters_pkey; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.perimeters
    ADD CONSTRAINT perimeters_pkey PRIMARY KEY (id);


--
-- Name: structure_name_forms structure_name_forms_pkey; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structure_name_forms
    ADD CONSTRAINT structure_name_forms_pkey PRIMARY KEY (id);


--
-- Name: structure_tutelles structure_tutelles_parent_id_child_id_key; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structure_tutelles
    ADD CONSTRAINT structure_tutelles_parent_id_child_id_key UNIQUE (parent_id, child_id);


--
-- Name: structure_tutelles structure_tutelles_pkey; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structure_tutelles
    ADD CONSTRAINT structure_tutelles_pkey PRIMARY KEY (id);


--
-- Name: structures structures_code_key; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structures
    ADD CONSTRAINT structures_code_key UNIQUE (code);


--
-- Name: structures structures_pkey; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structures
    ADD CONSTRAINT structures_pkey PRIMARY KEY (id);


--
-- Name: structures structures_ror_id_key; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structures
    ADD CONSTRAINT structures_ror_id_key UNIQUE (ror_id);


--
-- Name: structure_name_forms uq_snf_structure_form; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structure_name_forms
    ADD CONSTRAINT uq_snf_structure_form UNIQUE (structure_id, form_text);


--
-- Name: audit_log_aggregate_idx; Type: INDEX; Schema: ops; Owner: -
--

CREATE INDEX audit_log_aggregate_idx ON ops.audit_log USING btree (aggregate_type, aggregate_id);


--
-- Name: audit_log_created_at_idx; Type: INDEX; Schema: ops; Owner: -
--

CREATE INDEX audit_log_created_at_idx ON ops.audit_log USING btree (created_at DESC);


--
-- Name: audit_log_event_type_idx; Type: INDEX; Schema: ops; Owner: -
--

CREATE INDEX audit_log_event_type_idx ON ops.audit_log USING btree (event_type, created_at DESC);


--
-- Name: idx_phase_exec_phase; Type: INDEX; Schema: ops; Owner: -
--

CREATE INDEX idx_phase_exec_phase ON ops.pipeline_phase_executions USING btree (phase);


--
-- Name: idx_phase_exec_run_id; Type: INDEX; Schema: ops; Owner: -
--

CREATE INDEX idx_phase_exec_run_id ON ops.pipeline_phase_executions USING btree (run_id);


--
-- Name: idx_phase_exec_started_at; Type: INDEX; Schema: ops; Owner: -
--

CREATE INDEX idx_phase_exec_started_at ON ops.pipeline_phase_executions USING btree (started_at DESC);


--
-- Name: idx_confirmed_authorships_person; Type: INDEX; Schema: persons; Owner: -
--

CREATE INDEX idx_confirmed_authorships_person ON persons.confirmed_authorships USING btree (person_id);


--
-- Name: idx_person_ids_lookup; Type: INDEX; Schema: persons; Owner: -
--

CREATE INDEX idx_person_ids_lookup ON persons.person_identifiers USING btree (id_type, id_value);


--
-- Name: idx_person_ids_person; Type: INDEX; Schema: persons; Owner: -
--

CREATE INDEX idx_person_ids_person ON persons.person_identifiers USING btree (person_id);


--
-- Name: idx_persons_name; Type: INDEX; Schema: persons; Owner: -
--

CREATE INDEX idx_persons_name ON persons.persons USING btree (last_name_normalized, first_name_normalized);


--
-- Name: idx_persons_rh_department; Type: INDEX; Schema: persons; Owner: -
--

CREATE INDEX idx_persons_rh_department ON persons.persons_rh USING btree (department_name);


--
-- Name: idx_persons_rh_person_id; Type: INDEX; Schema: persons; Owner: -
--

CREATE INDEX idx_persons_rh_person_id ON persons.persons_rh USING btree (person_id);


--
-- Name: idx_pnf_person_id; Type: INDEX; Schema: persons; Owner: -
--

CREATE INDEX idx_pnf_person_id ON persons.person_name_forms USING btree (person_id);


--
-- Name: idx_rejected_authorships_person; Type: INDEX; Schema: persons; Owner: -
--

CREATE INDEX idx_rejected_authorships_person ON persons.rejected_authorships USING btree (person_id);


--
-- Name: idx_merge_redirects_kept; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_merge_redirects_kept ON public.merge_redirects USING btree (entity, kept_id);


--
-- Name: authorship_structures_pkey; Type: INDEX; Schema: publications; Owner: -
--

CREATE UNIQUE INDEX authorship_structures_pkey ON publications.authorship_structures USING btree (authorship_id, structure_id);


--
-- Name: idx_authorship_structures_structure_id; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_authorship_structures_structure_id ON publications.authorship_structures USING btree (structure_id);


--
-- Name: idx_authorships_corresponding_uca; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_authorships_corresponding_uca ON publications.authorships USING btree (publication_id) WHERE ((is_corresponding = true) AND (in_perimeter = true));


--
-- Name: idx_authorships_person; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_authorships_person ON publications.authorships USING btree (person_id) WHERE (person_id IS NOT NULL);


--
-- Name: idx_authorships_pub; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_authorships_pub ON publications.authorships USING btree (publication_id);


--
-- Name: idx_authorships_pub_uca; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_authorships_pub_uca ON publications.authorships USING btree (publication_id) WHERE (in_perimeter = true);


--
-- Name: idx_authorships_uca; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_authorships_uca ON publications.authorships USING btree (in_perimeter) WHERE (in_perimeter = true);


--
-- Name: idx_pub_countries; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_pub_countries ON publications.publications USING gin (countries) WHERE (countries IS NOT NULL);


--
-- Name: idx_pub_title_trgm; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_pub_title_trgm ON publications.publications USING gin (title_normalized public.gin_trgm_ops);


--
-- Name: idx_pub_unpaywall_checked; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_pub_unpaywall_checked ON publications.publications USING btree (unpaywall_checked_at NULLS FIRST) WHERE (doi IS NOT NULL);


--
-- Name: idx_publication_relations_target_doi; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publication_relations_target_doi ON publications.publication_relations USING btree (target_doi);


--
-- Name: idx_publication_relations_target_pub; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publication_relations_target_pub ON publications.publication_relations USING btree (target_publication_id) WHERE (target_publication_id IS NOT NULL);


--
-- Name: idx_publication_structures_structure; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publication_structures_structure ON publications.publication_structures USING btree (structure_id);


--
-- Name: idx_publications_in_perimeter_journal; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_in_perimeter_journal ON publications.publications USING btree (journal_id) WHERE in_perimeter;


--
-- Name: idx_publications_in_perimeter_year; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_in_perimeter_year ON publications.publications USING btree (pub_year DESC) WHERE in_perimeter;


--
-- Name: idx_publications_journal; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_journal ON publications.publications USING btree (journal_id);


--
-- Name: idx_publications_meta; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_meta ON publications.publications USING gin (meta) WHERE (meta IS NOT NULL);


--
-- Name: idx_publications_monograph; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_monograph ON publications.publications USING btree (monograph_id) WHERE (monograph_id IS NOT NULL);


--
-- Name: idx_publications_sources; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_sources ON publications.publications USING gin (sources);


--
-- Name: idx_publications_titlenorm_year; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_titlenorm_year ON publications.publications USING btree (title_normalized, pub_year);


--
-- Name: idx_publications_year; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_year ON publications.publications USING btree (pub_year);


--
-- Name: idx_publications_year_type; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_year_type ON publications.publications USING btree (pub_year, doc_type);


--
-- Name: publication_structures_pub_struct; Type: INDEX; Schema: publications; Owner: -
--

CREATE UNIQUE INDEX publication_structures_pub_struct ON publications.publication_structures USING btree (publication_id, structure_id);


--
-- Name: publication_subjects_subject_idx; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX publication_subjects_subject_idx ON publications.publication_subjects USING btree (subject_id);


--
-- Name: publications_doi_lower_key; Type: INDEX; Schema: publications; Owner: -
--

CREATE UNIQUE INDEX publications_doi_lower_key ON publications.publications USING btree (lower(doi)) WHERE (doi IS NOT NULL);


--
-- Name: subject_cooccurrences_b_idx; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX subject_cooccurrences_b_idx ON publications.subject_cooccurrences USING btree (subject_b_id);


--
-- Name: subject_cooccurrences_count_idx; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX subject_cooccurrences_count_idx ON publications.subject_cooccurrences USING btree (count DESC);


--
-- Name: subject_cooccurrences_pkey; Type: INDEX; Schema: publications; Owner: -
--

CREATE UNIQUE INDEX subject_cooccurrences_pkey ON publications.subject_cooccurrences USING btree (subject_a_id, subject_b_id);


--
-- Name: subjects_label_key; Type: INDEX; Schema: publications; Owner: -
--

CREATE UNIQUE INDEX subjects_label_key ON publications.subjects USING btree (lower(label));


--
-- Name: subjects_label_norm_trgm_idx; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX subjects_label_norm_trgm_idx ON publications.subjects USING gin (public.normalize_name_form(label) public.gin_trgm_ops);


--
-- Name: subjects_usage_count_idx; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX subjects_usage_count_idx ON publications.subjects USING btree (usage_count DESC);


--
-- Name: idx_apc_budget_struct; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_apc_budget_struct ON publishing.apc_payments USING btree (budget_structure_id) WHERE (budget_structure_id IS NOT NULL);


--
-- Name: idx_apc_doi; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_apc_doi ON publishing.apc_payments USING btree (lower(doi)) WHERE (doi IS NOT NULL);


--
-- Name: idx_apc_lab_struct; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_apc_lab_struct ON publishing.apc_payments USING btree (lab_structure_id) WHERE (lab_structure_id IS NOT NULL);


--
-- Name: idx_apc_pub; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_apc_pub ON publishing.apc_payments USING btree (publication_id) WHERE (publication_id IS NOT NULL);


--
-- Name: idx_doi_prefixes_client_name_normalized; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_doi_prefixes_client_name_normalized ON publishing.doi_prefixes USING btree (client_name_normalized) WHERE (client_name_normalized IS NOT NULL);


--
-- Name: idx_doi_prefixes_datacite_client_symbol; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_doi_prefixes_datacite_client_symbol ON publishing.doi_prefixes USING btree (datacite_client_symbol) WHERE (datacite_client_symbol IS NOT NULL);


--
-- Name: idx_doi_prefixes_publisher; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_doi_prefixes_publisher ON publishing.doi_prefixes USING btree (publisher_id) WHERE (publisher_id IS NOT NULL);


--
-- Name: idx_doi_prefixes_publisher_name_normalized; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_doi_prefixes_publisher_name_normalized ON publishing.doi_prefixes USING btree (publisher_name_normalized) WHERE (publisher_id IS NULL);


--
-- Name: idx_doi_prefixes_ra; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_doi_prefixes_ra ON publishing.doi_prefixes USING btree (ra);


--
-- Name: idx_jnl_nf_journal; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_jnl_nf_journal ON publishing.journal_name_forms USING btree (journal_id);


--
-- Name: idx_journal_issns_journal; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_journal_issns_journal ON publishing.journal_issns USING btree (journal_id);


--
-- Name: idx_journals_publisher; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_journals_publisher ON publishing.journals USING btree (publisher_id);


--
-- Name: idx_journals_titlenorm; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_journals_titlenorm ON publishing.journals USING btree (title_normalized);


--
-- Name: idx_monographs_journal; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_monographs_journal ON publishing.monographs USING btree (journal_id);


--
-- Name: idx_monographs_publisher; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_monographs_publisher ON publishing.monographs USING btree (publisher_id);


--
-- Name: idx_monographs_title_normalized; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_monographs_title_normalized ON publishing.monographs USING btree (title_normalized);


--
-- Name: idx_pub_nf_publisher; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_pub_nf_publisher ON publishing.publisher_name_forms USING btree (publisher_id);


--
-- Name: idx_publishers_name_norm; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_publishers_name_norm ON publishing.publishers USING btree (name_normalized);


--
-- Name: idx_publishers_name_trgm; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_publishers_name_trgm ON publishing.publishers USING gin (name public.gin_trgm_ops);


--
-- Name: ix_journal_doi_namespaces_journal_id; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX ix_journal_doi_namespaces_journal_id ON publishing.journal_doi_namespaces USING btree (journal_id);


--
-- Name: uq_journal_issns_linking; Type: INDEX; Schema: publishing; Owner: -
--

CREATE UNIQUE INDEX uq_journal_issns_linking ON publishing.journal_issns USING btree (journal_id) WHERE linking;


--
-- Name: idx_pnf_iso; Type: INDEX; Schema: ref; Owner: -
--

CREATE INDEX idx_pnf_iso ON ref.place_name_forms USING btree (iso_code);


--
-- Name: ix_hal_structure_aliases_hal_structure_id; Type: INDEX; Schema: ref; Owner: -
--

CREATE INDEX ix_hal_structure_aliases_hal_structure_id ON ref.hal_structure_aliases USING btree (hal_structure_id);


--
-- Name: ix_hal_structure_relations_child_id; Type: INDEX; Schema: ref; Owner: -
--

CREATE INDEX ix_hal_structure_relations_child_id ON ref.hal_structure_relations USING btree (child_id);


--
-- Name: ix_hal_structures_ror_id; Type: INDEX; Schema: ref; Owner: -
--

CREATE INDEX ix_hal_structures_ror_id ON ref.hal_structures USING btree (ror_id);


--
-- Name: ix_hal_structures_structure_id; Type: INDEX; Schema: ref; Owner: -
--

CREATE INDEX ix_hal_structures_structure_id ON ref.hal_structures USING btree (structure_id);


--
-- Name: ix_ror_relations_child_ror_id; Type: INDEX; Schema: ref; Owner: -
--

CREATE INDEX ix_ror_relations_child_ror_id ON ref.ror_relations USING btree (child_ror_id);


--
-- Name: author_identifying_keys_author_name_normalized_idx; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX author_identifying_keys_author_name_normalized_idx ON sources.author_identifying_keys USING btree (author_name_normalized);


--
-- Name: author_identifying_keys_key_hash_idx; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX author_identifying_keys_key_hash_idx ON sources.author_identifying_keys USING btree (key_hash);


--
-- Name: idx_sa_countries_dirty; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_sa_countries_dirty ON sources.source_authorships USING btree (source_publication_id) WHERE countries_dirty;


--
-- Name: idx_sa_identity; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_sa_identity ON sources.source_authorships USING btree (identity_id);


--
-- Name: idx_sa_in_perimeter; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_sa_in_perimeter ON sources.source_authorships USING btree (source_publication_id) WHERE (in_perimeter = true);


--
-- Name: idx_sa_orphan_in_perimeter; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_sa_orphan_in_perimeter ON sources.source_authorships USING btree (id) WHERE ((person_id IS NULL) AND in_perimeter);


--
-- Name: idx_sa_person; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_sa_person ON sources.source_authorships USING btree (person_id, identity_id) WHERE (person_id IS NOT NULL);


--
-- Name: idx_sa_pub_person; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_sa_pub_person ON sources.source_authorships USING btree (source_publication_id, person_id) WHERE (person_id IS NOT NULL);


--
-- Name: idx_saa_address; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_saa_address ON sources.source_authorship_addresses USING btree (address_id);


--
-- Name: idx_source_authorship_structures_structure_id; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_authorship_structures_structure_id ON sources.source_authorship_structures USING btree (structure_id);


--
-- Name: idx_source_publications_monograph; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_publications_monograph ON sources.source_publications USING btree (monograph_id) WHERE (monograph_id IS NOT NULL);


--
-- Name: idx_source_pubs_countries; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_pubs_countries ON sources.source_publications USING gin (countries) WHERE (countries IS NOT NULL);


--
-- Name: idx_source_pubs_doi; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_pubs_doi ON sources.source_publications USING btree (doi) WHERE (doi IS NOT NULL);


--
-- Name: idx_source_pubs_external_ids; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_pubs_external_ids ON sources.source_publications USING gin (external_ids) WHERE (external_ids <> '{}'::jsonb);


--
-- Name: idx_source_pubs_first_hal_id; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_pubs_first_hal_id ON sources.source_publications USING btree ((((external_ids -> 'hal_id'::text) ->> 0))) WHERE (((external_ids -> 'hal_id'::text) ->> 0) IS NOT NULL);


--
-- Name: idx_source_pubs_hal_collections; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_pubs_hal_collections ON sources.source_publications USING gin (hal_collections) WHERE (hal_collections IS NOT NULL);


--
-- Name: idx_source_pubs_journal; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_pubs_journal ON sources.source_publications USING btree (journal_id) WHERE (journal_id IS NOT NULL);


--
-- Name: idx_source_pubs_keys_dirty; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_pubs_keys_dirty ON sources.source_publications USING btree (keys_dirty) WHERE keys_dirty;


--
-- Name: idx_source_pubs_metadata_block; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_pubs_metadata_block ON sources.source_publications USING btree (title_normalized, pub_year, doc_type);


--
-- Name: idx_source_pubs_nnt; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_pubs_nnt ON sources.source_publications USING btree (((external_ids ->> 'nnt'::text))) WHERE ((external_ids ->> 'nnt'::text) IS NOT NULL);


--
-- Name: idx_source_pubs_pmid; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_pubs_pmid ON sources.source_publications USING btree (((external_ids ->> 'pmid'::text))) WHERE ((external_ids ->> 'pmid'::text) IS NOT NULL);


--
-- Name: idx_source_pubs_pub; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_pubs_pub ON sources.source_publications USING btree (publication_id) WHERE (publication_id IS NOT NULL);


--
-- Name: idx_source_pubs_staging; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_pubs_staging ON sources.source_publications USING btree (staging_id) WHERE (staging_id IS NOT NULL);


--
-- Name: idx_source_pubs_title_normalized_trgm; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_pubs_title_normalized_trgm ON sources.source_publications USING gin (title_normalized public.gin_trgm_ops);


--
-- Name: idx_staging_doi; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_staging_doi ON sources.staging USING btree (doi) WHERE (doi IS NOT NULL);


--
-- Name: idx_staging_processed; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_staging_processed ON sources.staging USING btree (processed) WHERE (NOT processed);


--
-- Name: idx_staging_source; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_staging_source ON sources.staging USING btree (source);


--
-- Name: ix_source_authorship_hal_structures_hal_structure_id; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX ix_source_authorship_hal_structures_hal_structure_id ON sources.source_authorship_hal_structures USING btree (hal_structure_id);


--
-- Name: ix_source_authorship_rors_address_id; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX ix_source_authorship_rors_address_id ON sources.source_authorship_rors USING btree (address_id);


--
-- Name: ix_source_authorship_rors_ror_id; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX ix_source_authorship_rors_ror_id ON sources.source_authorship_rors USING btree (ror_id);


--
-- Name: source_authorship_structures_pkey; Type: INDEX; Schema: sources; Owner: -
--

CREATE UNIQUE INDEX source_authorship_structures_pkey ON sources.source_authorship_structures USING btree (source_authorship_id, structure_id, evidence);


--
-- Name: addresses_raw_text_key; Type: INDEX; Schema: structures; Owner: -
--

CREATE UNIQUE INDEX addresses_raw_text_key ON structures.addresses USING btree (md5(raw_text));


--
-- Name: idx_addr_struct_address; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_addr_struct_address ON structures.address_structures USING btree (address_id);


--
-- Name: idx_addr_struct_filter; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_addr_struct_filter ON structures.address_structures USING btree (structure_id, address_id) INCLUDE (matched_form_id, is_confirmed);


--
-- Name: idx_addr_struct_structure; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_addr_struct_structure ON structures.address_structures USING btree (structure_id);


--
-- Name: idx_addr_sug_countries; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_addr_sug_countries ON structures.addresses USING gin (suggested_countries) WHERE (suggested_countries IS NOT NULL);


--
-- Name: idx_addresses_countries; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_addresses_countries ON structures.addresses USING gin (countries) WHERE (countries IS NOT NULL);


--
-- Name: idx_addresses_countries_dirty; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_addresses_countries_dirty ON structures.addresses USING btree (id) WHERE countries_dirty;


--
-- Name: idx_addresses_normalized_text; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_addresses_normalized_text ON structures.addresses USING hash (normalized_text);


--
-- Name: idx_addresses_normalized_text_trgm; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_addresses_normalized_text_trgm ON structures.addresses USING gin (normalized_text public.gin_trgm_ops);


--
-- Name: idx_ps_structure_id; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_ps_structure_id ON structures.perimeter_structures USING btree (structure_id);


--
-- Name: idx_struct_tut_child; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_struct_tut_child ON structures.structure_tutelles USING btree (child_id);


--
-- Name: idx_struct_tut_parent; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_struct_tut_parent ON structures.structure_tutelles USING btree (parent_id);


--
-- Name: idx_structure_name_forms_structure; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_structure_name_forms_structure ON structures.structure_name_forms USING btree (structure_id);


--
-- Name: idx_structures_type; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_structures_type ON structures.structures USING btree (structure_type);


--
-- Name: source_authorships_orphan_perimeter; Type: STATISTICS; Schema: sources; Owner: -
--

CREATE STATISTICS sources.source_authorships_orphan_perimeter (mcv) ON person_id, in_perimeter FROM sources.source_authorships;
ALTER STATISTICS sources.source_authorships_orphan_perimeter SET STATISTICS 1000;


--
-- Name: person_identifiers trg_protect_authenticated_identifier; Type: TRIGGER; Schema: persons; Owner: -
--

CREATE TRIGGER trg_protect_authenticated_identifier BEFORE INSERT OR UPDATE ON persons.person_identifiers FOR EACH ROW EXECUTE FUNCTION public.protect_authenticated_identifier();


--
-- Name: confirmed_authorships confirmed_authorships_person_id_fkey; Type: FK CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.confirmed_authorships
    ADD CONSTRAINT confirmed_authorships_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons.persons(id) ON DELETE CASCADE;


--
-- Name: confirmed_authorships confirmed_authorships_source_authorship_id_fkey; Type: FK CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.confirmed_authorships
    ADD CONSTRAINT confirmed_authorships_source_authorship_id_fkey FOREIGN KEY (source_authorship_id) REFERENCES sources.source_authorships(id) ON DELETE CASCADE;


--
-- Name: distinct_persons distinct_persons_person_id_a_fkey; Type: FK CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.distinct_persons
    ADD CONSTRAINT distinct_persons_person_id_a_fkey FOREIGN KEY (person_id_a) REFERENCES persons.persons(id) ON DELETE CASCADE;


--
-- Name: distinct_persons distinct_persons_person_id_b_fkey; Type: FK CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.distinct_persons
    ADD CONSTRAINT distinct_persons_person_id_b_fkey FOREIGN KEY (person_id_b) REFERENCES persons.persons(id) ON DELETE CASCADE;


--
-- Name: person_identifiers person_identifiers_person_id_fkey; Type: FK CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.person_identifiers
    ADD CONSTRAINT person_identifiers_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons.persons(id) ON DELETE CASCADE;


--
-- Name: person_name_forms person_name_forms_person_id_fkey; Type: FK CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.person_name_forms
    ADD CONSTRAINT person_name_forms_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons.persons(id) ON DELETE CASCADE;


--
-- Name: persons_rh persons_rh_person_id_fkey; Type: FK CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.persons_rh
    ADD CONSTRAINT persons_rh_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons.persons(id) ON DELETE RESTRICT;


--
-- Name: rejected_authorships rejected_authorships_person_id_fkey; Type: FK CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.rejected_authorships
    ADD CONSTRAINT rejected_authorships_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons.persons(id) ON DELETE CASCADE;


--
-- Name: rejected_authorships rejected_authorships_source_publication_id_fkey; Type: FK CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.rejected_authorships
    ADD CONSTRAINT rejected_authorships_source_publication_id_fkey FOREIGN KEY (source_publication_id) REFERENCES sources.source_publications(id) ON DELETE CASCADE;


--
-- Name: authorships authorships_person_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.authorships
    ADD CONSTRAINT authorships_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons.persons(id) ON DELETE CASCADE;


--
-- Name: authorships authorships_publication_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.authorships
    ADD CONSTRAINT authorships_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES publications.publications(id) ON DELETE CASCADE;


--
-- Name: publication_relations publication_relations_from_publication_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publication_relations
    ADD CONSTRAINT publication_relations_from_publication_id_fkey FOREIGN KEY (from_publication_id) REFERENCES publications.publications(id) ON DELETE CASCADE;


--
-- Name: publication_relations publication_relations_target_publication_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publication_relations
    ADD CONSTRAINT publication_relations_target_publication_id_fkey FOREIGN KEY (target_publication_id) REFERENCES publications.publications(id) ON DELETE CASCADE;


--
-- Name: publication_subjects publication_subjects_publication_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publication_subjects
    ADD CONSTRAINT publication_subjects_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES publications.publications(id) ON DELETE CASCADE;


--
-- Name: publication_subjects publication_subjects_subject_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publication_subjects
    ADD CONSTRAINT publication_subjects_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES publications.subjects(id) ON DELETE CASCADE;


--
-- Name: publications_detail publications_detail_publication_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publications_detail
    ADD CONSTRAINT publications_detail_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES publications.publications(id) ON DELETE CASCADE;


--
-- Name: publications publications_journal_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publications
    ADD CONSTRAINT publications_journal_id_fkey FOREIGN KEY (journal_id) REFERENCES publishing.journals(id);


--
-- Name: publications publications_monograph_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publications
    ADD CONSTRAINT publications_monograph_id_fkey FOREIGN KEY (monograph_id) REFERENCES publishing.monographs(id);


--
-- Name: apc_payments apc_payments_budget_structure_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.apc_payments
    ADD CONSTRAINT apc_payments_budget_structure_id_fkey FOREIGN KEY (budget_structure_id) REFERENCES structures.structures(id) ON DELETE SET NULL;


--
-- Name: apc_payments apc_payments_journal_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.apc_payments
    ADD CONSTRAINT apc_payments_journal_id_fkey FOREIGN KEY (journal_id) REFERENCES publishing.journals(id) ON DELETE SET NULL;


--
-- Name: apc_payments apc_payments_lab_structure_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.apc_payments
    ADD CONSTRAINT apc_payments_lab_structure_id_fkey FOREIGN KEY (lab_structure_id) REFERENCES structures.structures(id) ON DELETE SET NULL;


--
-- Name: apc_payments apc_payments_publication_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.apc_payments
    ADD CONSTRAINT apc_payments_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES publications.publications(id) ON DELETE SET NULL;


--
-- Name: apc_payments apc_payments_publisher_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.apc_payments
    ADD CONSTRAINT apc_payments_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES publishing.publishers(id) ON DELETE SET NULL;


--
-- Name: doi_prefixes doi_prefixes_publisher_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.doi_prefixes
    ADD CONSTRAINT doi_prefixes_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES publishing.publishers(id) ON DELETE SET NULL;


--
-- Name: journal_doi_namespaces journal_doi_namespaces_journal_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.journal_doi_namespaces
    ADD CONSTRAINT journal_doi_namespaces_journal_id_fkey FOREIGN KEY (journal_id) REFERENCES publishing.journals(id) ON DELETE CASCADE;


--
-- Name: journal_issns journal_issns_journal_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.journal_issns
    ADD CONSTRAINT journal_issns_journal_id_fkey FOREIGN KEY (journal_id) REFERENCES publishing.journals(id) ON DELETE SET NULL;


--
-- Name: journal_name_forms journal_name_forms_journal_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.journal_name_forms
    ADD CONSTRAINT journal_name_forms_journal_id_fkey FOREIGN KEY (journal_id) REFERENCES publishing.journals(id) ON DELETE CASCADE;


--
-- Name: journal_name_forms journal_name_forms_publisher_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.journal_name_forms
    ADD CONSTRAINT journal_name_forms_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES publishing.publishers(id);


--
-- Name: journals journals_publisher_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.journals
    ADD CONSTRAINT journals_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES publishing.publishers(id);


--
-- Name: monographs monographs_journal_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.monographs
    ADD CONSTRAINT monographs_journal_id_fkey FOREIGN KEY (journal_id) REFERENCES publishing.journals(id) ON DELETE SET NULL;


--
-- Name: monographs monographs_publisher_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.monographs
    ADD CONSTRAINT monographs_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES publishing.publishers(id) ON DELETE SET NULL;


--
-- Name: publisher_name_forms publisher_name_forms_publisher_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.publisher_name_forms
    ADD CONSTRAINT publisher_name_forms_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES publishing.publishers(id) ON DELETE CASCADE;


--
-- Name: hal_structure_aliases hal_structure_aliases_hal_structure_id_fkey; Type: FK CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.hal_structure_aliases
    ADD CONSTRAINT hal_structure_aliases_hal_structure_id_fkey FOREIGN KEY (hal_structure_id) REFERENCES ref.hal_structures(hal_structure_id) ON DELETE CASCADE;


--
-- Name: hal_structure_relations hal_structure_relations_child_id_fkey; Type: FK CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.hal_structure_relations
    ADD CONSTRAINT hal_structure_relations_child_id_fkey FOREIGN KEY (child_id) REFERENCES ref.hal_structures(hal_structure_id) ON DELETE CASCADE;


--
-- Name: hal_structure_relations hal_structure_relations_parent_id_fkey; Type: FK CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.hal_structure_relations
    ADD CONSTRAINT hal_structure_relations_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES ref.hal_structures(hal_structure_id) ON DELETE CASCADE;


--
-- Name: hal_structures hal_structures_structure_id_fkey; Type: FK CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.hal_structures
    ADD CONSTRAINT hal_structures_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES structures.structures(id) ON DELETE SET NULL;


--
-- Name: language_forms language_forms_language_code_fkey; Type: FK CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.language_forms
    ADD CONSTRAINT language_forms_language_code_fkey FOREIGN KEY (language_code) REFERENCES ref.languages(code) ON DELETE CASCADE;


--
-- Name: ror_relations ror_relations_child_ror_id_fkey; Type: FK CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.ror_relations
    ADD CONSTRAINT ror_relations_child_ror_id_fkey FOREIGN KEY (child_ror_id) REFERENCES ref.ror_organizations(ror_id) ON DELETE CASCADE;


--
-- Name: ror_relations ror_relations_parent_ror_id_fkey; Type: FK CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.ror_relations
    ADD CONSTRAINT ror_relations_parent_ror_id_fkey FOREIGN KEY (parent_ror_id) REFERENCES ref.ror_organizations(ror_id) ON DELETE CASCADE;


--
-- Name: source_authorship_addresses source_authorship_addresses_address_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorship_addresses
    ADD CONSTRAINT source_authorship_addresses_address_id_fkey FOREIGN KEY (address_id) REFERENCES structures.addresses(id) ON DELETE CASCADE;


--
-- Name: source_authorship_addresses source_authorship_addresses_source_authorship_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorship_addresses
    ADD CONSTRAINT source_authorship_addresses_source_authorship_id_fkey FOREIGN KEY (source_authorship_id) REFERENCES sources.source_authorships(id) ON DELETE CASCADE;


--
-- Name: source_authorship_hal_structures source_authorship_hal_structures_source_authorship_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorship_hal_structures
    ADD CONSTRAINT source_authorship_hal_structures_source_authorship_id_fkey FOREIGN KEY (source_authorship_id) REFERENCES sources.source_authorships(id) ON DELETE CASCADE;


--
-- Name: source_authorship_rors source_authorship_rors_address_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorship_rors
    ADD CONSTRAINT source_authorship_rors_address_id_fkey FOREIGN KEY (address_id) REFERENCES structures.addresses(id) ON DELETE CASCADE;


--
-- Name: source_authorship_rors source_authorship_rors_source_authorship_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorship_rors
    ADD CONSTRAINT source_authorship_rors_source_authorship_id_fkey FOREIGN KEY (source_authorship_id) REFERENCES sources.source_authorships(id) ON DELETE CASCADE;


--
-- Name: source_authorships source_authorships_identity_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorships
    ADD CONSTRAINT source_authorships_identity_id_fkey FOREIGN KEY (identity_id) REFERENCES sources.author_identifying_keys(id);


--
-- Name: source_authorships source_authorships_person_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorships
    ADD CONSTRAINT source_authorships_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons.persons(id) ON DELETE SET NULL;


--
-- Name: source_authorships source_authorships_source_publication_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_authorships
    ADD CONSTRAINT source_authorships_source_publication_id_fkey FOREIGN KEY (source_publication_id) REFERENCES sources.source_publications(id) ON DELETE CASCADE;


--
-- Name: source_publications source_publications_journal_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_publications
    ADD CONSTRAINT source_publications_journal_id_fkey FOREIGN KEY (journal_id) REFERENCES publishing.journals(id);


--
-- Name: source_publications source_publications_monograph_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_publications
    ADD CONSTRAINT source_publications_monograph_id_fkey FOREIGN KEY (monograph_id) REFERENCES publishing.monographs(id);


--
-- Name: source_publications source_publications_publication_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_publications
    ADD CONSTRAINT source_publications_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES publications.publications(id) ON DELETE SET NULL;


--
-- Name: source_publications source_publications_staging_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_publications
    ADD CONSTRAINT source_publications_staging_id_fkey FOREIGN KEY (staging_id) REFERENCES sources.staging(id);


--
-- Name: address_structures address_structures_address_id_fkey; Type: FK CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.address_structures
    ADD CONSTRAINT address_structures_address_id_fkey FOREIGN KEY (address_id) REFERENCES structures.addresses(id) ON DELETE CASCADE;


--
-- Name: address_structures address_structures_matched_form_id_fkey; Type: FK CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.address_structures
    ADD CONSTRAINT address_structures_matched_form_id_fkey FOREIGN KEY (matched_form_id) REFERENCES structures.structure_name_forms(id) ON DELETE SET NULL;


--
-- Name: address_structures address_structures_structure_id_fkey; Type: FK CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.address_structures
    ADD CONSTRAINT address_structures_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES structures.structures(id) ON DELETE CASCADE;


--
-- Name: perimeter_structures perimeter_structures_perimeter_id_fkey; Type: FK CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.perimeter_structures
    ADD CONSTRAINT perimeter_structures_perimeter_id_fkey FOREIGN KEY (perimeter_id) REFERENCES structures.perimeters(id) ON DELETE CASCADE;


--
-- Name: perimeter_structures perimeter_structures_structure_id_fkey; Type: FK CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.perimeter_structures
    ADD CONSTRAINT perimeter_structures_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES structures.structures(id) ON DELETE CASCADE;


--
-- Name: structure_name_forms structure_name_forms_structure_id_fkey; Type: FK CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structure_name_forms
    ADD CONSTRAINT structure_name_forms_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES structures.structures(id) ON DELETE CASCADE;


--
-- Name: structure_tutelles structure_tutelles_child_id_fkey; Type: FK CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structure_tutelles
    ADD CONSTRAINT structure_tutelles_child_id_fkey FOREIGN KEY (child_id) REFERENCES structures.structures(id) ON DELETE CASCADE;


--
-- Name: structure_tutelles structure_tutelles_parent_id_fkey; Type: FK CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structure_tutelles
    ADD CONSTRAINT structure_tutelles_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES structures.structures(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict nyWysq9wv77WJm4sNl5wnRR6y9JxN3Z8OVNO2pXNylFUduji3jiznQ0YXf3Koy5

