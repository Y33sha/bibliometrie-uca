--
-- PostgreSQL database dump
--

\restrict kZ778K8DdBfSH5h6fUrVfnfzm24Znof1Pp488rglJjJ8AqtWeaPqgrHNCBdEANu

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
    'rejected'
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
-- Name: publisher_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.publisher_type AS ENUM (
    'commercial',
    'learned_society',
    'academic_institution',
    'repository',
    'aggregator',
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
    'onr'
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

    -- Retrait des balises MathML/HTML (<i>, <sub>, <mml:*> …) en entier.
    -- Premier caractère = lettre ou '/' : préserve les indices de Miller
    -- <111>/<110> (cristallographie), qui sont du contenu, pas du markup.
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

    -- Chiffres exposants/indices → chiffres ASCII (attachés). L'exposant moins
    -- `⁻` n'est plus listé : il tombe dans le passage [^a-z0-9] → espace.
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


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: address_structures; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.address_structures (
    id integer NOT NULL,
    address_id integer NOT NULL,
    structure_id integer NOT NULL,
    matched_form_id integer,
    is_confirmed boolean
);


--
-- Name: address_structures_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.address_structures_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: address_structures_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.address_structures_id_seq OWNED BY public.address_structures.id;


--
-- Name: addresses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.addresses (
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
-- Name: addresses_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.addresses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: addresses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.addresses_id_seq OWNED BY public.addresses.id;


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: apc_payments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.apc_payments (
    id integer NOT NULL,
    lab_name text,
    publisher_name text,
    publisher_type text,
    journal_name text,
    issn text,
    journal_type text,
    doi text,
    article_title text,
    amount_eur_ht numeric(12,2),
    billing_year smallint,
    pub_year smallint,
    budget text,
    institution text,
    institution_type text,
    coman_id integer,
    all_surveys_answered text,
    shared_payment text,
    source_file text,
    expense_type text,
    remarks text,
    publication_id integer,
    journal_id integer,
    publisher_id integer,
    created_at timestamp with time zone DEFAULT now(),
    budget_structure_id integer,
    lab_structure_id integer
);


--
-- Name: apc_payments_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.apc_payments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: apc_payments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.apc_payments_id_seq OWNED BY public.apc_payments.id;


--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_log (
    id bigint NOT NULL,
    event_type text NOT NULL,
    aggregate_type text NOT NULL,
    aggregate_id integer,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    user_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE audit_log; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.audit_log IS 'Trace des opérations destructives/décisionnelles déclenchées via l''admin HTTP. Les opérations du pipeline ne sont pas auditées.';


--
-- Name: COLUMN audit_log.event_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_log.event_type IS 'Type d''événement, notation pointée : person.merged, publication.excluded, structure.deleted, etc.';


--
-- Name: COLUMN audit_log.aggregate_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_log.aggregate_type IS 'Type de l''entité affectée : person, publication, structure, journal, publisher, authorship.';


--
-- Name: COLUMN audit_log.aggregate_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_log.aggregate_id IS 'ID de l''entité affectée, NULL si l''entité a été supprimée et n''a pas d''équivalent survivant.';


--
-- Name: COLUMN audit_log.payload; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_log.payload IS 'Données utiles pour l''audit : source_id d''une fusion, champs modifiés, raison, etc.';


--
-- Name: COLUMN audit_log.user_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.audit_log.user_id IS 'Utilisateur admin authentifié ayant déclenché l''opération (middleware auth). NULL théoriquement impossible quand l''entrée est écrite.';


--
-- Name: audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_log_id_seq OWNED BY public.audit_log.id;


--
-- Name: config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.config (
    key text NOT NULL,
    value jsonb NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: perimeter_structures; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.perimeter_structures (
    perimeter_id integer NOT NULL,
    structure_id integer NOT NULL
);


--
-- Name: perimeters; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.perimeters (
    id integer NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now(),
    structure_ids integer[] DEFAULT '{}'::integer[] NOT NULL
);


--
-- Name: source_authorship_addresses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_authorship_addresses (
    id integer NOT NULL,
    source_authorship_id integer NOT NULL,
    address_id integer NOT NULL
);


--
-- Name: source_authorship_structures; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.source_authorship_structures AS
 SELECT DISTINCT saa.source_authorship_id,
    ps.structure_id
   FROM ((public.source_authorship_addresses saa
     JOIN public.address_structures ast ON ((ast.address_id = saa.address_id)))
     JOIN public.perimeter_structures ps ON ((ps.structure_id = ast.structure_id)))
  WHERE ((ast.is_confirmed IS DISTINCT FROM false) AND (ps.perimeter_id = ( SELECT perimeters.id
           FROM public.perimeters
          WHERE (perimeters.code = ( SELECT (config.value #>> '{}'::text[])
                   FROM public.config
                  WHERE (config.key = 'perimeter_affiliations'::text))))))
  WITH NO DATA;


--
-- Name: source_authorships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_authorships (
    id integer NOT NULL,
    source public.source_type NOT NULL,
    source_publication_id integer NOT NULL,
    author_position smallint,
    in_perimeter boolean DEFAULT false,
    countries text[],
    person_id integer,
    author_name_normalized text,
    is_corresponding boolean DEFAULT false,
    roles text[] DEFAULT ARRAY['author'::text],
    source_data jsonb,
    authorship_id integer,
    raw_author_name text,
    person_identifiers jsonb,
    source_structures text[],
    created_at timestamp with time zone DEFAULT now(),
    countries_dirty boolean DEFAULT true NOT NULL
);


--
-- Name: authorship_structures; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.authorship_structures AS
 SELECT DISTINCT sa.authorship_id,
    sas.structure_id
   FROM (public.source_authorship_structures sas
     JOIN public.source_authorships sa ON ((sa.id = sas.source_authorship_id)))
  WHERE (sa.authorship_id IS NOT NULL)
  WITH NO DATA;


--
-- Name: authorships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.authorships (
    id integer NOT NULL,
    publication_id integer NOT NULL,
    person_id integer,
    author_position smallint,
    in_perimeter boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    is_corresponding boolean,
    roles text[]
);


--
-- Name: authorships_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.authorships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: authorships_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.authorships_id_seq OWNED BY public.authorships.id;


--
-- Name: countries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.countries (
    code character(2) NOT NULL,
    name text NOT NULL
);


--
-- Name: distinct_persons; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.distinct_persons (
    id integer NOT NULL,
    person_id_a integer NOT NULL,
    person_id_b integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT distinct_persons_ordered CHECK ((person_id_a < person_id_b))
);


--
-- Name: distinct_persons_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.distinct_persons_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: distinct_persons_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.distinct_persons_id_seq OWNED BY public.distinct_persons.id;


--
-- Name: distinct_publications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.distinct_publications (
    id integer NOT NULL,
    pub_id_a integer NOT NULL,
    pub_id_b integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT distinct_pubs_ordered CHECK ((pub_id_a < pub_id_b))
);


--
-- Name: distinct_publications_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.distinct_publications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: distinct_publications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.distinct_publications_id_seq OWNED BY public.distinct_publications.id;


--
-- Name: doi_lookups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.doi_lookups (
    source public.source_type NOT NULL,
    doi text NOT NULL,
    not_found_at timestamp with time zone NOT NULL,
    next_retry timestamp with time zone NOT NULL
);


--
-- Name: doi_prefixes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.doi_prefixes (
    prefix text NOT NULL,
    ra text NOT NULL,
    publisher_id integer,
    publisher_name_raw text,
    publisher_name_normalized text,
    crossref_member_id integer,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    client_name_raw text,
    client_name_normalized text,
    datacite_client_symbol text
);


--
-- Name: journal_name_forms; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.journal_name_forms (
    id integer NOT NULL,
    journal_id integer NOT NULL,
    form_normalized text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    publisher_id integer
);


--
-- Name: journal_name_forms_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.journal_name_forms_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: journal_name_forms_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.journal_name_forms_id_seq OWNED BY public.journal_name_forms.id;


--
-- Name: journals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.journals (
    id integer NOT NULL,
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
    created_at timestamp with time zone DEFAULT now(),
    journal_type public.journal_type DEFAULT 'unknown'::public.journal_type,
    is_academic boolean DEFAULT true,
    doi_prefix text,
    doaj_payload jsonb,
    doaj_imported_at timestamp with time zone,
    pub_count integer DEFAULT 0 NOT NULL
);


--
-- Name: journals_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.journals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: journals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.journals_id_seq OWNED BY public.journals.id;


--
-- Name: perimeters_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.perimeters_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: perimeters_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.perimeters_id_seq OWNED BY public.perimeters.id;


--
-- Name: person_identifiers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.person_identifiers (
    id integer NOT NULL,
    person_id integer NOT NULL,
    id_type text NOT NULL,
    id_value text NOT NULL,
    source public.identifier_origin NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    status public.identifier_status DEFAULT 'pending'::public.identifier_status NOT NULL
);


--
-- Name: person_identifiers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.person_identifiers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: person_identifiers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.person_identifiers_id_seq OWNED BY public.person_identifiers.id;


--
-- Name: person_name_forms; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.person_name_forms (
    name_form text NOT NULL,
    person_id integer NOT NULL,
    sources text[] DEFAULT '{}'::text[] NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    status public.identifier_status DEFAULT 'pending'::public.identifier_status NOT NULL
);


--
-- Name: persons; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.persons (
    id integer NOT NULL,
    last_name text NOT NULL,
    first_name text NOT NULL,
    last_name_normalized text NOT NULL,
    first_name_normalized text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    rejected boolean DEFAULT false
);


--
-- Name: persons_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.persons_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: persons_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.persons_id_seq OWNED BY public.persons.id;


--
-- Name: persons_rh; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.persons_rh (
    id integer NOT NULL,
    person_id integer NOT NULL,
    email text,
    role_title text,
    department_name text,
    structure_id integer,
    start_date date,
    end_date date,
    hr_export_date date,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: persons_rh_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.persons_rh_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: persons_rh_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.persons_rh_id_seq OWNED BY public.persons_rh.id;


--
-- Name: pipeline_run_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pipeline_run_snapshots (
    id integer CONSTRAINT pipeline_check_snapshots_id_not_null NOT NULL,
    ran_at timestamp with time zone DEFAULT now() CONSTRAINT pipeline_check_snapshots_ran_at_not_null NOT NULL,
    mode text CONSTRAINT pipeline_check_snapshots_mode_not_null NOT NULL,
    payload jsonb CONSTRAINT pipeline_check_snapshots_payload_not_null NOT NULL
);


--
-- Name: pipeline_run_snapshots_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pipeline_run_snapshots_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pipeline_run_snapshots_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pipeline_run_snapshots_id_seq OWNED BY public.pipeline_run_snapshots.id;


--
-- Name: place_name_forms; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.place_name_forms (
    id integer CONSTRAINT country_name_forms_id_not_null NOT NULL,
    iso_code text CONSTRAINT country_name_forms_iso_code_not_null NOT NULL,
    form_normalized text CONSTRAINT country_name_forms_form_normalized_not_null NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    kind text DEFAULT 'country'::text NOT NULL,
    CONSTRAINT place_name_forms_kind_check CHECK ((kind = ANY (ARRAY['country'::text, 'institution'::text, 'city'::text])))
);


--
-- Name: place_name_forms_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.place_name_forms_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: place_name_forms_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.place_name_forms_id_seq OWNED BY public.place_name_forms.id;


--
-- Name: publication_relations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.publication_relations (
    from_publication_id integer NOT NULL,
    relation_type public.relation_type NOT NULL,
    target_doi text NOT NULL,
    target_publication_id integer,
    source text NOT NULL
);


--
-- Name: publication_structures; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.publication_structures AS
 SELECT DISTINCT a.publication_id,
    aus.structure_id
   FROM (public.authorships a
     JOIN public.authorship_structures aus ON ((aus.authorship_id = a.id)))
  WITH NO DATA;


--
-- Name: publication_subjects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.publication_subjects (
    publication_id integer NOT NULL,
    subject_id integer NOT NULL,
    source public.source_type NOT NULL,
    score real,
    created_at timestamp with time zone DEFAULT now(),
    rejected boolean DEFAULT false NOT NULL
);


--
-- Name: publications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.publications (
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
    in_perimeter boolean DEFAULT false NOT NULL,
    unpaywall_checked_at timestamp with time zone
);


--
-- Name: publications_detail; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.publications_detail (
    publication_id integer NOT NULL,
    abstract text,
    keywords text[],
    topics jsonb,
    biblio jsonb
);


--
-- Name: publications_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.publications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: publications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.publications_id_seq OWNED BY public.publications.id;


--
-- Name: publisher_name_forms; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.publisher_name_forms (
    id integer NOT NULL,
    publisher_id integer NOT NULL,
    form_normalized text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: publisher_name_forms_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.publisher_name_forms_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: publisher_name_forms_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.publisher_name_forms_id_seq OWNED BY public.publisher_name_forms.id;


--
-- Name: publishers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.publishers (
    id integer NOT NULL,
    name text NOT NULL,
    name_normalized text NOT NULL,
    openalex_id text,
    country text,
    is_predatory boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    publisher_type public.publisher_type DEFAULT 'unknown'::public.publisher_type NOT NULL,
    ror text,
    pub_count integer DEFAULT 0 NOT NULL
);


--
-- Name: publishers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.publishers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: publishers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.publishers_id_seq OWNED BY public.publishers.id;


--
-- Name: rejected_authorships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rejected_authorships (
    publication_id integer NOT NULL,
    person_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: source_authorship_addresses_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.source_authorship_addresses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_authorship_addresses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.source_authorship_addresses_id_seq OWNED BY public.source_authorship_addresses.id;


--
-- Name: source_authorships_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.source_authorships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_authorships_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.source_authorships_id_seq OWNED BY public.source_authorships.id;


--
-- Name: source_publications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_publications (
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
    cited_by_count integer,
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
    CONSTRAINT source_publications_external_ids_is_object CHECK ((jsonb_typeof(external_ids) = 'object'::text)),
    CONSTRAINT source_publications_raw_metadata_is_object CHECK ((jsonb_typeof(raw_metadata) = 'object'::text))
);


--
-- Name: source_publications_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.source_publications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_publications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.source_publications_id_seq OWNED BY public.source_publications.id;


--
-- Name: staging; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.staging (
    id integer NOT NULL,
    source public.source_type NOT NULL,
    source_id text NOT NULL,
    doi text,
    raw_data jsonb NOT NULL,
    processed boolean DEFAULT false,
    imported_at timestamp with time zone DEFAULT now(),
    raw_hash text,
    last_seen_at timestamp with time zone DEFAULT now(),
    not_found_at timestamp with time zone,
    disappeared_at timestamp with time zone,
    CONSTRAINT staging_not_found_at_implies_processed CHECK (((not_found_at IS NULL) OR processed))
);


--
-- Name: COLUMN staging.raw_hash; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.staging.raw_hash IS 'Empreinte md5 du payload tel qu''extrait de la source bulk. Sert de clé de détection de changement à l''UPSERT (et d''empreinte d''intégrité pour le chantier DATA_raw-data-store). Cas particulier OpenAlex : `refetch_truncated` n''écrit PAS `raw_hash` quand il complète les authorships d''une publication tronquée à 100 — la ligne garde le hash du payload bulk pour que le bulk suivant ne déclenche pas de réécriture inutile. L''invariant `raw_hash = md5(raw_data)` est donc volontairement rompu sur les lignes OpenAlex refetchées.';


--
-- Name: staging_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.staging_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: staging_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.staging_id_seq OWNED BY public.staging.id;


--
-- Name: structure_name_forms; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.structure_name_forms (
    id integer NOT NULL,
    structure_id integer NOT NULL,
    form_text text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    is_word_boundary boolean DEFAULT false NOT NULL,
    requires_context_of integer[],
    is_excluding boolean DEFAULT false NOT NULL
);


--
-- Name: structure_name_forms_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.structure_name_forms_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: structure_name_forms_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.structure_name_forms_id_seq OWNED BY public.structure_name_forms.id;


--
-- Name: structure_relations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.structure_relations (
    id integer NOT NULL,
    parent_id integer NOT NULL,
    child_id integer NOT NULL,
    relation_type text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT structure_relations_no_self_reference CHECK ((parent_id <> child_id))
);


--
-- Name: structure_relations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.structure_relations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: structure_relations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.structure_relations_id_seq OWNED BY public.structure_relations.id;


--
-- Name: structures; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.structures (
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
-- Name: structures_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.structures_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: structures_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.structures_id_seq OWNED BY public.structures.id;


--
-- Name: subject_cooccurrences; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.subject_cooccurrences AS
 SELECT ps1.subject_id AS subject_a_id,
    ps2.subject_id AS subject_b_id,
    (count(DISTINCT ps1.publication_id))::integer AS count
   FROM (public.publication_subjects ps1
     JOIN public.publication_subjects ps2 ON (((ps1.publication_id = ps2.publication_id) AND (ps1.subject_id < ps2.subject_id))))
  WHERE ((NOT ps1.rejected) AND (NOT ps2.rejected))
  GROUP BY ps1.subject_id, ps2.subject_id
 HAVING (count(DISTINCT ps1.publication_id) >= 2)
  WITH NO DATA;


--
-- Name: subjects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.subjects (
    id integer NOT NULL,
    label text NOT NULL,
    language text,
    created_at timestamp with time zone DEFAULT now(),
    usage_count integer DEFAULT 0 NOT NULL,
    ontologies jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: subjects_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.subjects_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: subjects_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.subjects_id_seq OWNED BY public.subjects.id;


--
-- Name: address_structures id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.address_structures ALTER COLUMN id SET DEFAULT nextval('public.address_structures_id_seq'::regclass);


--
-- Name: addresses id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.addresses ALTER COLUMN id SET DEFAULT nextval('public.addresses_id_seq'::regclass);


--
-- Name: apc_payments id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.apc_payments ALTER COLUMN id SET DEFAULT nextval('public.apc_payments_id_seq'::regclass);


--
-- Name: audit_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log ALTER COLUMN id SET DEFAULT nextval('public.audit_log_id_seq'::regclass);


--
-- Name: authorships id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorships ALTER COLUMN id SET DEFAULT nextval('public.authorships_id_seq'::regclass);


--
-- Name: distinct_persons id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distinct_persons ALTER COLUMN id SET DEFAULT nextval('public.distinct_persons_id_seq'::regclass);


--
-- Name: distinct_publications id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distinct_publications ALTER COLUMN id SET DEFAULT nextval('public.distinct_publications_id_seq'::regclass);


--
-- Name: journal_name_forms id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_name_forms ALTER COLUMN id SET DEFAULT nextval('public.journal_name_forms_id_seq'::regclass);


--
-- Name: journals id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journals ALTER COLUMN id SET DEFAULT nextval('public.journals_id_seq'::regclass);


--
-- Name: perimeters id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.perimeters ALTER COLUMN id SET DEFAULT nextval('public.perimeters_id_seq'::regclass);


--
-- Name: person_identifiers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_identifiers ALTER COLUMN id SET DEFAULT nextval('public.person_identifiers_id_seq'::regclass);


--
-- Name: persons id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persons ALTER COLUMN id SET DEFAULT nextval('public.persons_id_seq'::regclass);


--
-- Name: persons_rh id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persons_rh ALTER COLUMN id SET DEFAULT nextval('public.persons_rh_id_seq'::regclass);


--
-- Name: pipeline_run_snapshots id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_run_snapshots ALTER COLUMN id SET DEFAULT nextval('public.pipeline_run_snapshots_id_seq'::regclass);


--
-- Name: place_name_forms id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.place_name_forms ALTER COLUMN id SET DEFAULT nextval('public.place_name_forms_id_seq'::regclass);


--
-- Name: publications id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publications ALTER COLUMN id SET DEFAULT nextval('public.publications_id_seq'::regclass);


--
-- Name: publisher_name_forms id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publisher_name_forms ALTER COLUMN id SET DEFAULT nextval('public.publisher_name_forms_id_seq'::regclass);


--
-- Name: publishers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publishers ALTER COLUMN id SET DEFAULT nextval('public.publishers_id_seq'::regclass);


--
-- Name: source_authorship_addresses id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_authorship_addresses ALTER COLUMN id SET DEFAULT nextval('public.source_authorship_addresses_id_seq'::regclass);


--
-- Name: source_authorships id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_authorships ALTER COLUMN id SET DEFAULT nextval('public.source_authorships_id_seq'::regclass);


--
-- Name: source_publications id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_publications ALTER COLUMN id SET DEFAULT nextval('public.source_publications_id_seq'::regclass);


--
-- Name: staging id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staging ALTER COLUMN id SET DEFAULT nextval('public.staging_id_seq'::regclass);


--
-- Name: structure_name_forms id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structure_name_forms ALTER COLUMN id SET DEFAULT nextval('public.structure_name_forms_id_seq'::regclass);


--
-- Name: structure_relations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structure_relations ALTER COLUMN id SET DEFAULT nextval('public.structure_relations_id_seq'::regclass);


--
-- Name: structures id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structures ALTER COLUMN id SET DEFAULT nextval('public.structures_id_seq'::regclass);


--
-- Name: subjects id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subjects ALTER COLUMN id SET DEFAULT nextval('public.subjects_id_seq'::regclass);


--
-- Name: address_structures address_structures_address_id_structure_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.address_structures
    ADD CONSTRAINT address_structures_address_id_structure_id_key UNIQUE (address_id, structure_id);


--
-- Name: address_structures address_structures_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.address_structures
    ADD CONSTRAINT address_structures_pkey PRIMARY KEY (id);


--
-- Name: addresses addresses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.addresses
    ADD CONSTRAINT addresses_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: apc_payments apc_payments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.apc_payments
    ADD CONSTRAINT apc_payments_pkey PRIMARY KEY (id);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: authorships authorships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorships
    ADD CONSTRAINT authorships_pkey PRIMARY KEY (id);


--
-- Name: authorships authorships_publication_person_uq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorships
    ADD CONSTRAINT authorships_publication_person_uq UNIQUE (publication_id, person_id);


--
-- Name: config config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config
    ADD CONSTRAINT config_pkey PRIMARY KEY (key);


--
-- Name: countries countries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.countries
    ADD CONSTRAINT countries_pkey PRIMARY KEY (code);


--
-- Name: distinct_persons distinct_persons_person_id_a_person_id_b_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distinct_persons
    ADD CONSTRAINT distinct_persons_person_id_a_person_id_b_key UNIQUE (person_id_a, person_id_b);


--
-- Name: distinct_persons distinct_persons_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distinct_persons
    ADD CONSTRAINT distinct_persons_pkey PRIMARY KEY (id);


--
-- Name: distinct_publications distinct_publications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distinct_publications
    ADD CONSTRAINT distinct_publications_pkey PRIMARY KEY (id);


--
-- Name: distinct_publications distinct_publications_pub_id_a_pub_id_b_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distinct_publications
    ADD CONSTRAINT distinct_publications_pub_id_a_pub_id_b_key UNIQUE (pub_id_a, pub_id_b);


--
-- Name: doi_lookups doi_lookups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.doi_lookups
    ADD CONSTRAINT doi_lookups_pkey PRIMARY KEY (source, doi);


--
-- Name: doi_prefixes doi_prefixes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.doi_prefixes
    ADD CONSTRAINT doi_prefixes_pkey PRIMARY KEY (prefix);


--
-- Name: journal_name_forms journal_name_forms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_name_forms
    ADD CONSTRAINT journal_name_forms_pkey PRIMARY KEY (id);


--
-- Name: journals journals_openalex_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journals
    ADD CONSTRAINT journals_openalex_id_key UNIQUE (openalex_id);


--
-- Name: journals journals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journals
    ADD CONSTRAINT journals_pkey PRIMARY KEY (id);


--
-- Name: perimeter_structures perimeter_structures_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.perimeter_structures
    ADD CONSTRAINT perimeter_structures_pkey PRIMARY KEY (perimeter_id, structure_id);


--
-- Name: perimeters perimeters_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.perimeters
    ADD CONSTRAINT perimeters_code_key UNIQUE (code);


--
-- Name: perimeters perimeters_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.perimeters
    ADD CONSTRAINT perimeters_pkey PRIMARY KEY (id);


--
-- Name: person_identifiers person_identifiers_id_type_id_value_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_identifiers
    ADD CONSTRAINT person_identifiers_id_type_id_value_key UNIQUE (id_type, id_value);


--
-- Name: person_identifiers person_identifiers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_identifiers
    ADD CONSTRAINT person_identifiers_pkey PRIMARY KEY (id);


--
-- Name: person_name_forms person_name_forms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_name_forms
    ADD CONSTRAINT person_name_forms_pkey PRIMARY KEY (name_form, person_id);


--
-- Name: persons persons_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persons
    ADD CONSTRAINT persons_pkey PRIMARY KEY (id);


--
-- Name: persons_rh persons_rh_person_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persons_rh
    ADD CONSTRAINT persons_rh_person_id_key UNIQUE (person_id);


--
-- Name: persons_rh persons_rh_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persons_rh
    ADD CONSTRAINT persons_rh_pkey PRIMARY KEY (id);


--
-- Name: pipeline_run_snapshots pipeline_check_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_run_snapshots
    ADD CONSTRAINT pipeline_check_snapshots_pkey PRIMARY KEY (id);


--
-- Name: place_name_forms place_name_forms_form_normalized_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.place_name_forms
    ADD CONSTRAINT place_name_forms_form_normalized_key UNIQUE (form_normalized);


--
-- Name: place_name_forms place_name_forms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.place_name_forms
    ADD CONSTRAINT place_name_forms_pkey PRIMARY KEY (id);


--
-- Name: publication_relations publication_relations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publication_relations
    ADD CONSTRAINT publication_relations_pkey PRIMARY KEY (from_publication_id, relation_type, target_doi);


--
-- Name: publication_subjects publication_subjects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publication_subjects
    ADD CONSTRAINT publication_subjects_pkey PRIMARY KEY (publication_id, subject_id, source);


--
-- Name: publications_detail publications_detail_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publications_detail
    ADD CONSTRAINT publications_detail_pkey PRIMARY KEY (publication_id);


--
-- Name: publications publications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publications
    ADD CONSTRAINT publications_pkey PRIMARY KEY (id);


--
-- Name: publisher_name_forms publisher_name_forms_form_normalized_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publisher_name_forms
    ADD CONSTRAINT publisher_name_forms_form_normalized_key UNIQUE (form_normalized);


--
-- Name: publisher_name_forms publisher_name_forms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publisher_name_forms
    ADD CONSTRAINT publisher_name_forms_pkey PRIMARY KEY (id);


--
-- Name: publishers publishers_openalex_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publishers
    ADD CONSTRAINT publishers_openalex_id_key UNIQUE (openalex_id);


--
-- Name: publishers publishers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publishers
    ADD CONSTRAINT publishers_pkey PRIMARY KEY (id);


--
-- Name: rejected_authorships rejected_authorships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rejected_authorships
    ADD CONSTRAINT rejected_authorships_pkey PRIMARY KEY (publication_id, person_id);


--
-- Name: source_authorship_addresses source_authorship_addresses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_authorship_addresses
    ADD CONSTRAINT source_authorship_addresses_pkey PRIMARY KEY (id);


--
-- Name: source_authorship_addresses source_authorship_addresses_source_authorship_id_address_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_authorship_addresses
    ADD CONSTRAINT source_authorship_addresses_source_authorship_id_address_id_key UNIQUE (source_authorship_id, address_id);


--
-- Name: source_authorships source_authorships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_authorships
    ADD CONSTRAINT source_authorships_pkey PRIMARY KEY (id);


--
-- Name: source_authorships source_authorships_pub_pos_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_authorships
    ADD CONSTRAINT source_authorships_pub_pos_key UNIQUE (source_publication_id, author_position);


--
-- Name: source_publications source_publications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_publications
    ADD CONSTRAINT source_publications_pkey PRIMARY KEY (id);


--
-- Name: source_publications source_publications_source_source_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_publications
    ADD CONSTRAINT source_publications_source_source_id_key UNIQUE (source, source_id);


--
-- Name: staging staging_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staging
    ADD CONSTRAINT staging_pkey PRIMARY KEY (id);


--
-- Name: staging staging_source_source_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.staging
    ADD CONSTRAINT staging_source_source_id_key UNIQUE (source, source_id);


--
-- Name: structure_name_forms structure_name_forms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structure_name_forms
    ADD CONSTRAINT structure_name_forms_pkey PRIMARY KEY (id);


--
-- Name: structure_relations structure_relations_parent_id_child_id_relation_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structure_relations
    ADD CONSTRAINT structure_relations_parent_id_child_id_relation_type_key UNIQUE (parent_id, child_id, relation_type);


--
-- Name: structure_relations structure_relations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structure_relations
    ADD CONSTRAINT structure_relations_pkey PRIMARY KEY (id);


--
-- Name: structures structures_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structures
    ADD CONSTRAINT structures_code_key UNIQUE (code);


--
-- Name: structures structures_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structures
    ADD CONSTRAINT structures_pkey PRIMARY KEY (id);


--
-- Name: subjects subjects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.subjects
    ADD CONSTRAINT subjects_pkey PRIMARY KEY (id);


--
-- Name: journal_name_forms uq_jnl_nf_form_publisher; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_name_forms
    ADD CONSTRAINT uq_jnl_nf_form_publisher UNIQUE (form_normalized, publisher_id);


--
-- Name: structure_name_forms uq_snf_structure_form; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structure_name_forms
    ADD CONSTRAINT uq_snf_structure_form UNIQUE (structure_id, form_text);


--
-- Name: addresses_raw_text_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX addresses_raw_text_key ON public.addresses USING btree (md5(raw_text));


--
-- Name: audit_log_aggregate_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_log_aggregate_idx ON public.audit_log USING btree (aggregate_type, aggregate_id);


--
-- Name: audit_log_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_log_created_at_idx ON public.audit_log USING btree (created_at DESC);


--
-- Name: audit_log_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_log_event_type_idx ON public.audit_log USING btree (event_type, created_at DESC);


--
-- Name: authorship_structures_pkey; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX authorship_structures_pkey ON public.authorship_structures USING btree (authorship_id, structure_id);


--
-- Name: idx_addr_struct_address; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_addr_struct_address ON public.address_structures USING btree (address_id);


--
-- Name: idx_addr_struct_filter; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_addr_struct_filter ON public.address_structures USING btree (structure_id, address_id) INCLUDE (matched_form_id, is_confirmed);


--
-- Name: idx_addr_struct_structure; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_addr_struct_structure ON public.address_structures USING btree (structure_id);


--
-- Name: idx_addr_sug_countries; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_addr_sug_countries ON public.addresses USING gin (suggested_countries) WHERE (suggested_countries IS NOT NULL);


--
-- Name: idx_addresses_countries; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_addresses_countries ON public.addresses USING gin (countries) WHERE (countries IS NOT NULL);


--
-- Name: idx_addresses_countries_dirty; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_addresses_countries_dirty ON public.addresses USING btree (id) WHERE countries_dirty;


--
-- Name: idx_addresses_normalized_text; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_addresses_normalized_text ON public.addresses USING btree (normalized_text);


--
-- Name: idx_addresses_normalized_text_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_addresses_normalized_text_trgm ON public.addresses USING gin (normalized_text public.gin_trgm_ops);


--
-- Name: idx_apc_billing_year; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_apc_billing_year ON public.apc_payments USING btree (billing_year);


--
-- Name: idx_apc_budget_struct; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_apc_budget_struct ON public.apc_payments USING btree (budget_structure_id) WHERE (budget_structure_id IS NOT NULL);


--
-- Name: idx_apc_doi; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_apc_doi ON public.apc_payments USING btree (lower(doi)) WHERE (doi IS NOT NULL);


--
-- Name: idx_apc_institution; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_apc_institution ON public.apc_payments USING btree (institution);


--
-- Name: idx_apc_lab_struct; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_apc_lab_struct ON public.apc_payments USING btree (lab_structure_id) WHERE (lab_structure_id IS NOT NULL);


--
-- Name: idx_apc_pub; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_apc_pub ON public.apc_payments USING btree (publication_id) WHERE (publication_id IS NOT NULL);


--
-- Name: idx_authorship_structures_structure_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorship_structures_structure_id ON public.authorship_structures USING btree (structure_id);


--
-- Name: idx_authorships_corresponding_uca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorships_corresponding_uca ON public.authorships USING btree (publication_id) WHERE ((is_corresponding = true) AND (in_perimeter = true));


--
-- Name: idx_authorships_person; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorships_person ON public.authorships USING btree (person_id) WHERE (person_id IS NOT NULL);


--
-- Name: idx_authorships_pub; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorships_pub ON public.authorships USING btree (publication_id);


--
-- Name: idx_authorships_pub_uca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorships_pub_uca ON public.authorships USING btree (publication_id) WHERE (in_perimeter = true);


--
-- Name: idx_authorships_uca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorships_uca ON public.authorships USING btree (in_perimeter) WHERE (in_perimeter = true);


--
-- Name: idx_distinct_pubs_a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_distinct_pubs_a ON public.distinct_publications USING btree (pub_id_a);


--
-- Name: idx_distinct_pubs_b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_distinct_pubs_b ON public.distinct_publications USING btree (pub_id_b);


--
-- Name: idx_doi_prefixes_client_name_normalized; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_doi_prefixes_client_name_normalized ON public.doi_prefixes USING btree (client_name_normalized) WHERE (client_name_normalized IS NOT NULL);


--
-- Name: idx_doi_prefixes_datacite_client_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_doi_prefixes_datacite_client_symbol ON public.doi_prefixes USING btree (datacite_client_symbol) WHERE (datacite_client_symbol IS NOT NULL);


--
-- Name: idx_doi_prefixes_publisher; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_doi_prefixes_publisher ON public.doi_prefixes USING btree (publisher_id) WHERE (publisher_id IS NOT NULL);


--
-- Name: idx_doi_prefixes_publisher_name_normalized; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_doi_prefixes_publisher_name_normalized ON public.doi_prefixes USING btree (publisher_name_normalized) WHERE (publisher_id IS NULL);


--
-- Name: idx_doi_prefixes_ra; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_doi_prefixes_ra ON public.doi_prefixes USING btree (ra);


--
-- Name: idx_jnl_nf_journal; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jnl_nf_journal ON public.journal_name_forms USING btree (journal_id);


--
-- Name: idx_journals_doi_prefix; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_journals_doi_prefix ON public.journals USING btree (doi_prefix) WHERE (doi_prefix IS NOT NULL);


--
-- Name: idx_journals_eissn; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_journals_eissn ON public.journals USING btree (eissn);


--
-- Name: idx_journals_issn; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_journals_issn ON public.journals USING btree (issn);


--
-- Name: idx_journals_issnl; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_journals_issnl ON public.journals USING btree (issnl);


--
-- Name: idx_journals_publisher; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_journals_publisher ON public.journals USING btree (publisher_id);


--
-- Name: idx_journals_titlenorm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_journals_titlenorm ON public.journals USING btree (title_normalized);


--
-- Name: idx_person_ids_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_person_ids_lookup ON public.person_identifiers USING btree (id_type, id_value);


--
-- Name: idx_person_ids_person; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_person_ids_person ON public.person_identifiers USING btree (person_id);


--
-- Name: idx_persons_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_persons_name ON public.persons USING btree (last_name_normalized, first_name_normalized);


--
-- Name: idx_persons_rh_department; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_persons_rh_department ON public.persons_rh USING btree (department_name);


--
-- Name: idx_persons_rh_person_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_persons_rh_person_id ON public.persons_rh USING btree (person_id);


--
-- Name: idx_pipeline_run_snapshots_mode_ran_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pipeline_run_snapshots_mode_ran_at ON public.pipeline_run_snapshots USING btree (mode, ran_at DESC);


--
-- Name: idx_pnf_iso; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pnf_iso ON public.place_name_forms USING btree (iso_code);


--
-- Name: idx_pnf_person_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pnf_person_id ON public.person_name_forms USING btree (person_id);


--
-- Name: idx_ps_structure_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ps_structure_id ON public.perimeter_structures USING btree (structure_id);


--
-- Name: idx_pub_countries; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pub_countries ON public.publications USING gin (countries) WHERE (countries IS NOT NULL);


--
-- Name: idx_pub_nf_publisher; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pub_nf_publisher ON public.publisher_name_forms USING btree (publisher_id);


--
-- Name: idx_pub_title_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pub_title_trgm ON public.publications USING gin (title_normalized public.gin_trgm_ops);


--
-- Name: idx_pub_unpaywall_checked; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pub_unpaywall_checked ON public.publications USING btree (unpaywall_checked_at NULLS FIRST) WHERE (doi IS NOT NULL);


--
-- Name: idx_publication_relations_target_doi; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publication_relations_target_doi ON public.publication_relations USING btree (target_doi);


--
-- Name: idx_publication_relations_target_pub; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publication_relations_target_pub ON public.publication_relations USING btree (target_publication_id) WHERE (target_publication_id IS NOT NULL);


--
-- Name: idx_publication_structures_structure; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publication_structures_structure ON public.publication_structures USING btree (structure_id);


--
-- Name: idx_publications_in_perimeter_journal; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publications_in_perimeter_journal ON public.publications USING btree (journal_id) WHERE in_perimeter;


--
-- Name: idx_publications_in_perimeter_year; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publications_in_perimeter_year ON public.publications USING btree (pub_year DESC) WHERE in_perimeter;


--
-- Name: idx_publications_journal; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publications_journal ON public.publications USING btree (journal_id);


--
-- Name: idx_publications_meta; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publications_meta ON public.publications USING gin (meta) WHERE (meta IS NOT NULL);


--
-- Name: idx_publications_sources; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publications_sources ON public.publications USING gin (sources);


--
-- Name: idx_publications_titlenorm_year; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publications_titlenorm_year ON public.publications USING btree (title_normalized, pub_year);


--
-- Name: idx_publications_year; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publications_year ON public.publications USING btree (pub_year);


--
-- Name: idx_publications_year_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publications_year_type ON public.publications USING btree (pub_year, doc_type);


--
-- Name: idx_publishers_name_norm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publishers_name_norm ON public.publishers USING btree (name_normalized);


--
-- Name: idx_publishers_name_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publishers_name_trgm ON public.publishers USING gin (name public.gin_trgm_ops);


--
-- Name: idx_sa_authorship; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sa_authorship ON public.source_authorships USING btree (authorship_id) WHERE (authorship_id IS NOT NULL);


--
-- Name: idx_sa_countries_dirty; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sa_countries_dirty ON public.source_authorships USING btree (source) WHERE countries_dirty;


--
-- Name: idx_sa_in_perimeter; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sa_in_perimeter ON public.source_authorships USING btree (source_publication_id) WHERE (in_perimeter = true);


--
-- Name: idx_sa_person; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_sa_person ON public.source_authorships USING btree (person_id) WHERE (person_id IS NOT NULL);


--
-- Name: idx_saa_address; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_saa_address ON public.source_authorship_addresses USING btree (address_id);


--
-- Name: idx_source_authorship_structures_structure_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_authorship_structures_structure_id ON public.source_authorship_structures USING btree (structure_id);


--
-- Name: idx_source_pubs_countries; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_pubs_countries ON public.source_publications USING gin (countries) WHERE (countries IS NOT NULL);


--
-- Name: idx_source_pubs_doi; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_pubs_doi ON public.source_publications USING btree (doi) WHERE (doi IS NOT NULL);


--
-- Name: idx_source_pubs_external_ids; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_pubs_external_ids ON public.source_publications USING gin (external_ids) WHERE (external_ids <> '{}'::jsonb);


--
-- Name: idx_source_pubs_hal_collections; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_pubs_hal_collections ON public.source_publications USING gin (hal_collections) WHERE (hal_collections IS NOT NULL);


--
-- Name: idx_source_pubs_hal_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_pubs_hal_id ON public.source_publications USING gin (((external_ids -> 'hal_id'::text)));


--
-- Name: idx_source_pubs_keys_dirty; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_pubs_keys_dirty ON public.source_publications USING btree (keys_dirty) WHERE keys_dirty;


--
-- Name: idx_source_pubs_metadata_block; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_pubs_metadata_block ON public.source_publications USING btree (title_normalized, pub_year, doc_type);


--
-- Name: idx_source_pubs_nnt; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_pubs_nnt ON public.source_publications USING btree (((external_ids ->> 'nnt'::text))) WHERE ((external_ids ->> 'nnt'::text) IS NOT NULL);


--
-- Name: idx_source_pubs_pmid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_pubs_pmid ON public.source_publications USING btree (((external_ids ->> 'pmid'::text))) WHERE ((external_ids ->> 'pmid'::text) IS NOT NULL);


--
-- Name: idx_source_pubs_pub; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_pubs_pub ON public.source_publications USING btree (publication_id) WHERE (publication_id IS NOT NULL);


--
-- Name: idx_source_pubs_staging; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_pubs_staging ON public.source_publications USING btree (staging_id) WHERE (staging_id IS NOT NULL);


--
-- Name: idx_source_pubs_title_normalized_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_pubs_title_normalized_trgm ON public.source_publications USING gin (title_normalized public.gin_trgm_ops);


--
-- Name: idx_staging_doi; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_staging_doi ON public.staging USING btree (doi) WHERE (doi IS NOT NULL);


--
-- Name: idx_staging_processed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_staging_processed ON public.staging USING btree (processed) WHERE (NOT processed);


--
-- Name: idx_staging_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_staging_source ON public.staging USING btree (source);


--
-- Name: idx_struct_rel_child; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_struct_rel_child ON public.structure_relations USING btree (child_id);


--
-- Name: idx_struct_rel_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_struct_rel_parent ON public.structure_relations USING btree (parent_id);


--
-- Name: idx_structure_name_forms_structure; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_structure_name_forms_structure ON public.structure_name_forms USING btree (structure_id);


--
-- Name: idx_structures_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_structures_type ON public.structures USING btree (structure_type);


--
-- Name: idx_subjects_oa_label_lower; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_subjects_oa_label_lower ON public.subjects USING btree (lower(label)) WHERE (ontologies ? 'openalex_topic'::text);


--
-- Name: publication_structures_pub_struct; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX publication_structures_pub_struct ON public.publication_structures USING btree (publication_id, structure_id);


--
-- Name: publication_subjects_subject_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX publication_subjects_subject_idx ON public.publication_subjects USING btree (subject_id);


--
-- Name: publications_doi_lower_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX publications_doi_lower_key ON public.publications USING btree (lower(doi)) WHERE (doi IS NOT NULL);


--
-- Name: source_authorship_structures_pkey; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX source_authorship_structures_pkey ON public.source_authorship_structures USING btree (source_authorship_id, structure_id);


--
-- Name: subject_cooccurrences_b_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX subject_cooccurrences_b_idx ON public.subject_cooccurrences USING btree (subject_b_id);


--
-- Name: subject_cooccurrences_count_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX subject_cooccurrences_count_idx ON public.subject_cooccurrences USING btree (count DESC);


--
-- Name: subject_cooccurrences_pkey; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX subject_cooccurrences_pkey ON public.subject_cooccurrences USING btree (subject_a_id, subject_b_id);


--
-- Name: subjects_label_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX subjects_label_key ON public.subjects USING btree (lower(label));


--
-- Name: subjects_label_norm_trgm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX subjects_label_norm_trgm_idx ON public.subjects USING gin (public.normalize_name_form(label) public.gin_trgm_ops);


--
-- Name: subjects_usage_count_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX subjects_usage_count_idx ON public.subjects USING btree (usage_count DESC);


--
-- Name: address_structures address_structures_address_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.address_structures
    ADD CONSTRAINT address_structures_address_id_fkey FOREIGN KEY (address_id) REFERENCES public.addresses(id) ON DELETE CASCADE;


--
-- Name: address_structures address_structures_matched_form_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.address_structures
    ADD CONSTRAINT address_structures_matched_form_id_fkey FOREIGN KEY (matched_form_id) REFERENCES public.structure_name_forms(id) ON DELETE SET NULL;


--
-- Name: address_structures address_structures_structure_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.address_structures
    ADD CONSTRAINT address_structures_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES public.structures(id) ON DELETE CASCADE;


--
-- Name: apc_payments apc_payments_budget_structure_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.apc_payments
    ADD CONSTRAINT apc_payments_budget_structure_id_fkey FOREIGN KEY (budget_structure_id) REFERENCES public.structures(id) ON DELETE SET NULL;


--
-- Name: apc_payments apc_payments_journal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.apc_payments
    ADD CONSTRAINT apc_payments_journal_id_fkey FOREIGN KEY (journal_id) REFERENCES public.journals(id) ON DELETE SET NULL;


--
-- Name: apc_payments apc_payments_lab_structure_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.apc_payments
    ADD CONSTRAINT apc_payments_lab_structure_id_fkey FOREIGN KEY (lab_structure_id) REFERENCES public.structures(id) ON DELETE SET NULL;


--
-- Name: apc_payments apc_payments_publication_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.apc_payments
    ADD CONSTRAINT apc_payments_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES public.publications(id) ON DELETE SET NULL;


--
-- Name: apc_payments apc_payments_publisher_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.apc_payments
    ADD CONSTRAINT apc_payments_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES public.publishers(id) ON DELETE SET NULL;


--
-- Name: authorships authorships_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorships
    ADD CONSTRAINT authorships_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.persons(id) ON DELETE SET NULL;


--
-- Name: authorships authorships_publication_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorships
    ADD CONSTRAINT authorships_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES public.publications(id) ON DELETE CASCADE;


--
-- Name: distinct_persons distinct_persons_person_id_a_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distinct_persons
    ADD CONSTRAINT distinct_persons_person_id_a_fkey FOREIGN KEY (person_id_a) REFERENCES public.persons(id) ON DELETE CASCADE;


--
-- Name: distinct_persons distinct_persons_person_id_b_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distinct_persons
    ADD CONSTRAINT distinct_persons_person_id_b_fkey FOREIGN KEY (person_id_b) REFERENCES public.persons(id) ON DELETE CASCADE;


--
-- Name: distinct_publications distinct_publications_pub_id_a_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distinct_publications
    ADD CONSTRAINT distinct_publications_pub_id_a_fkey FOREIGN KEY (pub_id_a) REFERENCES public.publications(id) ON DELETE CASCADE;


--
-- Name: distinct_publications distinct_publications_pub_id_b_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distinct_publications
    ADD CONSTRAINT distinct_publications_pub_id_b_fkey FOREIGN KEY (pub_id_b) REFERENCES public.publications(id) ON DELETE CASCADE;


--
-- Name: doi_prefixes doi_prefixes_publisher_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.doi_prefixes
    ADD CONSTRAINT doi_prefixes_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES public.publishers(id) ON DELETE SET NULL;


--
-- Name: journal_name_forms journal_name_forms_journal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_name_forms
    ADD CONSTRAINT journal_name_forms_journal_id_fkey FOREIGN KEY (journal_id) REFERENCES public.journals(id) ON DELETE CASCADE;


--
-- Name: journal_name_forms journal_name_forms_publisher_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_name_forms
    ADD CONSTRAINT journal_name_forms_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES public.publishers(id);


--
-- Name: journals journals_publisher_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journals
    ADD CONSTRAINT journals_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES public.publishers(id);


--
-- Name: perimeter_structures perimeter_structures_perimeter_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.perimeter_structures
    ADD CONSTRAINT perimeter_structures_perimeter_id_fkey FOREIGN KEY (perimeter_id) REFERENCES public.perimeters(id) ON DELETE CASCADE;


--
-- Name: perimeter_structures perimeter_structures_structure_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.perimeter_structures
    ADD CONSTRAINT perimeter_structures_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES public.structures(id) ON DELETE CASCADE;


--
-- Name: person_identifiers person_identifiers_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_identifiers
    ADD CONSTRAINT person_identifiers_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.persons(id) ON DELETE CASCADE;


--
-- Name: person_name_forms person_name_forms_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_name_forms
    ADD CONSTRAINT person_name_forms_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.persons(id) ON DELETE CASCADE;


--
-- Name: persons_rh persons_rh_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persons_rh
    ADD CONSTRAINT persons_rh_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.persons(id) ON DELETE RESTRICT;


--
-- Name: persons_rh persons_rh_structure_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persons_rh
    ADD CONSTRAINT persons_rh_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES public.structures(id);


--
-- Name: publication_relations publication_relations_from_publication_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publication_relations
    ADD CONSTRAINT publication_relations_from_publication_id_fkey FOREIGN KEY (from_publication_id) REFERENCES public.publications(id) ON DELETE CASCADE;


--
-- Name: publication_relations publication_relations_target_publication_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publication_relations
    ADD CONSTRAINT publication_relations_target_publication_id_fkey FOREIGN KEY (target_publication_id) REFERENCES public.publications(id) ON DELETE SET NULL;


--
-- Name: publication_subjects publication_subjects_publication_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publication_subjects
    ADD CONSTRAINT publication_subjects_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES public.publications(id) ON DELETE CASCADE;


--
-- Name: publication_subjects publication_subjects_subject_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publication_subjects
    ADD CONSTRAINT publication_subjects_subject_id_fkey FOREIGN KEY (subject_id) REFERENCES public.subjects(id) ON DELETE CASCADE;


--
-- Name: publications_detail publications_detail_publication_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publications_detail
    ADD CONSTRAINT publications_detail_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES public.publications(id) ON DELETE CASCADE;


--
-- Name: publications publications_journal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publications
    ADD CONSTRAINT publications_journal_id_fkey FOREIGN KEY (journal_id) REFERENCES public.journals(id);


--
-- Name: publisher_name_forms publisher_name_forms_publisher_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.publisher_name_forms
    ADD CONSTRAINT publisher_name_forms_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES public.publishers(id) ON DELETE CASCADE;


--
-- Name: rejected_authorships rejected_authorships_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rejected_authorships
    ADD CONSTRAINT rejected_authorships_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.persons(id) ON DELETE CASCADE;


--
-- Name: rejected_authorships rejected_authorships_publication_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rejected_authorships
    ADD CONSTRAINT rejected_authorships_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES public.publications(id) ON DELETE CASCADE;


--
-- Name: source_authorship_addresses source_authorship_addresses_address_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_authorship_addresses
    ADD CONSTRAINT source_authorship_addresses_address_id_fkey FOREIGN KEY (address_id) REFERENCES public.addresses(id) ON DELETE CASCADE;


--
-- Name: source_authorship_addresses source_authorship_addresses_source_authorship_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_authorship_addresses
    ADD CONSTRAINT source_authorship_addresses_source_authorship_id_fkey FOREIGN KEY (source_authorship_id) REFERENCES public.source_authorships(id) ON DELETE CASCADE;


--
-- Name: source_authorships source_authorships_authorship_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_authorships
    ADD CONSTRAINT source_authorships_authorship_id_fkey FOREIGN KEY (authorship_id) REFERENCES public.authorships(id) ON DELETE SET NULL;


--
-- Name: source_authorships source_authorships_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_authorships
    ADD CONSTRAINT source_authorships_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.persons(id) ON DELETE SET NULL;


--
-- Name: source_authorships source_authorships_source_publication_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_authorships
    ADD CONSTRAINT source_authorships_source_publication_id_fkey FOREIGN KEY (source_publication_id) REFERENCES public.source_publications(id) ON DELETE CASCADE;


--
-- Name: source_publications source_publications_journal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_publications
    ADD CONSTRAINT source_publications_journal_id_fkey FOREIGN KEY (journal_id) REFERENCES public.journals(id);


--
-- Name: source_publications source_publications_publication_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_publications
    ADD CONSTRAINT source_publications_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES public.publications(id) ON DELETE SET NULL;


--
-- Name: source_publications source_publications_staging_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_publications
    ADD CONSTRAINT source_publications_staging_id_fkey FOREIGN KEY (staging_id) REFERENCES public.staging(id);


--
-- Name: structure_name_forms structure_name_forms_structure_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structure_name_forms
    ADD CONSTRAINT structure_name_forms_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES public.structures(id) ON DELETE CASCADE;


--
-- Name: structure_relations structure_relations_child_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structure_relations
    ADD CONSTRAINT structure_relations_child_id_fkey FOREIGN KEY (child_id) REFERENCES public.structures(id) ON DELETE CASCADE;


--
-- Name: structure_relations structure_relations_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structure_relations
    ADD CONSTRAINT structure_relations_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.structures(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict kZ778K8DdBfSH5h6fUrVfnfzm24Znof1Pp488rglJjJ8AqtWeaPqgrHNCBdEANu

