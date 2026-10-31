--
-- PostgreSQL database dump
--

\restrict S3g5501iNWm1LUqnDvEYQ7zmM9H5ixYWxHjLkBI8qpPECT0JF6fCbJzmwem9jku

-- Dumped from database version 18.4
-- Dumped by pg_dump version 18.4

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
-- Name: queues; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA queues;


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
-- Name: country_detection_method; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.country_detection_method AS ENUM (
    'manual',
    'country_name',
    'source_openalex',
    'institution',
    'city',
    'source_scanr'
);


--
-- Name: date_precision; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.date_precision AS ENUM (
    'year',
    'month',
    'day'
);


--
-- Name: doc_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.doc_type AS ENUM (
    'article',
    'conference_paper',
    'conference',
    'recorded_talk',
    'book',
    'book_chapter',
    'thesis',
    'ongoing_thesis',
    'practice_thesis',
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
    'media',
    'physical_object'
);


--
-- Name: grouping_method; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.grouping_method AS ENUM (
    'reference',
    'name',
    'identifier',
    'order',
    'model'
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
-- Name: issn_link_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.issn_link_type AS ENUM (
    'continued_by',
    'supplement'
);


--
-- Name: issn_status; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.issn_status AS ENUM (
    'active',
    'cancelled',
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
-- Name: lookup_source; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.lookup_source AS ENUM (
    'hal',
    'openalex',
    'wos',
    'scanr',
    'theses',
    'crossref',
    'datacite',
    'doi_org'
);


--
-- Name: merged_entity; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.merged_entity AS ENUM (
    'person',
    'serial',
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
    'diamond'
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
    'hr_record',
    'hal_structure',
    'ror',
    'thesis_institution',
    'thesis_partner'
);


--
-- Name: person_exclusion; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.person_exclusion AS ENUM (
    'not_a_person',
    'out_of_perimeter'
);


--
-- Name: platform_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.platform_type AS ENUM (
    'repository',
    'preprint_server',
    'publisher_platform',
    'unknown'
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
    'manual',
    'orcid',
    'hal_person_id',
    'idref',
    'name',
    'compatible_name'
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
-- Name: serial_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.serial_type AS ENUM (
    'journal',
    'data_journal',
    'proceedings',
    'book_series',
    'media',
    'unknown'
);


--
-- Name: source_identifier_role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.source_identifier_role AS ENUM (
    'primary',
    'derived',
    'secondary',
    'related'
);


--
-- Name: source_identifier_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.source_identifier_type AS ENUM (
    'doi',
    'hal_id',
    'nnt',
    'pmid',
    'pmcid',
    'arxiv_id',
    'isbn',
    'eisbn'
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


--
-- Name: regroup_identifier_publications(text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.regroup_identifier_publications(id_type text, id_value text) RETURNS void
    LANGUAGE sql
    AS $$
                INSERT INTO queues.publication_contributions_queue (id)
                SELECT DISTINCT sr.publication_id
                FROM sources.source_records sr
                JOIN sources.source_contributions sc ON sc.source_record_id = sr.id
                JOIN sources.contributor_information ci ON ci.id = sc.contributor_information_id
                WHERE sr.publication_id IS NOT NULL
                  AND ci.identifiers ? id_type
                  AND ci.identifiers ->> id_type = id_value
                ON CONFLICT (id) DO UPDATE SET seq = DEFAULT
            $$;


--
-- Name: regroup_on_first_name_change(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.regroup_on_first_name_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
                DECLARE
                    ident record;
                BEGIN
                    FOR ident IN
                        SELECT id_type, id_value FROM persons.person_identifiers
                        WHERE person_id = NEW.id AND id_type IN ('orcid', 'idref') AND status IN ('confirmed', 'authenticated')
                    LOOP
                        PERFORM public.regroup_identifier_publications(ident.id_type, ident.id_value);
                    END LOOP;
                    RETURN NULL;
                END;
            $$;


--
-- Name: regroup_on_identifier_decision(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.regroup_on_identifier_decision() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        PERFORM public.regroup_identifier_publications(OLD.id_type, OLD.id_value);
                    ELSE
                        PERFORM public.regroup_identifier_publications(NEW.id_type, NEW.id_value);
                    END IF;
                    RETURN NULL;
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
    entity_type text NOT NULL,
    entity_id integer,
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
-- Name: COLUMN audit_log.entity_type; Type: COMMENT; Schema: ops; Owner: -
--

COMMENT ON COLUMN ops.audit_log.entity_type IS 'Type de l''entité affectée : address, config, perimeter, person, publication, publisher, serial, structure.';


--
-- Name: COLUMN audit_log.entity_id; Type: COMMENT; Schema: ops; Owner: -
--

COMMENT ON COLUMN ops.audit_log.entity_id IS 'ID de l''entité affectée, NULL si l''entité a été supprimée et n''a pas d''équivalent survivant.';


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
    CONSTRAINT config_brand_hue_is_angle CHECK (((key <> 'brand_hue'::text) OR ((jsonb_typeof(value) = 'number'::text) AND (((value)::numeric >= (0)::numeric) AND ((value)::numeric <= (359)::numeric)) AND ((value)::numeric = trunc((value)::numeric))))),
    CONSTRAINT config_cap_is_non_negative_integer CHECK (((key <> ALL (ARRAY['doi_resolution_max_per_run'::text, 'fetch_missing_max_per_source'::text, 'sudoc_max_per_run'::text, 'unpaywall_max_per_run'::text])) OR ((jsonb_typeof(value) = 'number'::text) AND ((value)::numeric >= (0)::numeric) AND ((value)::numeric = trunc((value)::numeric))))),
    CONSTRAINT config_delay_is_positive_integer CHECK (((key <> ALL (ARRAY['doaj_refresh_after_days'::text, 'doi_resolution_recheck_after_days'::text, 'fetch_missing_retry_after_days'::text, 'fetch_stale_after_days'::text, 'unpaywall_recheck_after_days'::text])) OR ((jsonb_typeof(value) = 'number'::text) AND ((value)::numeric >= (1)::numeric) AND ((value)::numeric = trunc((value)::numeric))))),
    CONSTRAINT config_institution_country_is_code CHECK (((key <> 'institution_country'::text) OR ((jsonb_typeof(value) = 'string'::text) AND ((value #>> '{}'::text[]) ~ '^[a-z]{2}$'::text) AND ((value #>> '{}'::text[]) <> 'xx'::text)))),
    CONSTRAINT config_site_title_is_text CHECK (((key <> 'site_title'::text) OR (jsonb_typeof(value) = 'string'::text))),
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
-- Name: roles; Type: TABLE; Schema: ops; Owner: -
--

CREATE TABLE ops.roles (
    code text NOT NULL,
    label text NOT NULL
);


--
-- Name: TABLE roles; Type: COMMENT; Schema: ops; Owner: -
--

COMMENT ON TABLE ops.roles IS 'Rôles que le code connaît (domain.users.Role).';


--
-- Name: user_roles; Type: TABLE; Schema: ops; Owner: -
--

CREATE TABLE ops.user_roles (
    user_id integer NOT NULL,
    role_code text NOT NULL
);


--
-- Name: TABLE user_roles; Type: COMMENT; Schema: ops; Owner: -
--

COMMENT ON TABLE ops.user_roles IS 'Rôles attribués à chaque utilisateur.';


--
-- Name: users; Type: TABLE; Schema: ops; Owner: -
--

CREATE TABLE ops.users (
    id integer NOT NULL,
    login text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE users; Type: COMMENT; Schema: ops; Owner: -
--

COMMENT ON TABLE ops.users IS 'Utilisateurs autorisés à ouvrir une session.';


--
-- Name: COLUMN users.login; Type: COMMENT; Schema: ops; Owner: -
--

COMMENT ON COLUMN ops.users.login IS 'Identifiant de connexion : identifiant CAS, ou ADMIN_USER pour la connexion par mot de passe.';


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: ops; Owner: -
--

ALTER TABLE ops.users ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME ops.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: confirmed_source_contributions; Type: TABLE; Schema: persons; Owner: -
--

CREATE TABLE persons.confirmed_source_contributions (
    source_contribution_id integer NOT NULL,
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
-- Name: hr_records; Type: TABLE; Schema: persons; Owner: -
--

CREATE TABLE persons.hr_records (
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
-- Name: hr_records_id_seq; Type: SEQUENCE; Schema: persons; Owner: -
--

CREATE SEQUENCE persons.hr_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: hr_records_id_seq; Type: SEQUENCE OWNED BY; Schema: persons; Owner: -
--

ALTER SEQUENCE persons.hr_records_id_seq OWNED BY persons.hr_records.id;


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
-- Name: rejected_contributions; Type: TABLE; Schema: persons; Owner: -
--

CREATE TABLE persons.rejected_contributions (
    source_record_id integer NOT NULL,
    person_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
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
-- Name: aligned_source_contributions; Type: TABLE; Schema: publications; Owner: -
--

CREATE TABLE publications.aligned_source_contributions (
    source_contribution_id integer NOT NULL,
    contribution_id integer NOT NULL,
    source_record_id integer NOT NULL,
    method public.grouping_method NOT NULL,
    score real,
    margin real,
    CONSTRAINT aligned_source_contributions_score_check CHECK (((method = 'model'::public.grouping_method) OR ((score IS NULL) AND (margin IS NULL))))
);


--
-- Name: TABLE aligned_source_contributions; Type: COMMENT; Schema: publications; Owner: -
--

COMMENT ON TABLE publications.aligned_source_contributions IS 'Appartenance d''une contribution source à sa contribution. method : origine du lien. score et margin, en bits, pour method = model : poids de Fellegi-Sunter du lien, et écart à la meilleure autre possibilité de l''affectation.';


--
-- Name: contributions; Type: TABLE; Schema: publications; Owner: -
--

CREATE TABLE publications.contributions (
    id integer NOT NULL,
    publication_id integer NOT NULL,
    person_id integer,
    resolution_mode public.resolution_mode,
    reference_position smallint,
    is_corresponding boolean,
    roles text[],
    perimeter_evidence public.perimeter_evidence[] DEFAULT '{}'::public.perimeter_evidence[] NOT NULL,
    in_perimeter boolean GENERATED ALWAYS AS ((cardinality(perimeter_evidence) > 0)) STORED NOT NULL,
    CONSTRAINT contributions_resolution_mode_with_person CHECK (((person_id IS NULL) = (resolution_mode IS NULL)))
)
WITH (fillfactor='90');


--
-- Name: TABLE contributions; Type: COMMENT; Schema: publications; Owner: -
--

COMMENT ON TABLE publications.contributions IS 'Contributions sources d''un même auteur dans une publication, avec au maximum une contribution source par enregistrement source. reference_position : position dans la liste la plus longue. Une personne a au maximum une contribution par publication.';


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
-- Name: source_contribution_addresses; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.source_contribution_addresses (
    id integer NOT NULL,
    source_contribution_id integer NOT NULL,
    address_id integer NOT NULL
);


--
-- Name: source_contribution_hal_structures; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.source_contribution_hal_structures (
    source_contribution_id integer CONSTRAINT source_contribution_hal_structu_source_contribution_id_not_null NOT NULL,
    hal_structure_id integer NOT NULL
);


--
-- Name: source_contribution_rors; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.source_contribution_rors (
    source_contribution_id integer NOT NULL,
    ror_id text NOT NULL,
    address_id integer
);


--
-- Name: TABLE source_contribution_rors; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON TABLE sources.source_contribution_rors IS 'ROR attribués par la source à une contribution source, rattachés à l''adresse de leur affiliation, ou à la seule contribution source quand l''affiliation est sans texte (address_id vide). ror_id est sans clé étrangère vers ror_organizations : une source peut citer un ROR absent du dump importé.';


--
-- Name: source_contributions; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.source_contributions (
    id integer NOT NULL,
    source public.source_type NOT NULL,
    source_record_id integer NOT NULL,
    author_position smallint,
    is_corresponding boolean DEFAULT false,
    roles text[] DEFAULT ARRAY['author'::text],
    raw_author_name text,
    created_at timestamp with time zone DEFAULT now(),
    contributor_information_id integer NOT NULL,
    neutralized_identifiers jsonb,
    content_hash text,
    raw_last_name text,
    raw_first_name text,
    perimeter_evidence public.perimeter_evidence[] DEFAULT '{}'::public.perimeter_evidence[] NOT NULL,
    in_perimeter boolean GENERATED ALWAYS AS ((cardinality(perimeter_evidence) > 0)) STORED NOT NULL,
    countries text[],
    collective boolean DEFAULT false NOT NULL,
    duplicate_of integer,
    CONSTRAINT source_contributions_name_form CHECK (((num_nonnulls(raw_author_name, raw_last_name) = 1) AND ((raw_first_name IS NULL) OR (raw_last_name IS NOT NULL))))
)
WITH (fillfactor='90');
ALTER TABLE ONLY sources.source_contributions ALTER COLUMN source_record_id SET (n_distinct=-0.0134);


--
-- Name: COLUMN source_contributions.neutralized_identifiers; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_contributions.neutralized_identifiers IS 'Identifiants des informations du contributeur que la résolution des personnes ignore pour cette contribution source, avec leur motif : {"orcid": "shared"}.';


--
-- Name: COLUMN source_contributions.content_hash; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_contributions.content_hash IS 'Empreinte des champs écrits par la normalisation, adresses comprises.';


--
-- Name: COLUMN source_contributions.countries; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_contributions.countries IS 'Pays de la contribution source : pays retenus de ses adresses, de ses organisations ROR sans adresse et de ses structures HAL.';


--
-- Name: COLUMN source_contributions.collective; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_contributions.collective IS 'Contribution source collective (collaboration, consortium, groupe d''étude…), posée par la normalisation d''après le signal de la source ou d''après le nom.';


--
-- Name: COLUMN source_contributions.duplicate_of; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_contributions.duplicate_of IS 'Doublon d''auteur : contribution source qui répète, dans la liste d''auteurs de son enregistrement source, la contribution source référencée. Écrite par la phase author_grouping.';


--
-- Name: source_records; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.source_records (
    id integer NOT NULL,
    source public.source_type NOT NULL,
    source_id text NOT NULL,
    title text NOT NULL,
    doc_type public.doc_type,
    publication_id integer,
    staging_id integer,
    created_at timestamp with time zone DEFAULT now(),
    countries text[],
    hal_collections text[],
    urls text[],
    serial_id integer,
    language text,
    container_title text,
    is_retracted boolean,
    abstract text,
    keywords text[],
    topics jsonb,
    biblio jsonb,
    source_extras jsonb,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    corrections jsonb DEFAULT '{}'::jsonb CONSTRAINT source_records_raw_metadata_not_null NOT NULL,
    title_normalized text,
    monograph_id integer,
    authors_hash text,
    impact jsonb,
    license public.license_type,
    author_count integer DEFAULT 0 NOT NULL,
    distinct_author_count integer DEFAULT 0 NOT NULL,
    raw_doc_type text,
    raw_language text,
    publisher_id integer,
    is_matchable boolean DEFAULT true NOT NULL,
    publication_date date,
    publication_date_precision public.date_precision,
    publication_year smallint GENERATED ALWAYS AS ((EXTRACT(year FROM publication_date))::smallint) STORED,
    CONSTRAINT source_records_corrections_is_object CHECK ((jsonb_typeof(corrections) = 'object'::text)),
    CONSTRAINT source_records_impact_is_object CHECK (((impact IS NULL) OR (jsonb_typeof(impact) = 'object'::text)))
);


--
-- Name: COLUMN source_records.authors_hash; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_records.authors_hash IS 'Empreinte de la partie auteurs du payload source, à la dernière synchronisation des contributions sources.';


--
-- Name: COLUMN source_records.author_count; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_records.author_count IS 'Contributions sources de l''enregistrement source qui ont le rôle author et ne sont pas collectives, telles que la source les donne.';


--
-- Name: COLUMN source_records.distinct_author_count; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_records.distinct_author_count IS 'Noms complets normalisés distincts parmi les contributions sources comptées par author_count.';


--
-- Name: COLUMN source_records.raw_doc_type; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_records.raw_doc_type IS 'Type de document donné par la source, dans son vocabulaire.';


--
-- Name: COLUMN source_records.raw_language; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_records.raw_language IS 'Langue donnée par la source, dans son vocabulaire.';


--
-- Name: COLUMN source_records.publisher_id; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_records.publisher_id IS 'Éditeur que nomme la source. Nul pour une production hébergée sans être publiée.';


--
-- Name: COLUMN source_records.is_matchable; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_records.is_matchable IS 'Faux pour un enregistrement source écarté de la réconciliation : préfixe DOI exclu, titre de paratexte, enregistrement ScanR issu d''un dépôt HAL introuvable, enregistrement d''agrégateur sans DOI, lien ni clé de confirmation.';


--
-- Name: COLUMN source_records.publication_date; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_records.publication_date IS 'Date de publication. À l''année : 1er janvier ; au mois : 1er du mois.';


--
-- Name: COLUMN source_records.publication_date_precision; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_records.publication_date_precision IS 'Précision de publication_date : year, month ou day.';


--
-- Name: COLUMN source_records.publication_year; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_records.publication_year IS 'Année de publication_date.';


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
-- Name: idref_structures; Type: TABLE; Schema: structures; Owner: -
--

CREATE TABLE structures.idref_structures (
    idref_ppn text NOT NULL,
    structure_id integer NOT NULL,
    matched_form_id integer,
    is_confirmed boolean
);


--
-- Name: TABLE idref_structures; Type: COMMENT; Schema: structures; Owner: -
--

COMMENT ON TABLE structures.idref_structures IS 'Structure interne d''un PPN IdRef de laboratoire partenaire de thèse : détectée par une forme de nom (matched_form_id), confirmée ou infirmée par l''administration (is_confirmed).';


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
-- Name: source_contribution_structures; Type: MATERIALIZED VIEW; Schema: sources; Owner: -
--

CREATE MATERIALIZED VIEW sources.source_contribution_structures AS
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
         SELECT DISTINCT sah.source_contribution_id,
            COALESCE(al.hal_structure_id, sah.hal_structure_id) AS hal_structure_id
           FROM (sources.source_contribution_hal_structures sah
             LEFT JOIN ref.hal_structure_aliases al ON ((al.alias_id = sah.hal_structure_id)))
        ), hal_lowest AS (
         SELECT hal_direct.source_contribution_id,
            hal_direct.hal_structure_id
           FROM hal_direct
        EXCEPT
         SELECT d.source_contribution_id,
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
 SELECT saa.source_contribution_id,
    ast.structure_id,
    'address'::public.perimeter_evidence AS evidence
   FROM (sources.source_contribution_addresses saa
     JOIN structures.address_structures ast ON ((ast.address_id = saa.address_id)))
  WHERE ((ast.is_confirmed IS DISTINCT FROM false) AND (ast.structure_id IN ( SELECT perimeter.structure_id
           FROM perimeter)))
UNION
 SELECT sar.source_contribution_id,
    s.id AS structure_id,
    'ror'::public.perimeter_evidence AS evidence
   FROM (sources.source_contribution_rors sar
     JOIN structures.structures s ON ((s.ror_id = sar.ror_id)))
  WHERE ((s.id IN ( SELECT perimeter.structure_id
           FROM perimeter)) AND (sar.address_id IS NULL))
UNION
 SELECT l.source_contribution_id,
    r.structure_id,
    'hal_structure'::public.perimeter_evidence AS evidence
   FROM (hal_lowest l
     JOIN hal_reach r ON ((r.origin_id = l.hal_structure_id)))
UNION
 SELECT sa.id AS source_contribution_id,
    s.id AS structure_id,
    'thesis_institution'::public.perimeter_evidence AS evidence
   FROM ((sources.source_records sp
     JOIN sources.source_contributions sa ON ((sa.source_record_id = sp.id)))
     JOIN structures.structures s ON (((s.api_ids -> 'theses'::text) ? (sp.source_extras ->> 'etablissement_ppn'::text))))
  WHERE ((sp.source = 'theses'::public.source_type) AND (s.id IN ( SELECT perimeter.structure_id
           FROM perimeter)))
UNION
 SELECT sa.id AS source_contribution_id,
    ist.structure_id,
    'thesis_partner'::public.perimeter_evidence AS evidence
   FROM (((sources.source_records sp
     CROSS JOIN LATERAL jsonb_array_elements((sp.source_extras -> 'partenaires'::text)) partner(value))
     JOIN structures.idref_structures ist ON ((ist.idref_ppn = (partner.value ->> 'ppn'::text))))
     JOIN sources.source_contributions sa ON (((sa.source_record_id = sp.id) AND (sa.roles && ARRAY['author'::text]))))
  WHERE ((sp.source = 'theses'::public.source_type) AND (ist.is_confirmed IS DISTINCT FROM false) AND ((ist.matched_form_id IS NOT NULL) OR ist.is_confirmed) AND (ist.structure_id IN ( SELECT perimeter.structure_id
           FROM perimeter)))
  WITH NO DATA;


--
-- Name: contribution_structures; Type: MATERIALIZED VIEW; Schema: publications; Owner: -
--

CREATE MATERIALIZED VIEW publications.contribution_structures AS
 SELECT DISTINCT m.contribution_id,
    scs.structure_id
   FROM (((sources.source_contribution_structures scs
     JOIN publications.aligned_source_contributions m ON ((m.source_contribution_id = scs.source_contribution_id)))
     JOIN publications.contributions g ON ((g.id = m.contribution_id)))
     JOIN persons.persons pe ON ((pe.id = g.person_id)))
  WHERE (pe.exclusion IS NULL)
  WITH NO DATA;


--
-- Name: contributions_id_seq; Type: SEQUENCE; Schema: publications; Owner: -
--

CREATE SEQUENCE publications.contributions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: contributions_id_seq; Type: SEQUENCE OWNED BY; Schema: publications; Owner: -
--

ALTER SEQUENCE publications.contributions_id_seq OWNED BY publications.contributions.id;


--
-- Name: manual_merge_source_records; Type: TABLE; Schema: publications; Owner: -
--

CREATE TABLE publications.manual_merge_source_records (
    manual_merge_id integer NOT NULL,
    source public.source_type NOT NULL,
    source_id text NOT NULL
);


--
-- Name: TABLE manual_merge_source_records; Type: COMMENT; Schema: publications; Owner: -
--

COMMENT ON TABLE publications.manual_merge_source_records IS 'Enregistrements sources d''une fusion manuelle, par clé naturelle. La réconciliation les réunit dans une même publication.';


--
-- Name: manual_merges; Type: TABLE; Schema: publications; Owner: -
--

CREATE TABLE publications.manual_merges (
    id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE manual_merges; Type: COMMENT; Schema: publications; Owner: -
--

COMMENT ON TABLE publications.manual_merges IS 'Fusions de publications décidées par l''administration.';


--
-- Name: manual_merges_id_seq; Type: SEQUENCE; Schema: publications; Owner: -
--

CREATE SEQUENCE publications.manual_merges_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: manual_merges_id_seq; Type: SEQUENCE OWNED BY; Schema: publications; Owner: -
--

ALTER SEQUENCE publications.manual_merges_id_seq OWNED BY publications.manual_merges.id;


--
-- Name: publication_author_alignment; Type: MATERIALIZED VIEW; Schema: publications; Owner: -
--

CREATE MATERIALIZED VIEW publications.publication_author_alignment AS
 WITH author_members AS (
         SELECT g.publication_id,
            gs.contribution_id AS group_id,
            gs.source_record_id AS source_publication_id,
            count(*) OVER (PARTITION BY gs.contribution_id) AS group_size
           FROM ((publications.aligned_source_contributions gs
             JOIN publications.contributions g ON ((g.id = gs.contribution_id)))
             JOIN sources.source_contributions sa ON ((sa.id = gs.source_contribution_id)))
          WHERE ((sa.roles IS NULL) OR ('author'::text = ANY (sa.roles)))
        )
 SELECT publication_id,
    count(DISTINCT source_publication_id) AS source_records,
    count(*) AS source_contributions,
    count(*) FILTER (WHERE (group_size >= 2)) AS matched_source_contributions
   FROM author_members
  GROUP BY publication_id
 HAVING (count(DISTINCT source_publication_id) >= 2)
  WITH NO DATA;


--
-- Name: MATERIALIZED VIEW publication_author_alignment; Type: COMMENT; Schema: publications; Owner: -
--

COMMENT ON MATERIALIZED VIEW publications.publication_author_alignment IS 'Recouvrement des listes d''auteurs des publications à plusieurs enregistrements sources. matched_source_contributions : contributions sources qui ont un correspondant dans un autre enregistrement source.';


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
 SELECT DISTINCT g.publication_id,
    gs.structure_id
   FROM (publications.contributions g
     JOIN publications.contribution_structures gs ON ((gs.contribution_id = g.id)))
  WHERE (g.roles && ARRAY['author'::text])
  WITH NO DATA;


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
-- Name: publication_rors; Type: MATERIALIZED VIEW; Schema: publications; Owner: -
--

CREATE MATERIALIZED VIEW publications.publication_rors AS
 WITH RECURSIVE cited AS (
         SELECT c.publication_id,
            r.ror_id
           FROM (((publications.contributions c
             JOIN publications.aligned_source_contributions m ON ((m.contribution_id = c.id)))
             JOIN sources.source_contribution_rors r ON ((r.source_contribution_id = m.source_contribution_id)))
             LEFT JOIN persons.persons pe ON ((pe.id = c.person_id)))
          WHERE ((c.roles && ARRAY['author'::text]) AND (pe.exclusion IS DISTINCT FROM 'not_a_person'::public.person_exclusion))
        UNION
         SELECT ps.publication_id,
            s.ror_id
           FROM (publications.publication_structures ps
             JOIN structures.structures s ON ((s.id = ps.structure_id)))
          WHERE (s.ror_id IS NOT NULL)
        ), lineage AS (
         SELECT cited.publication_id,
            cited.ror_id,
            true AS cited
           FROM cited
        UNION
         SELECT l.publication_id,
            rr.parent_ror_id,
            false
           FROM (lineage l
             JOIN ref.ror_relations rr ON ((rr.child_ror_id = l.ror_id)))
        )
 SELECT publication_id,
    ror_id,
    bool_or(cited) AS cited
   FROM lineage
  GROUP BY publication_id, ror_id
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
    doi text,
    oa_status public.oa_type DEFAULT 'unknown'::public.oa_type,
    serial_id integer,
    container_title text,
    language text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    countries text[],
    sources public.source_type[] DEFAULT '{}'::public.source_type[] NOT NULL,
    source_extras jsonb,
    is_retracted boolean DEFAULT false NOT NULL,
    subjects_ingested_at timestamp with time zone,
    monograph_id integer,
    license public.license_type,
    deposit_license public.license_type,
    perimeter_evidence public.perimeter_evidence[] DEFAULT '{}'::public.perimeter_evidence[] NOT NULL,
    in_perimeter boolean GENERATED ALWAYS AS ((cardinality(perimeter_evidence) > 0)) STORED NOT NULL,
    corrections jsonb DEFAULT '{}'::jsonb NOT NULL,
    publisher_id integer,
    doi_prefix text GENERATED ALWAYS AS (split_part(doi, '/'::text, 1)) STORED,
    best_copy_url text,
    publication_date date NOT NULL,
    publication_date_precision public.date_precision NOT NULL,
    publication_year smallint GENERATED ALWAYS AS ((EXTRACT(year FROM publication_date))::smallint) STORED,
    CONSTRAINT publications_corrections_is_object CHECK ((jsonb_typeof(corrections) = 'object'::text))
);


--
-- Name: COLUMN publications.publisher_id; Type: COMMENT; Schema: publications; Owner: -
--

COMMENT ON COLUMN publications.publications.publisher_id IS 'Éditeur à la date de publication : titulaire du préfixe du DOI Crossref, à défaut éditeur des enregistrements sources.';


--
-- Name: COLUMN publications.doi_prefix; Type: COMMENT; Schema: publications; Owner: -
--

COMMENT ON COLUMN publications.publications.doi_prefix IS 'Préfixe du DOI, pour les jointures sur doi_prefixes.';


--
-- Name: COLUMN publications.best_copy_url; Type: COMMENT; Schema: publications; Owner: -
--

COMMENT ON COLUMN publications.publications.best_copy_url IS 'Adresse de la meilleure copie ouverte, parmi les localisations des enregistrements sources.';


--
-- Name: COLUMN publications.publication_date; Type: COMMENT; Schema: publications; Owner: -
--

COMMENT ON COLUMN publications.publications.publication_date IS 'Date de publication. À l''année : 1er janvier ; au mois : 1er du mois.';


--
-- Name: COLUMN publications.publication_date_precision; Type: COMMENT; Schema: publications; Owner: -
--

COMMENT ON COLUMN publications.publications.publication_date_precision IS 'Précision de publication_date : year, month ou day.';


--
-- Name: COLUMN publications.publication_year; Type: COMMENT; Schema: publications; Owner: -
--

COMMENT ON COLUMN publications.publications.publication_year IS 'Année de publication_date.';


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
    usage_count integer DEFAULT 0 NOT NULL,
    label_normalized text NOT NULL
);


--
-- Name: COLUMN subjects.label_normalized; Type: COMMENT; Schema: publications; Owner: -
--

COMMENT ON COLUMN publications.subjects.label_normalized IS 'Forme de recherche du libellé (normalize_text), servie par un index trigram.';


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
    publication_year smallint,
    budget text,
    institution text,
    coman_id integer,
    source_file text,
    remarks text,
    publication_id integer,
    serial_id integer,
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
-- Name: issn_links; Type: TABLE; Schema: publishing; Owner: -
--

CREATE TABLE publishing.issn_links (
    issn text NOT NULL,
    linked_issn text NOT NULL,
    link_type public.issn_link_type NOT NULL
);


--
-- Name: TABLE issn_links; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON TABLE publishing.issn_links IS 'Liens entre ISSN lus dans le Sudoc, une ligne par lien : continued_by, titre précédent vers titre suivant ; supplement, revue principale vers supplément.';


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
    serial_id integer,
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
-- Name: COLUMN monographs.serial_id; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.monographs.serial_id IS 'Collection dont la monographie fait partie, quand cette collection porte un ISSN.';


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
-- Name: platforms; Type: TABLE; Schema: publishing; Owner: -
--

CREATE TABLE publishing.platforms (
    id integer NOT NULL,
    name text NOT NULL,
    name_normalized text NOT NULL,
    platform_type public.platform_type DEFAULT 'unknown'::public.platform_type NOT NULL,
    openalex_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE platforms; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON TABLE publishing.platforms IS 'Lieux qui hébergent des publications : entrepôts, serveurs de preprints, plateformes d''éditeurs.';


--
-- Name: COLUMN platforms.openalex_id; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.platforms.openalex_id IS 'Source OpenAlex de la plateforme, dont elle prend le nom.';


--
-- Name: platforms_id_seq; Type: SEQUENCE; Schema: publishing; Owner: -
--

CREATE SEQUENCE publishing.platforms_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: platforms_id_seq; Type: SEQUENCE OWNED BY; Schema: publishing; Owner: -
--

ALTER SEQUENCE publishing.platforms_id_seq OWNED BY publishing.platforms.id;


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
    publication_count integer DEFAULT 0 NOT NULL
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
-- Name: serial_doi_namespaces; Type: TABLE; Schema: publishing; Owner: -
--

CREATE TABLE publishing.serial_doi_namespaces (
    namespace text NOT NULL,
    serial_id integer NOT NULL,
    dois integer NOT NULL,
    share double precision NOT NULL
);


--
-- Name: serial_issns; Type: TABLE; Schema: publishing; Owner: -
--

CREATE TABLE publishing.serial_issns (
    id integer NOT NULL,
    issn text NOT NULL,
    serial_id integer,
    support public.issn_support,
    status public.issn_status DEFAULT 'active'::public.issn_status NOT NULL,
    sudoc_checked_at timestamp with time zone,
    issnl text,
    sudoc_title text
);


--
-- Name: TABLE serial_issns; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON TABLE publishing.serial_issns IS 'ISSN valides, une ligne par ISSN, et revue de leur ISSN-L.';


--
-- Name: COLUMN serial_issns.issn; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.serial_issns.issn IS 'ISSN, forme normalisée.';


--
-- Name: COLUMN serial_issns.serial_id; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.serial_issns.serial_id IS 'Revue de l''ISSN-L de l''ISSN, calculée par la phase publishing.';


--
-- Name: COLUMN serial_issns.support; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.serial_issns.support IS 'Support de l''ISSN. NULL : inconnu.';


--
-- Name: COLUMN serial_issns.status; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.serial_issns.status IS 'active ; cancelled (ISSN annulé) ; unverified (sans notice Sudoc).';


--
-- Name: COLUMN serial_issns.sudoc_checked_at; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.serial_issns.sudoc_checked_at IS 'Date de la vérification de l''ISSN au Sudoc. NULL : jamais vérifié.';


--
-- Name: COLUMN serial_issns.issnl; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.serial_issns.issnl IS 'ISSN-L de l''ISSN d''après sa notice Sudoc. NULL : inconnu.';


--
-- Name: COLUMN serial_issns.sudoc_title; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON COLUMN publishing.serial_issns.sudoc_title IS 'Titre de la notice Sudoc de l''ISSN. NULL : sans notice, ou ISSN jamais vérifié.';


--
-- Name: serial_issns_id_seq; Type: SEQUENCE; Schema: publishing; Owner: -
--

CREATE SEQUENCE publishing.serial_issns_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: serial_issns_id_seq; Type: SEQUENCE OWNED BY; Schema: publishing; Owner: -
--

ALTER SEQUENCE publishing.serial_issns_id_seq OWNED BY publishing.serial_issns.id;


--
-- Name: serial_title_decisions; Type: TABLE; Schema: publishing; Owner: -
--

CREATE TABLE publishing.serial_title_decisions (
    id integer NOT NULL,
    title_normalized text NOT NULL,
    serial_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE serial_title_decisions; Type: COMMENT; Schema: publishing; Owner: -
--

COMMENT ON TABLE publishing.serial_title_decisions IS 'Fusions décidées par l''administration : une série sans ISSN de ce titre normalisé est rattachée à la revue.';


--
-- Name: serial_title_decisions_id_seq; Type: SEQUENCE; Schema: publishing; Owner: -
--

CREATE SEQUENCE publishing.serial_title_decisions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: serial_title_decisions_id_seq; Type: SEQUENCE OWNED BY; Schema: publishing; Owner: -
--

ALTER SEQUENCE publishing.serial_title_decisions_id_seq OWNED BY publishing.serial_title_decisions.id;


--
-- Name: serials; Type: TABLE; Schema: publishing; Owner: -
--

CREATE TABLE publishing.serials (
    id integer NOT NULL,
    title text NOT NULL,
    title_normalized text NOT NULL,
    publisher_id integer,
    openalex_id text,
    is_in_doaj boolean DEFAULT false,
    oa_model public.oa_model,
    created_at timestamp with time zone DEFAULT now(),
    serial_type public.serial_type DEFAULT 'unknown'::public.serial_type,
    is_academic boolean DEFAULT true,
    doaj_payload jsonb,
    doaj_imported_at timestamp with time zone,
    publication_count integer DEFAULT 0 NOT NULL,
    manual_fields text[] DEFAULT '{}'::text[] NOT NULL
);


--
-- Name: serials_id_seq; Type: SEQUENCE; Schema: publishing; Owner: -
--

CREATE SEQUENCE publishing.serials_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: serials_id_seq; Type: SEQUENCE OWNED BY; Schema: publishing; Owner: -
--

ALTER SEQUENCE publishing.serials_id_seq OWNED BY publishing.serials.id;


--
-- Name: address_candidates_queue; Type: TABLE; Schema: queues; Owner: -
--

CREATE TABLE queues.address_candidates_queue (
    id integer NOT NULL,
    seq bigint NOT NULL
);


--
-- Name: address_candidates_queue_seq_seq; Type: SEQUENCE; Schema: queues; Owner: -
--

ALTER TABLE queues.address_candidates_queue ALTER COLUMN seq ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME queues.address_candidates_queue_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: address_countries_queue; Type: TABLE; Schema: queues; Owner: -
--

CREATE TABLE queues.address_countries_queue (
    id integer NOT NULL,
    seq bigint NOT NULL
);


--
-- Name: address_countries_queue_seq_seq; Type: SEQUENCE; Schema: queues; Owner: -
--

ALTER TABLE queues.address_countries_queue ALTER COLUMN seq ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME queues.address_countries_queue_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: contribution_attributes_queue; Type: TABLE; Schema: queues; Owner: -
--

CREATE TABLE queues.contribution_attributes_queue (
    id integer NOT NULL,
    seq bigint NOT NULL
);


--
-- Name: contribution_attributes_queue_seq_seq; Type: SEQUENCE; Schema: queues; Owner: -
--

ALTER TABLE queues.contribution_attributes_queue ALTER COLUMN seq ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME queues.contribution_attributes_queue_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: contribution_resolution_queue; Type: TABLE; Schema: queues; Owner: -
--

CREATE TABLE queues.contribution_resolution_queue (
    id integer NOT NULL,
    seq bigint NOT NULL
);


--
-- Name: contribution_resolution_queue_seq_seq; Type: SEQUENCE; Schema: queues; Owner: -
--

ALTER TABLE queues.contribution_resolution_queue ALTER COLUMN seq ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME queues.contribution_resolution_queue_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: publication_contributions_queue; Type: TABLE; Schema: queues; Owner: -
--

CREATE TABLE queues.publication_contributions_queue (
    id integer NOT NULL,
    seq bigint NOT NULL
);


--
-- Name: publication_contributions_queue_seq_seq; Type: SEQUENCE; Schema: queues; Owner: -
--

ALTER TABLE queues.publication_contributions_queue ALTER COLUMN seq ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME queues.publication_contributions_queue_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: source_contribution_countries_queue; Type: TABLE; Schema: queues; Owner: -
--

CREATE TABLE queues.source_contribution_countries_queue (
    id integer NOT NULL,
    seq bigint NOT NULL
);


--
-- Name: source_contribution_countries_queue_seq_seq; Type: SEQUENCE; Schema: queues; Owner: -
--

ALTER TABLE queues.source_contribution_countries_queue ALTER COLUMN seq ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME queues.source_contribution_countries_queue_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: source_record_keys_queue; Type: TABLE; Schema: queues; Owner: -
--

CREATE TABLE queues.source_record_keys_queue (
    id integer NOT NULL,
    seq bigint NOT NULL
);


--
-- Name: source_record_keys_queue_seq_seq; Type: SEQUENCE; Schema: queues; Owner: -
--

ALTER TABLE queues.source_record_keys_queue ALTER COLUMN seq ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME queues.source_record_keys_queue_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


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
    iso_code character(2) CONSTRAINT country_name_forms_iso_code_not_null NOT NULL,
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
-- Name: source_record_identifiers; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.source_record_identifiers (
    source_record_id integer NOT NULL,
    id_type public.source_identifier_type NOT NULL,
    id_value text NOT NULL,
    role public.source_identifier_role NOT NULL,
    removed_by text
);


--
-- Name: TABLE source_record_identifiers; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON TABLE sources.source_record_identifiers IS 'Identifiants d''un enregistrement source, réécrits à chaque normalisation.';


--
-- Name: COLUMN source_record_identifiers.id_value; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_record_identifiers.id_value IS 'Forme normalisée de l''identifiant.';


--
-- Name: COLUMN source_record_identifiers.role; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_record_identifiers.role IS 'primary : identifiant de l''enregistrement dans la source. derived : identifiant de l''enregistrement d''une autre source dont l''enregistrement source est dérivé. Un enregistrement source a au plus un identifiant dérivé. secondary : identifiant que la source attribue au même document. related : identifiant d''un document lié.';


--
-- Name: COLUMN source_record_identifiers.removed_by; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_record_identifiers.removed_by IS 'Règle de correction qui retire l''identifiant. NULL : identifiant actif.';


--
-- Name: known_dois; Type: VIEW; Schema: sources; Owner: -
--

CREATE VIEW sources.known_dois AS
 SELECT i.id_value AS doi,
    sp.source,
    sp.publication_id
   FROM (sources.source_records sp
     JOIN sources.source_record_identifiers i ON ((i.source_record_id = sp.id)))
  WHERE ((i.id_type = 'doi'::public.source_identifier_type) AND (i.removed_by IS NULL))
UNION
 SELECT pr.target_doi AS doi,
    NULL::public.source_type AS source,
    pr.from_publication_id AS publication_id
   FROM publications.publication_relations pr
  WHERE (pr.target_doi IS NOT NULL)
UNION
 SELECT ('10.48550/arxiv.'::text || lower(i.id_value)) AS doi,
    sp.source,
    sp.publication_id
   FROM (sources.source_records sp
     JOIN sources.source_record_identifiers i ON ((i.source_record_id = sp.id)))
  WHERE ((i.id_type = 'arxiv_id'::public.source_identifier_type) AND (i.removed_by IS NULL) AND (NOT (EXISTS ( SELECT 1
           FROM sources.source_record_identifiers x
          WHERE ((x.source_record_id = i.source_record_id) AND (x.id_type = i.id_type) AND (x.removed_by IS NULL) AND (ROW(
                CASE x.role
                    WHEN 'primary'::public.source_identifier_role THEN 1
                    WHEN 'derived'::public.source_identifier_role THEN 2
                    WHEN 'secondary'::public.source_identifier_role THEN 3
                    WHEN 'related'::public.source_identifier_role THEN 4
                    ELSE NULL::integer
                END, (x.id_value COLLATE "C")) < ROW(
                CASE i.role
                    WHEN 'primary'::public.source_identifier_role THEN 1
                    WHEN 'derived'::public.source_identifier_role THEN 2
                    WHEN 'secondary'::public.source_identifier_role THEN 3
                    WHEN 'related'::public.source_identifier_role THEN 4
                    ELSE NULL::integer
                END, (i.id_value COLLATE "C"))))))));


--
-- Name: VIEW known_dois; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON VIEW sources.known_dois IS 'Tous les DOI connus : DOI actifs des enregistrements sources, cibles des relations, DOI DataCite déduits des identifiants arXiv. publication_id est la publication de l''enregistrement source, ou la publication d''origine de la relation ; NULL pour un enregistrement source orphelin.';


--
-- Name: candidate_dois; Type: VIEW; Schema: sources; Owner: -
--

CREATE VIEW sources.candidate_dois AS
 SELECT DISTINCT k.doi,
    k.source,
    k.publication_id
   FROM (sources.known_dois k
     JOIN publications.publications p ON ((p.id = k.publication_id)))
  WHERE p.in_perimeter;


--
-- Name: contributor_information; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.contributor_information (
    id integer NOT NULL,
    identifiers jsonb,
    last_name_normalized text NOT NULL,
    first_name_normalized text,
    author_name_normalized text GENERATED ALWAYS AS (
CASE
    WHEN (COALESCE(first_name_normalized, ''::text) = ''::text) THEN last_name_normalized
    WHEN (last_name_normalized = ''::text) THEN first_name_normalized
    ELSE ((first_name_normalized || ' '::text) || last_name_normalized)
END) STORED,
    key_hash text GENERATED ALWAYS AS (md5(((((COALESCE(last_name_normalized, ''::text) || ''::text) || COALESCE(first_name_normalized, ''::text)) || ''::text) || COALESCE((identifiers)::text, ''::text)))) STORED
);


--
-- Name: contributor_information_id_seq; Type: SEQUENCE; Schema: sources; Owner: -
--

CREATE SEQUENCE sources.contributor_information_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: contributor_information_id_seq; Type: SEQUENCE OWNED BY; Schema: sources; Owner: -
--

ALTER SEQUENCE sources.contributor_information_id_seq OWNED BY sources.contributor_information.id;


--
-- Name: doi_targets; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.doi_targets (
    doi text NOT NULL,
    target_doi text NOT NULL,
    rule text NOT NULL
);


--
-- Name: TABLE doi_targets; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON TABLE sources.doi_targets IS 'Cible du DOI d''une forme secondaire, réécrite par la correction par DOI partagé. La cible tient lieu du DOI pour la réconciliation et la consolidation.';


--
-- Name: COLUMN doi_targets.doi; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.doi_targets.doi IS 'DOI d''une version, d''une variante ou d''une pièce de dataset.';


--
-- Name: COLUMN doi_targets.target_doi; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.doi_targets.target_doi IS 'DOI de l''œuvre principale, présent en base.';


--
-- Name: COLUMN doi_targets.rule; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.doi_targets.rule IS 'Règle de correction qui relie les deux DOI.';


--
-- Name: dois; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.dois (
    doi text NOT NULL,
    unpaywall_oa_status public.oa_type,
    unpaywall_checked_at timestamp with time zone,
    registered_url text,
    resolved_at timestamp with time zone,
    CONSTRAINT dois_registered_url_dated CHECK (((registered_url IS NULL) OR (resolved_at IS NOT NULL))),
    CONSTRAINT dois_unpaywall_dated CHECK (((unpaywall_oa_status IS NULL) OR (unpaywall_checked_at IS NOT NULL)))
);


--
-- Name: TABLE dois; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON TABLE sources.dois IS 'Réponses des services externes sur chaque DOI de publication : verdict d''Unpaywall, URL de résolution chez doi.org.';


--
-- Name: COLUMN dois.unpaywall_oa_status; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.dois.unpaywall_oa_status IS 'Statut open access donné par Unpaywall. NULL avec une date : DOI absent d''Unpaywall.';


--
-- Name: COLUMN dois.unpaywall_checked_at; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.dois.unpaywall_checked_at IS 'Date du verdict d''Unpaywall. Le DOI est réinterrogé au-delà du délai unpaywall_recheck_after_days.';


--
-- Name: COLUMN dois.registered_url; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.dois.registered_url IS 'URL de résolution du DOI, lue dans l''API des handles de doi.org. NULL avec une date : DOI inconnu de doi.org.';


--
-- Name: COLUMN dois.resolved_at; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.dois.resolved_at IS 'Date de la lecture chez doi.org.';


--
-- Name: embargoes; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.embargoes (
    source_record_id integer NOT NULL,
    until date
);


--
-- Name: TABLE embargoes; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON TABLE sources.embargoes IS 'Embargo déclaré par un enregistrement source : fichier déposé dans HAL, thèse de theses.fr.';


--
-- Name: COLUMN embargoes.until; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.embargoes.until IS 'Date de fin d''embargo. Nulle quand la source déclare un embargo sans date.';


--
-- Name: failed_lookups; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.failed_lookups (
    source public.lookup_source NOT NULL,
    id_type text NOT NULL,
    id_value text NOT NULL,
    not_found_at timestamp with time zone NOT NULL,
    CONSTRAINT failed_lookups_id_type_check CHECK ((id_type = ANY (ARRAY['doi'::text, 'hal_id'::text, 'nnt'::text])))
);


--
-- Name: TABLE failed_lookups; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON TABLE sources.failed_lookups IS 'Identifiants cherchés en vain par la phase fetch_missing, dans une source ou auprès de doi.org (source doi_org : DOI que doi.org ne connaît pas). L''échec est définitif pour un identifiant absent de son registre (hal-id dans HAL, NNT dans theses.fr, DOI auprès de doi.org). Les autres recherches reprennent quand not_found_at date de plus que le délai fetch_missing_retry_after_days.';


--
-- Name: source_contribution_addresses_id_seq; Type: SEQUENCE; Schema: sources; Owner: -
--

CREATE SEQUENCE sources.source_contribution_addresses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_contribution_addresses_id_seq; Type: SEQUENCE OWNED BY; Schema: sources; Owner: -
--

ALTER SEQUENCE sources.source_contribution_addresses_id_seq OWNED BY sources.source_contribution_addresses.id;


--
-- Name: source_contributions_id_seq; Type: SEQUENCE; Schema: sources; Owner: -
--

CREATE SEQUENCE sources.source_contributions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_contributions_id_seq; Type: SEQUENCE OWNED BY; Schema: sources; Owner: -
--

ALTER SEQUENCE sources.source_contributions_id_seq OWNED BY sources.source_contributions.id;


--
-- Name: source_record_locations; Type: TABLE; Schema: sources; Owner: -
--

CREATE TABLE sources.source_record_locations (
    source_record_id integer NOT NULL,
    url text NOT NULL,
    pdf_url text,
    oai_id text,
    version text,
    license public.license_type,
    is_oa boolean,
    platform_id integer
);


--
-- Name: TABLE source_record_locations; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON TABLE sources.source_record_locations IS 'Localisations d''un enregistrement source, réécrites à chaque normalisation.';


--
-- Name: COLUMN source_record_locations.oai_id; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_record_locations.oai_id IS 'Identifiant OAI-PMH de la copie, que déclare l''entrepôt.';


--
-- Name: COLUMN source_record_locations.version; Type: COMMENT; Schema: sources; Owner: -
--

COMMENT ON COLUMN sources.source_record_locations.version IS 'Version de la copie dans le vocabulaire de la source (submittedVersion, acceptedVersion, publishedVersion).';


--
-- Name: source_records_id_seq; Type: SEQUENCE; Schema: sources; Owner: -
--

CREATE SEQUENCE sources.source_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_records_id_seq; Type: SEQUENCE OWNED BY; Schema: sources; Owner: -
--

ALTER SEQUENCE sources.source_records_id_seq OWNED BY sources.source_records.id;


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
    CONSTRAINT staging_entry_mode_check CHECK ((entry_mode = ANY (ARRAY['bulk'::text, 'fetch_missing_doi'::text, 'manual_export'::text, 'person_identifier'::text, 'fetch_missing_hal_id'::text, 'fetch_missing_nnt'::text])))
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
-- Name: address_country_candidates; Type: TABLE; Schema: structures; Owner: -
--

CREATE TABLE structures.address_country_candidates (
    address_id integer NOT NULL,
    country_code character(2) NOT NULL,
    method public.country_detection_method NOT NULL,
    detected_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE address_country_candidates; Type: COMMENT; Schema: structures; Owner: -
--

COMMENT ON TABLE structures.address_country_candidates IS 'Pays proposé pour une adresse par un moyen de détection. addresses.countries en dérive par la préséance du domaine.';


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
    publication_count integer DEFAULT 0,
    countries character(2)[],
    CONSTRAINT ck_addresses_normalized_text_not_empty CHECK ((normalized_text <> ''::text))
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
-- Name: structure_parents; Type: TABLE; Schema: structures; Owner: -
--

CREATE TABLE structures.structure_parents (
    id integer NOT NULL,
    parent_id integer NOT NULL,
    child_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT structure_parents_no_self_reference CHECK ((parent_id <> child_id))
);


--
-- Name: structure_parents_id_seq; Type: SEQUENCE; Schema: structures; Owner: -
--

CREATE SEQUENCE structures.structure_parents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: structure_parents_id_seq; Type: SEQUENCE OWNED BY; Schema: structures; Owner: -
--

ALTER SEQUENCE structures.structure_parents_id_seq OWNED BY structures.structure_parents.id;


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
-- Name: hr_records id; Type: DEFAULT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.hr_records ALTER COLUMN id SET DEFAULT nextval('persons.hr_records_id_seq'::regclass);


--
-- Name: person_identifiers id; Type: DEFAULT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.person_identifiers ALTER COLUMN id SET DEFAULT nextval('persons.person_identifiers_id_seq'::regclass);


--
-- Name: persons id; Type: DEFAULT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.persons ALTER COLUMN id SET DEFAULT nextval('persons.persons_id_seq'::regclass);


--
-- Name: contributions id; Type: DEFAULT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.contributions ALTER COLUMN id SET DEFAULT nextval('publications.contributions_id_seq'::regclass);


--
-- Name: manual_merges id; Type: DEFAULT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.manual_merges ALTER COLUMN id SET DEFAULT nextval('publications.manual_merges_id_seq'::regclass);


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
-- Name: monographs id; Type: DEFAULT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.monographs ALTER COLUMN id SET DEFAULT nextval('publishing.monographs_id_seq'::regclass);


--
-- Name: platforms id; Type: DEFAULT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.platforms ALTER COLUMN id SET DEFAULT nextval('publishing.platforms_id_seq'::regclass);


--
-- Name: publisher_name_forms id; Type: DEFAULT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.publisher_name_forms ALTER COLUMN id SET DEFAULT nextval('publishing.publisher_name_forms_id_seq'::regclass);


--
-- Name: publishers id; Type: DEFAULT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.publishers ALTER COLUMN id SET DEFAULT nextval('publishing.publishers_id_seq'::regclass);


--
-- Name: serial_issns id; Type: DEFAULT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.serial_issns ALTER COLUMN id SET DEFAULT nextval('publishing.serial_issns_id_seq'::regclass);


--
-- Name: serial_title_decisions id; Type: DEFAULT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.serial_title_decisions ALTER COLUMN id SET DEFAULT nextval('publishing.serial_title_decisions_id_seq'::regclass);


--
-- Name: serials id; Type: DEFAULT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.serials ALTER COLUMN id SET DEFAULT nextval('publishing.serials_id_seq'::regclass);


--
-- Name: place_name_forms id; Type: DEFAULT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.place_name_forms ALTER COLUMN id SET DEFAULT nextval('ref.place_name_forms_id_seq'::regclass);


--
-- Name: contributor_information id; Type: DEFAULT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.contributor_information ALTER COLUMN id SET DEFAULT nextval('sources.contributor_information_id_seq'::regclass);


--
-- Name: source_contribution_addresses id; Type: DEFAULT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contribution_addresses ALTER COLUMN id SET DEFAULT nextval('sources.source_contribution_addresses_id_seq'::regclass);


--
-- Name: source_contributions id; Type: DEFAULT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contributions ALTER COLUMN id SET DEFAULT nextval('sources.source_contributions_id_seq'::regclass);


--
-- Name: source_records id; Type: DEFAULT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_records ALTER COLUMN id SET DEFAULT nextval('sources.source_records_id_seq'::regclass);


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
-- Name: structure_parents id; Type: DEFAULT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structure_parents ALTER COLUMN id SET DEFAULT nextval('structures.structure_parents_id_seq'::regclass);


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
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (code);


--
-- Name: user_roles user_roles_pkey; Type: CONSTRAINT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.user_roles
    ADD CONSTRAINT user_roles_pkey PRIMARY KEY (user_id, role_code);


--
-- Name: users users_login_key; Type: CONSTRAINT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.users
    ADD CONSTRAINT users_login_key UNIQUE (login);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: confirmed_source_contributions confirmed_source_contributions_pkey; Type: CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.confirmed_source_contributions
    ADD CONSTRAINT confirmed_source_contributions_pkey PRIMARY KEY (source_contribution_id);


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
-- Name: hr_records hr_records_person_id_key; Type: CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.hr_records
    ADD CONSTRAINT hr_records_person_id_key UNIQUE (person_id);


--
-- Name: hr_records hr_records_pkey; Type: CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.hr_records
    ADD CONSTRAINT hr_records_pkey PRIMARY KEY (id);


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
-- Name: rejected_contributions rejected_contributions_pkey; Type: CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.rejected_contributions
    ADD CONSTRAINT rejected_contributions_pkey PRIMARY KEY (source_record_id, person_id);


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
-- Name: aligned_source_contributions aligned_source_contributions_contribution_record_uq; Type: CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.aligned_source_contributions
    ADD CONSTRAINT aligned_source_contributions_contribution_record_uq UNIQUE (contribution_id, source_record_id);


--
-- Name: aligned_source_contributions aligned_source_contributions_pkey; Type: CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.aligned_source_contributions
    ADD CONSTRAINT aligned_source_contributions_pkey PRIMARY KEY (source_contribution_id);


--
-- Name: contributions contributions_pkey; Type: CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.contributions
    ADD CONSTRAINT contributions_pkey PRIMARY KEY (id);


--
-- Name: contributions contributions_publication_person_uq; Type: CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.contributions
    ADD CONSTRAINT contributions_publication_person_uq UNIQUE (publication_id, person_id);


--
-- Name: manual_merge_source_records manual_merge_source_records_pkey; Type: CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.manual_merge_source_records
    ADD CONSTRAINT manual_merge_source_records_pkey PRIMARY KEY (manual_merge_id, source, source_id);


--
-- Name: manual_merges manual_merges_pkey; Type: CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.manual_merges
    ADD CONSTRAINT manual_merges_pkey PRIMARY KEY (id);


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
-- Name: issn_links issn_links_pkey; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.issn_links
    ADD CONSTRAINT issn_links_pkey PRIMARY KEY (issn, linked_issn, link_type);


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
-- Name: platforms platforms_openalex_id_key; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.platforms
    ADD CONSTRAINT platforms_openalex_id_key UNIQUE (openalex_id);


--
-- Name: platforms platforms_pkey; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.platforms
    ADD CONSTRAINT platforms_pkey PRIMARY KEY (id);


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
-- Name: serial_doi_namespaces serial_doi_namespaces_pkey; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.serial_doi_namespaces
    ADD CONSTRAINT serial_doi_namespaces_pkey PRIMARY KEY (namespace);


--
-- Name: serial_issns serial_issns_pkey; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.serial_issns
    ADD CONSTRAINT serial_issns_pkey PRIMARY KEY (id);


--
-- Name: serial_title_decisions serial_title_decisions_pkey; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.serial_title_decisions
    ADD CONSTRAINT serial_title_decisions_pkey PRIMARY KEY (id);


--
-- Name: serials serials_openalex_id_key; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.serials
    ADD CONSTRAINT serials_openalex_id_key UNIQUE (openalex_id);


--
-- Name: serials serials_pkey; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.serials
    ADD CONSTRAINT serials_pkey PRIMARY KEY (id);


--
-- Name: serial_issns uq_serial_issns_issn; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.serial_issns
    ADD CONSTRAINT uq_serial_issns_issn UNIQUE (issn);


--
-- Name: serial_title_decisions uq_serial_title_decisions; Type: CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.serial_title_decisions
    ADD CONSTRAINT uq_serial_title_decisions UNIQUE (title_normalized);


--
-- Name: address_candidates_queue address_candidates_queue_pkey; Type: CONSTRAINT; Schema: queues; Owner: -
--

ALTER TABLE ONLY queues.address_candidates_queue
    ADD CONSTRAINT address_candidates_queue_pkey PRIMARY KEY (id);


--
-- Name: address_countries_queue address_countries_queue_pkey; Type: CONSTRAINT; Schema: queues; Owner: -
--

ALTER TABLE ONLY queues.address_countries_queue
    ADD CONSTRAINT address_countries_queue_pkey PRIMARY KEY (id);


--
-- Name: contribution_attributes_queue contribution_attributes_queue_pkey; Type: CONSTRAINT; Schema: queues; Owner: -
--

ALTER TABLE ONLY queues.contribution_attributes_queue
    ADD CONSTRAINT contribution_attributes_queue_pkey PRIMARY KEY (id);


--
-- Name: contribution_resolution_queue contribution_resolution_queue_pkey; Type: CONSTRAINT; Schema: queues; Owner: -
--

ALTER TABLE ONLY queues.contribution_resolution_queue
    ADD CONSTRAINT contribution_resolution_queue_pkey PRIMARY KEY (id);


--
-- Name: publication_contributions_queue publication_contributions_queue_pkey; Type: CONSTRAINT; Schema: queues; Owner: -
--

ALTER TABLE ONLY queues.publication_contributions_queue
    ADD CONSTRAINT publication_contributions_queue_pkey PRIMARY KEY (id);


--
-- Name: source_contribution_countries_queue source_contribution_countries_queue_pkey; Type: CONSTRAINT; Schema: queues; Owner: -
--

ALTER TABLE ONLY queues.source_contribution_countries_queue
    ADD CONSTRAINT source_contribution_countries_queue_pkey PRIMARY KEY (id);


--
-- Name: source_record_keys_queue source_record_keys_queue_pkey; Type: CONSTRAINT; Schema: queues; Owner: -
--

ALTER TABLE ONLY queues.source_record_keys_queue
    ADD CONSTRAINT source_record_keys_queue_pkey PRIMARY KEY (id);


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
-- Name: contributor_information contributor_information_key; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.contributor_information
    ADD CONSTRAINT contributor_information_key UNIQUE NULLS NOT DISTINCT (last_name_normalized, first_name_normalized, identifiers);


--
-- Name: contributor_information contributor_information_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.contributor_information
    ADD CONSTRAINT contributor_information_pkey PRIMARY KEY (id);


--
-- Name: doi_targets doi_targets_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.doi_targets
    ADD CONSTRAINT doi_targets_pkey PRIMARY KEY (doi);


--
-- Name: dois dois_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.dois
    ADD CONSTRAINT dois_pkey PRIMARY KEY (doi);


--
-- Name: embargoes embargoes_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.embargoes
    ADD CONSTRAINT embargoes_pkey PRIMARY KEY (source_record_id);


--
-- Name: failed_lookups failed_lookups_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.failed_lookups
    ADD CONSTRAINT failed_lookups_pkey PRIMARY KEY (source, id_type, id_value);


--
-- Name: source_contribution_addresses source_contribution_addresses_key; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contribution_addresses
    ADD CONSTRAINT source_contribution_addresses_key UNIQUE (source_contribution_id, address_id);


--
-- Name: source_contribution_addresses source_contribution_addresses_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contribution_addresses
    ADD CONSTRAINT source_contribution_addresses_pkey PRIMARY KEY (id);


--
-- Name: source_contribution_hal_structures source_contribution_hal_structures_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contribution_hal_structures
    ADD CONSTRAINT source_contribution_hal_structures_pkey PRIMARY KEY (source_contribution_id, hal_structure_id);


--
-- Name: source_contribution_rors source_contribution_rors_key; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contribution_rors
    ADD CONSTRAINT source_contribution_rors_key UNIQUE NULLS NOT DISTINCT (source_contribution_id, ror_id, address_id);


--
-- Name: source_contributions source_contributions_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contributions
    ADD CONSTRAINT source_contributions_pkey PRIMARY KEY (id);


--
-- Name: source_contributions source_contributions_record_position_key; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contributions
    ADD CONSTRAINT source_contributions_record_position_key UNIQUE (source_record_id, author_position) DEFERRABLE;


--
-- Name: source_record_identifiers source_record_identifiers_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_record_identifiers
    ADD CONSTRAINT source_record_identifiers_pkey PRIMARY KEY (source_record_id, id_type, id_value);


--
-- Name: source_record_locations source_record_locations_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_record_locations
    ADD CONSTRAINT source_record_locations_pkey PRIMARY KEY (source_record_id, url);


--
-- Name: source_records source_records_pkey; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_records
    ADD CONSTRAINT source_records_pkey PRIMARY KEY (id);


--
-- Name: source_records source_records_source_source_id_key; Type: CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_records
    ADD CONSTRAINT source_records_source_source_id_key UNIQUE (source, source_id);


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
-- Name: address_country_candidates address_country_candidates_pkey; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.address_country_candidates
    ADD CONSTRAINT address_country_candidates_pkey PRIMARY KEY (address_id, country_code, method);


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
-- Name: idref_structures idref_structures_pkey; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.idref_structures
    ADD CONSTRAINT idref_structures_pkey PRIMARY KEY (idref_ppn, structure_id);


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
-- Name: structure_parents structure_parents_parent_id_child_id_key; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structure_parents
    ADD CONSTRAINT structure_parents_parent_id_child_id_key UNIQUE (parent_id, child_id);


--
-- Name: structure_parents structure_parents_pkey; Type: CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structure_parents
    ADD CONSTRAINT structure_parents_pkey PRIMARY KEY (id);


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
-- Name: audit_log_created_at_idx; Type: INDEX; Schema: ops; Owner: -
--

CREATE INDEX audit_log_created_at_idx ON ops.audit_log USING btree (created_at DESC);


--
-- Name: audit_log_entity_idx; Type: INDEX; Schema: ops; Owner: -
--

CREATE INDEX audit_log_entity_idx ON ops.audit_log USING btree (entity_type, entity_id);


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
-- Name: idx_confirmed_source_contributions_person; Type: INDEX; Schema: persons; Owner: -
--

CREATE INDEX idx_confirmed_source_contributions_person ON persons.confirmed_source_contributions USING btree (person_id);


--
-- Name: idx_hr_records_department; Type: INDEX; Schema: persons; Owner: -
--

CREATE INDEX idx_hr_records_department ON persons.hr_records USING btree (department_name);


--
-- Name: idx_hr_records_person_id; Type: INDEX; Schema: persons; Owner: -
--

CREATE INDEX idx_hr_records_person_id ON persons.hr_records USING btree (person_id);


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
-- Name: idx_pnf_person_id; Type: INDEX; Schema: persons; Owner: -
--

CREATE INDEX idx_pnf_person_id ON persons.person_name_forms USING btree (person_id);


--
-- Name: idx_rejected_contributions_person; Type: INDEX; Schema: persons; Owner: -
--

CREATE INDEX idx_rejected_contributions_person ON persons.rejected_contributions USING btree (person_id);


--
-- Name: idx_merge_redirects_kept; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_merge_redirects_kept ON public.merge_redirects USING btree (entity, kept_id);


--
-- Name: contribution_structures_pkey; Type: INDEX; Schema: publications; Owner: -
--

CREATE UNIQUE INDEX contribution_structures_pkey ON publications.contribution_structures USING btree (contribution_id, structure_id);


--
-- Name: contributions_orphans_idx; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX contributions_orphans_idx ON publications.contributions USING btree (publication_id) WHERE ((person_id IS NULL) AND in_perimeter);


--
-- Name: contributions_person_id_idx; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX contributions_person_id_idx ON publications.contributions USING btree (person_id) INCLUDE (publication_id, roles) WHERE (person_id IS NOT NULL);


--
-- Name: idx_contribution_structures_structure_id; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_contribution_structures_structure_id ON publications.contribution_structures USING btree (structure_id);


--
-- Name: idx_manual_merge_source_records_source_record; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_manual_merge_source_records_source_record ON publications.manual_merge_source_records USING btree (source, source_id);


--
-- Name: idx_publication_relations_target_doi; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publication_relations_target_doi ON publications.publication_relations USING btree (target_doi);


--
-- Name: idx_publication_relations_target_publication; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publication_relations_target_publication ON publications.publication_relations USING btree (target_publication_id) WHERE (target_publication_id IS NOT NULL);


--
-- Name: idx_publication_rors_ror; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publication_rors_ror ON publications.publication_rors USING btree (ror_id);


--
-- Name: idx_publication_structures_structure; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publication_structures_structure ON publications.publication_structures USING btree (structure_id);


--
-- Name: idx_publications_countries; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_countries ON publications.publications USING gin (countries) WHERE (countries IS NOT NULL);


--
-- Name: idx_publications_doi_prefix; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_doi_prefix ON publications.publications USING btree (doi_prefix) WHERE (doi_prefix IS NOT NULL);


--
-- Name: idx_publications_in_perimeter_serial; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_in_perimeter_serial ON publications.publications USING btree (serial_id) WHERE in_perimeter;


--
-- Name: idx_publications_in_perimeter_year; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_in_perimeter_year ON publications.publications USING btree (publication_year DESC) WHERE in_perimeter;


--
-- Name: idx_publications_monograph; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_monograph ON publications.publications USING btree (monograph_id) WHERE (monograph_id IS NOT NULL);


--
-- Name: idx_publications_publisher; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_publisher ON publications.publications USING btree (publisher_id) WHERE (publisher_id IS NOT NULL);


--
-- Name: idx_publications_serial; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_serial ON publications.publications USING btree (serial_id);


--
-- Name: idx_publications_source_extras; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_source_extras ON publications.publications USING gin (source_extras) WHERE (source_extras IS NOT NULL);


--
-- Name: idx_publications_sources; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_sources ON publications.publications USING gin (sources);


--
-- Name: idx_publications_title_normalized; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_title_normalized ON publications.publications USING hash (title_normalized);


--
-- Name: idx_publications_title_trgm; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_title_trgm ON publications.publications USING gin (title_normalized public.gin_trgm_ops);


--
-- Name: idx_publications_year; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_year ON publications.publications USING btree (publication_year);


--
-- Name: idx_publications_year_type; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX idx_publications_year_type ON publications.publications USING btree (publication_year, doc_type);


--
-- Name: ix_aligned_source_contributions_source_record_id; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX ix_aligned_source_contributions_source_record_id ON publications.aligned_source_contributions USING btree (source_record_id);


--
-- Name: publication_author_alignment_pkey; Type: INDEX; Schema: publications; Owner: -
--

CREATE UNIQUE INDEX publication_author_alignment_pkey ON publications.publication_author_alignment USING btree (publication_id);


--
-- Name: publication_rors_pkey; Type: INDEX; Schema: publications; Owner: -
--

CREATE UNIQUE INDEX publication_rors_pkey ON publications.publication_rors USING btree (publication_id, ror_id);


--
-- Name: publication_structures_publication_structure; Type: INDEX; Schema: publications; Owner: -
--

CREATE UNIQUE INDEX publication_structures_publication_structure ON publications.publication_structures USING btree (publication_id, structure_id);


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
-- Name: subjects_label_normalized_trgm_idx; Type: INDEX; Schema: publications; Owner: -
--

CREATE INDEX subjects_label_normalized_trgm_idx ON publications.subjects USING gin (label_normalized public.gin_trgm_ops);


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
-- Name: idx_apc_payments_publication; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_apc_payments_publication ON publishing.apc_payments USING btree (publication_id) WHERE (publication_id IS NOT NULL);


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
-- Name: idx_issn_links_linked; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_issn_links_linked ON publishing.issn_links USING btree (linked_issn);


--
-- Name: idx_monographs_publisher; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_monographs_publisher ON publishing.monographs USING btree (publisher_id);


--
-- Name: idx_monographs_serial; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_monographs_serial ON publishing.monographs USING btree (serial_id);


--
-- Name: idx_monographs_title_normalized; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_monographs_title_normalized ON publishing.monographs USING hash (title_normalized);


--
-- Name: idx_publisher_name_forms_publisher; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_publisher_name_forms_publisher ON publishing.publisher_name_forms USING btree (publisher_id);


--
-- Name: idx_publishers_name_norm; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_publishers_name_norm ON publishing.publishers USING btree (name_normalized);


--
-- Name: idx_publishers_name_trgm; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_publishers_name_trgm ON publishing.publishers USING gin (name public.gin_trgm_ops);


--
-- Name: idx_serial_issns_serial; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_serial_issns_serial ON publishing.serial_issns USING btree (serial_id);


--
-- Name: idx_serials_publisher; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_serials_publisher ON publishing.serials USING btree (publisher_id);


--
-- Name: idx_serials_title_normalized; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX idx_serials_title_normalized ON publishing.serials USING hash (title_normalized);


--
-- Name: ix_serial_doi_namespaces_serial_id; Type: INDEX; Schema: publishing; Owner: -
--

CREATE INDEX ix_serial_doi_namespaces_serial_id ON publishing.serial_doi_namespaces USING btree (serial_id);


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
-- Name: contributor_information_author_name_normalized_idx; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX contributor_information_author_name_normalized_idx ON sources.contributor_information USING btree (author_name_normalized);


--
-- Name: contributor_information_idref_idx; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX contributor_information_idref_idx ON sources.contributor_information USING btree (((identifiers ->> 'idref'::text))) WHERE (identifiers ? 'idref'::text);


--
-- Name: contributor_information_key_hash_idx; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX contributor_information_key_hash_idx ON sources.contributor_information USING btree (key_hash);


--
-- Name: contributor_information_orcid_idx; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX contributor_information_orcid_idx ON sources.contributor_information USING btree (((identifiers ->> 'orcid'::text))) WHERE (identifiers ? 'orcid'::text);


--
-- Name: idx_doi_targets_target_doi; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_doi_targets_target_doi ON sources.doi_targets USING btree (target_doi);


--
-- Name: idx_saa_address; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_saa_address ON sources.source_contribution_addresses USING btree (address_id);


--
-- Name: idx_source_contribution_structures_structure_id; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_contribution_structures_structure_id ON sources.source_contribution_structures USING btree (structure_id);


--
-- Name: idx_source_contributions_contributor_information; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_contributions_contributor_information ON sources.source_contributions USING btree (contributor_information_id);


--
-- Name: idx_source_contributions_in_perimeter; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_contributions_in_perimeter ON sources.source_contributions USING btree (source_record_id) WHERE (in_perimeter = true);


--
-- Name: idx_source_record_identifiers_value; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_record_identifiers_value ON sources.source_record_identifiers USING btree (id_type, id_value);


--
-- Name: idx_source_record_locations_platform; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_record_locations_platform ON sources.source_record_locations USING btree (platform_id) WHERE (platform_id IS NOT NULL);


--
-- Name: idx_source_records_countries; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_records_countries ON sources.source_records USING gin (countries) WHERE (countries IS NOT NULL);


--
-- Name: idx_source_records_hal_collections; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_records_hal_collections ON sources.source_records USING gin (hal_collections) WHERE (hal_collections IS NOT NULL);


--
-- Name: idx_source_records_monograph; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_records_monograph ON sources.source_records USING btree (monograph_id) WHERE (monograph_id IS NOT NULL);


--
-- Name: idx_source_records_publication; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_records_publication ON sources.source_records USING btree (publication_id) WHERE (publication_id IS NOT NULL);


--
-- Name: idx_source_records_publisher; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_records_publisher ON sources.source_records USING btree (publisher_id) WHERE (publisher_id IS NOT NULL);


--
-- Name: idx_source_records_serial; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_records_serial ON sources.source_records USING btree (serial_id) WHERE (serial_id IS NOT NULL);


--
-- Name: idx_source_records_staging; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_records_staging ON sources.source_records USING btree (staging_id) WHERE (staging_id IS NOT NULL);


--
-- Name: idx_source_records_title_normalized; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_records_title_normalized ON sources.source_records USING hash (title_normalized);


--
-- Name: idx_source_records_title_normalized_trgm; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX idx_source_records_title_normalized_trgm ON sources.source_records USING gin (title_normalized public.gin_trgm_ops);


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
-- Name: ix_source_contribution_hal_structures_hal_structure_id; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX ix_source_contribution_hal_structures_hal_structure_id ON sources.source_contribution_hal_structures USING btree (hal_structure_id);


--
-- Name: ix_source_contribution_rors_address_id; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX ix_source_contribution_rors_address_id ON sources.source_contribution_rors USING btree (address_id);


--
-- Name: ix_source_contribution_rors_ror_id; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX ix_source_contribution_rors_ror_id ON sources.source_contribution_rors USING btree (ror_id);


--
-- Name: source_contribution_structures_pkey; Type: INDEX; Schema: sources; Owner: -
--

CREATE UNIQUE INDEX source_contribution_structures_pkey ON sources.source_contribution_structures USING btree (source_contribution_id, structure_id, evidence);


--
-- Name: source_contributions_duplicate_of_idx; Type: INDEX; Schema: sources; Owner: -
--

CREATE INDEX source_contributions_duplicate_of_idx ON sources.source_contributions USING btree (duplicate_of) WHERE (duplicate_of IS NOT NULL);


--
-- Name: uq_source_record_identifiers_derived; Type: INDEX; Schema: sources; Owner: -
--

CREATE UNIQUE INDEX uq_source_record_identifiers_derived ON sources.source_record_identifiers USING btree (source_record_id) WHERE (role = 'derived'::public.source_identifier_role);


--
-- Name: addresses_normalized_text_key; Type: INDEX; Schema: structures; Owner: -
--

CREATE UNIQUE INDEX addresses_normalized_text_key ON structures.addresses USING btree (md5(normalized_text));


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
-- Name: idx_addresses_countries; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_addresses_countries ON structures.addresses USING gin (countries) WHERE (countries IS NOT NULL);


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

CREATE INDEX idx_struct_tut_child ON structures.structure_parents USING btree (child_id);


--
-- Name: idx_struct_tut_parent; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_struct_tut_parent ON structures.structure_parents USING btree (parent_id);


--
-- Name: idx_structure_name_forms_structure; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_structure_name_forms_structure ON structures.structure_name_forms USING btree (structure_id);


--
-- Name: idx_structures_type; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX idx_structures_type ON structures.structures USING btree (structure_type);


--
-- Name: ix_idref_structures_structure_id; Type: INDEX; Schema: structures; Owner: -
--

CREATE INDEX ix_idref_structures_structure_id ON structures.idref_structures USING btree (structure_id);


--
-- Name: person_identifiers trg_protect_authenticated_identifier; Type: TRIGGER; Schema: persons; Owner: -
--

CREATE TRIGGER trg_protect_authenticated_identifier BEFORE INSERT OR UPDATE ON persons.person_identifiers FOR EACH ROW EXECUTE FUNCTION public.protect_authenticated_identifier();


--
-- Name: persons trg_regroup_on_first_name_change; Type: TRIGGER; Schema: persons; Owner: -
--

CREATE TRIGGER trg_regroup_on_first_name_change AFTER UPDATE OF first_name_normalized ON persons.persons FOR EACH ROW WHEN ((old.first_name_normalized IS DISTINCT FROM new.first_name_normalized)) EXECUTE FUNCTION public.regroup_on_first_name_change();


--
-- Name: person_identifiers trg_regroup_on_identifier_delete; Type: TRIGGER; Schema: persons; Owner: -
--

CREATE TRIGGER trg_regroup_on_identifier_delete AFTER DELETE ON persons.person_identifiers FOR EACH ROW WHEN (((old.id_type = ANY (ARRAY['orcid'::text, 'idref'::text])) AND (old.status = ANY (ARRAY['confirmed'::public.identifier_status, 'authenticated'::public.identifier_status])))) EXECUTE FUNCTION public.regroup_on_identifier_decision();


--
-- Name: person_identifiers trg_regroup_on_identifier_insert; Type: TRIGGER; Schema: persons; Owner: -
--

CREATE TRIGGER trg_regroup_on_identifier_insert AFTER INSERT ON persons.person_identifiers FOR EACH ROW WHEN (((new.id_type = ANY (ARRAY['orcid'::text, 'idref'::text])) AND (new.status = ANY (ARRAY['confirmed'::public.identifier_status, 'authenticated'::public.identifier_status])))) EXECUTE FUNCTION public.regroup_on_identifier_decision();


--
-- Name: person_identifiers trg_regroup_on_identifier_update; Type: TRIGGER; Schema: persons; Owner: -
--

CREATE TRIGGER trg_regroup_on_identifier_update AFTER UPDATE OF status, person_id ON persons.person_identifiers FOR EACH ROW WHEN (((new.id_type = ANY (ARRAY['orcid'::text, 'idref'::text])) AND ((old.status = ANY (ARRAY['confirmed'::public.identifier_status, 'authenticated'::public.identifier_status])) OR (new.status = ANY (ARRAY['confirmed'::public.identifier_status, 'authenticated'::public.identifier_status]))) AND ((old.status IS DISTINCT FROM new.status) OR (old.person_id IS DISTINCT FROM new.person_id)))) EXECUTE FUNCTION public.regroup_on_identifier_decision();


--
-- Name: user_roles user_roles_role_code_fkey; Type: FK CONSTRAINT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.user_roles
    ADD CONSTRAINT user_roles_role_code_fkey FOREIGN KEY (role_code) REFERENCES ops.roles(code);


--
-- Name: user_roles user_roles_user_id_fkey; Type: FK CONSTRAINT; Schema: ops; Owner: -
--

ALTER TABLE ONLY ops.user_roles
    ADD CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES ops.users(id) ON DELETE CASCADE;


--
-- Name: confirmed_source_contributions confirmed_source_contributions_person_id_fkey; Type: FK CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.confirmed_source_contributions
    ADD CONSTRAINT confirmed_source_contributions_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons.persons(id) ON DELETE CASCADE;


--
-- Name: confirmed_source_contributions confirmed_source_contributions_source_contribution_id_fkey; Type: FK CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.confirmed_source_contributions
    ADD CONSTRAINT confirmed_source_contributions_source_contribution_id_fkey FOREIGN KEY (source_contribution_id) REFERENCES sources.source_contributions(id) ON DELETE CASCADE;


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
-- Name: hr_records hr_records_person_id_fkey; Type: FK CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.hr_records
    ADD CONSTRAINT hr_records_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons.persons(id) ON DELETE RESTRICT;


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
-- Name: rejected_contributions rejected_contributions_person_id_fkey; Type: FK CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.rejected_contributions
    ADD CONSTRAINT rejected_contributions_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons.persons(id) ON DELETE CASCADE;


--
-- Name: rejected_contributions rejected_contributions_source_record_id_fkey; Type: FK CONSTRAINT; Schema: persons; Owner: -
--

ALTER TABLE ONLY persons.rejected_contributions
    ADD CONSTRAINT rejected_contributions_source_record_id_fkey FOREIGN KEY (source_record_id) REFERENCES sources.source_records(id) ON DELETE CASCADE;


--
-- Name: aligned_source_contributions aligned_source_contributions_contribution_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.aligned_source_contributions
    ADD CONSTRAINT aligned_source_contributions_contribution_id_fkey FOREIGN KEY (contribution_id) REFERENCES publications.contributions(id) ON DELETE CASCADE;


--
-- Name: aligned_source_contributions aligned_source_contributions_source_contribution_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.aligned_source_contributions
    ADD CONSTRAINT aligned_source_contributions_source_contribution_id_fkey FOREIGN KEY (source_contribution_id) REFERENCES sources.source_contributions(id) ON DELETE CASCADE;


--
-- Name: aligned_source_contributions aligned_source_contributions_source_record_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.aligned_source_contributions
    ADD CONSTRAINT aligned_source_contributions_source_record_id_fkey FOREIGN KEY (source_record_id) REFERENCES sources.source_records(id) ON DELETE CASCADE;


--
-- Name: contributions contributions_person_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.contributions
    ADD CONSTRAINT contributions_person_id_fkey FOREIGN KEY (person_id) REFERENCES persons.persons(id) ON DELETE SET NULL;


--
-- Name: contributions contributions_publication_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.contributions
    ADD CONSTRAINT contributions_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES publications.publications(id) ON DELETE CASCADE;


--
-- Name: manual_merge_source_records manual_merge_source_records_manual_merge_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.manual_merge_source_records
    ADD CONSTRAINT manual_merge_source_records_manual_merge_id_fkey FOREIGN KEY (manual_merge_id) REFERENCES publications.manual_merges(id) ON DELETE CASCADE;


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
-- Name: publications publications_monograph_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publications
    ADD CONSTRAINT publications_monograph_id_fkey FOREIGN KEY (monograph_id) REFERENCES publishing.monographs(id);


--
-- Name: publications publications_publisher_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publications
    ADD CONSTRAINT publications_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES publishing.publishers(id);


--
-- Name: publications publications_serial_id_fkey; Type: FK CONSTRAINT; Schema: publications; Owner: -
--

ALTER TABLE ONLY publications.publications
    ADD CONSTRAINT publications_serial_id_fkey FOREIGN KEY (serial_id) REFERENCES publishing.serials(id);


--
-- Name: apc_payments apc_payments_budget_structure_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.apc_payments
    ADD CONSTRAINT apc_payments_budget_structure_id_fkey FOREIGN KEY (budget_structure_id) REFERENCES structures.structures(id) ON DELETE SET NULL;


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
-- Name: apc_payments apc_payments_serial_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.apc_payments
    ADD CONSTRAINT apc_payments_serial_id_fkey FOREIGN KEY (serial_id) REFERENCES publishing.serials(id) ON DELETE SET NULL;


--
-- Name: doi_prefixes doi_prefixes_publisher_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.doi_prefixes
    ADD CONSTRAINT doi_prefixes_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES publishing.publishers(id) ON DELETE SET NULL;


--
-- Name: monographs monographs_publisher_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.monographs
    ADD CONSTRAINT monographs_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES publishing.publishers(id) ON DELETE SET NULL;


--
-- Name: monographs monographs_serial_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.monographs
    ADD CONSTRAINT monographs_serial_id_fkey FOREIGN KEY (serial_id) REFERENCES publishing.serials(id) ON DELETE SET NULL;


--
-- Name: publisher_name_forms publisher_name_forms_publisher_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.publisher_name_forms
    ADD CONSTRAINT publisher_name_forms_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES publishing.publishers(id) ON DELETE CASCADE;


--
-- Name: serial_doi_namespaces serial_doi_namespaces_serial_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.serial_doi_namespaces
    ADD CONSTRAINT serial_doi_namespaces_serial_id_fkey FOREIGN KEY (serial_id) REFERENCES publishing.serials(id) ON DELETE CASCADE;


--
-- Name: serial_issns serial_issns_serial_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.serial_issns
    ADD CONSTRAINT serial_issns_serial_id_fkey FOREIGN KEY (serial_id) REFERENCES publishing.serials(id) ON DELETE SET NULL;


--
-- Name: serial_title_decisions serial_title_decisions_serial_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.serial_title_decisions
    ADD CONSTRAINT serial_title_decisions_serial_id_fkey FOREIGN KEY (serial_id) REFERENCES publishing.serials(id) ON DELETE CASCADE;


--
-- Name: serials serials_publisher_id_fkey; Type: FK CONSTRAINT; Schema: publishing; Owner: -
--

ALTER TABLE ONLY publishing.serials
    ADD CONSTRAINT serials_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES publishing.publishers(id);


--
-- Name: contribution_resolution_queue contribution_resolution_queue_id_fkey; Type: FK CONSTRAINT; Schema: queues; Owner: -
--

ALTER TABLE ONLY queues.contribution_resolution_queue
    ADD CONSTRAINT contribution_resolution_queue_id_fkey FOREIGN KEY (id) REFERENCES publications.contributions(id) ON DELETE CASCADE;


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
-- Name: place_name_forms place_name_forms_iso_code_fkey; Type: FK CONSTRAINT; Schema: ref; Owner: -
--

ALTER TABLE ONLY ref.place_name_forms
    ADD CONSTRAINT place_name_forms_iso_code_fkey FOREIGN KEY (iso_code) REFERENCES ref.countries(code);


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
-- Name: embargoes embargoes_source_record_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.embargoes
    ADD CONSTRAINT embargoes_source_record_id_fkey FOREIGN KEY (source_record_id) REFERENCES sources.source_records(id) ON DELETE CASCADE;


--
-- Name: source_contribution_addresses source_contribution_addresses_address_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contribution_addresses
    ADD CONSTRAINT source_contribution_addresses_address_id_fkey FOREIGN KEY (address_id) REFERENCES structures.addresses(id) ON DELETE CASCADE;


--
-- Name: source_contribution_addresses source_contribution_addresses_source_contribution_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contribution_addresses
    ADD CONSTRAINT source_contribution_addresses_source_contribution_id_fkey FOREIGN KEY (source_contribution_id) REFERENCES sources.source_contributions(id) ON DELETE CASCADE;


--
-- Name: source_contribution_hal_structures source_contribution_hal_structures_source_contribution_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contribution_hal_structures
    ADD CONSTRAINT source_contribution_hal_structures_source_contribution_id_fkey FOREIGN KEY (source_contribution_id) REFERENCES sources.source_contributions(id) ON DELETE CASCADE;


--
-- Name: source_contribution_rors source_contribution_rors_address_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contribution_rors
    ADD CONSTRAINT source_contribution_rors_address_id_fkey FOREIGN KEY (address_id) REFERENCES structures.addresses(id) ON DELETE CASCADE;


--
-- Name: source_contribution_rors source_contribution_rors_source_contribution_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contribution_rors
    ADD CONSTRAINT source_contribution_rors_source_contribution_id_fkey FOREIGN KEY (source_contribution_id) REFERENCES sources.source_contributions(id) ON DELETE CASCADE;


--
-- Name: source_contributions source_contributions_contributor_information_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contributions
    ADD CONSTRAINT source_contributions_contributor_information_id_fkey FOREIGN KEY (contributor_information_id) REFERENCES sources.contributor_information(id);


--
-- Name: source_contributions source_contributions_duplicate_of_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contributions
    ADD CONSTRAINT source_contributions_duplicate_of_fkey FOREIGN KEY (duplicate_of) REFERENCES sources.source_contributions(id) ON DELETE SET NULL;


--
-- Name: source_contributions source_contributions_source_record_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_contributions
    ADD CONSTRAINT source_contributions_source_record_id_fkey FOREIGN KEY (source_record_id) REFERENCES sources.source_records(id) ON DELETE CASCADE;


--
-- Name: source_record_identifiers source_record_identifiers_source_record_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_record_identifiers
    ADD CONSTRAINT source_record_identifiers_source_record_id_fkey FOREIGN KEY (source_record_id) REFERENCES sources.source_records(id) ON DELETE CASCADE;


--
-- Name: source_record_locations source_record_locations_platform_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_record_locations
    ADD CONSTRAINT source_record_locations_platform_id_fkey FOREIGN KEY (platform_id) REFERENCES publishing.platforms(id);


--
-- Name: source_record_locations source_record_locations_source_record_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_record_locations
    ADD CONSTRAINT source_record_locations_source_record_id_fkey FOREIGN KEY (source_record_id) REFERENCES sources.source_records(id) ON DELETE CASCADE;


--
-- Name: source_records source_records_monograph_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_records
    ADD CONSTRAINT source_records_monograph_id_fkey FOREIGN KEY (monograph_id) REFERENCES publishing.monographs(id);


--
-- Name: source_records source_records_publication_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_records
    ADD CONSTRAINT source_records_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES publications.publications(id) ON DELETE SET NULL;


--
-- Name: source_records source_records_publisher_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_records
    ADD CONSTRAINT source_records_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES publishing.publishers(id);


--
-- Name: source_records source_records_serial_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_records
    ADD CONSTRAINT source_records_serial_id_fkey FOREIGN KEY (serial_id) REFERENCES publishing.serials(id);


--
-- Name: source_records source_records_staging_id_fkey; Type: FK CONSTRAINT; Schema: sources; Owner: -
--

ALTER TABLE ONLY sources.source_records
    ADD CONSTRAINT source_records_staging_id_fkey FOREIGN KEY (staging_id) REFERENCES sources.staging(id);


--
-- Name: address_country_candidates address_country_candidates_address_id_fkey; Type: FK CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.address_country_candidates
    ADD CONSTRAINT address_country_candidates_address_id_fkey FOREIGN KEY (address_id) REFERENCES structures.addresses(id) ON DELETE CASCADE;


--
-- Name: address_country_candidates address_country_candidates_country_code_fkey; Type: FK CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.address_country_candidates
    ADD CONSTRAINT address_country_candidates_country_code_fkey FOREIGN KEY (country_code) REFERENCES ref.countries(code);


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
-- Name: idref_structures idref_structures_matched_form_id_fkey; Type: FK CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.idref_structures
    ADD CONSTRAINT idref_structures_matched_form_id_fkey FOREIGN KEY (matched_form_id) REFERENCES structures.structure_name_forms(id) ON DELETE SET NULL;


--
-- Name: idref_structures idref_structures_structure_id_fkey; Type: FK CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.idref_structures
    ADD CONSTRAINT idref_structures_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES structures.structures(id) ON DELETE CASCADE;


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
-- Name: structure_parents structure_parents_child_id_fkey; Type: FK CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structure_parents
    ADD CONSTRAINT structure_parents_child_id_fkey FOREIGN KEY (child_id) REFERENCES structures.structures(id) ON DELETE CASCADE;


--
-- Name: structure_parents structure_parents_parent_id_fkey; Type: FK CONSTRAINT; Schema: structures; Owner: -
--

ALTER TABLE ONLY structures.structure_parents
    ADD CONSTRAINT structure_parents_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES structures.structures(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict S3g5501iNWm1LUqnDvEYQ7zmM9H5ixYWxHjLkBI8qpPECT0JF6fCbJzmwem9jku

