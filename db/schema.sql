--
-- PostgreSQL database dump
--

\restrict 0ine58ZG8V6UOyW7Eb9A1hjkTdmyPjCaYkkIYc0srG2sMLT0c7lqJmkAMWbwucm

-- Dumped from database version 18.3 (Ubuntu 18.3-1.pgdg22.04+1)
-- Dumped by pg_dump version 18.3 (Ubuntu 18.3-1.pgdg22.04+1)

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
    'retraction'
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
-- Name: oa_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.oa_type AS ENUM (
    'gold',
    'hybrid',
    'bronze',
    'green',
    'closed',
    'unknown',
    'diamond'
);


--
-- Name: source_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.source_type AS ENUM (
    'hal',
    'openalex',
    'wos',
    'scanr'
);


--
-- Name: structure_type; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.structure_type AS ENUM (
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


--
-- Name: normalize_name_form(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.normalize_name_form(text) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT
    AS $_$
  SELECT trim(regexp_replace(unaccent(lower(trim($1))), '[^a-z0-9]+', ' ', 'g'));
$_$;


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
    normalized_text text CONSTRAINT addresses_raw_text_normalized_not_null NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    country text,
    pub_count integer DEFAULT 0,
    countries character(2)[],
    suggested_countries character(2)[]
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
-- Name: authorships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.authorships (
    id integer NOT NULL,
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
    wos_authorship_id integer,
    scanr_authorship_id integer
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
-- Name: config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.config (
    key text NOT NULL,
    value jsonb NOT NULL,
    description text,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: countries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.countries (
    code character(2) NOT NULL,
    name text NOT NULL
);


--
-- Name: country_name_forms; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.country_name_forms (
    id integer NOT NULL,
    iso_code text NOT NULL,
    form_normalized text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: country_name_forms_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.country_name_forms_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: country_name_forms_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.country_name_forms_id_seq OWNED BY public.country_name_forms.id;


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
-- Name: hal_authorships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hal_authorships (
    id integer NOT NULL,
    author_position smallint,
    hal_struct_ids integer[],
    is_uca boolean DEFAULT false,
    excluded boolean DEFAULT false,
    structure_ids integer[],
    countries text[],
    person_id integer,
    author_name_normalized text,
    is_corresponding boolean DEFAULT false,
    source_document_id integer NOT NULL,
    roles text[],
    source_author_id integer NOT NULL
);


--
-- Name: hal_authorships_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.hal_authorships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: hal_authorships_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.hal_authorships_id_seq OWNED BY public.hal_authorships.id;


--
-- Name: hal_structures; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hal_structures (
    hal_struct_id integer NOT NULL,
    name text,
    acronym text,
    type text,
    parent_ids integer[],
    structure_id integer,
    doc_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now(),
    start_date date,
    end_date date,
    valid text,
    code text,
    country text,
    enriched_at timestamp with time zone,
    id integer NOT NULL
);


--
-- Name: hal_structures_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.hal_structures_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: hal_structures_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.hal_structures_id_seq OWNED BY public.hal_structures.id;


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
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
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
-- Name: openalex_authorship_addresses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openalex_authorship_addresses (
    id integer NOT NULL,
    openalex_authorship_id integer NOT NULL,
    address_id integer NOT NULL
);


--
-- Name: openalex_authorship_addresses_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.openalex_authorship_addresses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: openalex_authorship_addresses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.openalex_authorship_addresses_id_seq OWNED BY public.openalex_authorship_addresses.id;


--
-- Name: openalex_authorships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openalex_authorships (
    id integer NOT NULL,
    author_position smallint,
    raw_affiliation text,
    openalex_institution_ids text[],
    is_uca boolean DEFAULT false,
    excluded boolean DEFAULT false,
    structure_ids integer[],
    raw_author_name text,
    person_id integer,
    countries text[],
    author_name_normalized text,
    is_corresponding boolean DEFAULT false,
    source_document_id integer NOT NULL,
    roles text[],
    source_author_id integer NOT NULL
);


--
-- Name: openalex_authorships_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.openalex_authorships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: openalex_authorships_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.openalex_authorships_id_seq OWNED BY public.openalex_authorships.id;


--
-- Name: openalex_institutions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openalex_institutions (
    id integer NOT NULL,
    openalex_id text NOT NULL,
    name text NOT NULL,
    ror_id text,
    country_code text,
    type text,
    structure_id integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: openalex_institutions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.openalex_institutions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: openalex_institutions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.openalex_institutions_id_seq OWNED BY public.openalex_institutions.id;


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
    source text,
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
    id integer NOT NULL,
    name_form text NOT NULL,
    person_ids integer[] NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    sources text[]
);


--
-- Name: person_name_forms_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.person_name_forms_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: person_name_forms_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.person_name_forms_id_seq OWNED BY public.person_name_forms.id;


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
    updated_at timestamp with time zone DEFAULT now(),
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
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
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
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    countries text[],
    sources public.source_type[] DEFAULT '{}'::public.source_type[] NOT NULL
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
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
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
-- Name: scanr_authorship_addresses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scanr_authorship_addresses (
    id integer NOT NULL,
    scanr_authorship_id integer NOT NULL,
    address_id integer NOT NULL
);


--
-- Name: scanr_authorship_addresses_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scanr_authorship_addresses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scanr_authorship_addresses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scanr_authorship_addresses_id_seq OWNED BY public.scanr_authorship_addresses.id;


--
-- Name: scanr_authorships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scanr_authorships (
    id integer NOT NULL,
    author_position smallint,
    raw_affiliations jsonb,
    affiliation_ids text[],
    detected_countries text[],
    is_uca boolean DEFAULT false,
    excluded boolean DEFAULT false,
    structure_ids integer[],
    countries text[],
    person_id integer,
    author_name_normalized text,
    source_document_id integer NOT NULL,
    roles text[],
    source_author_id integer NOT NULL
);


--
-- Name: scanr_authorships_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scanr_authorships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scanr_authorships_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scanr_authorships_id_seq OWNED BY public.scanr_authorships.id;


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version text NOT NULL,
    applied_at timestamp with time zone DEFAULT now()
);


--
-- Name: source_authors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_authors (
    id integer NOT NULL,
    source text NOT NULL,
    source_id text NOT NULL,
    full_name text NOT NULL,
    last_name text,
    first_name text,
    orcid text,
    idref text,
    person_id integer,
    source_ids jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: source_authors_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.source_authors_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_authors_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.source_authors_id_seq OWNED BY public.source_authors.id;


--
-- Name: source_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.source_documents (
    id integer NOT NULL,
    source text NOT NULL,
    source_id text NOT NULL,
    doi text,
    title text NOT NULL,
    pub_year smallint,
    doc_type text,
    publication_id integer,
    staging_id integer,
    created_at timestamp with time zone DEFAULT now(),
    countries text[],
    collections text[],
    external_ids jsonb
);


--
-- Name: source_documents_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.source_documents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: source_documents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.source_documents_id_seq OWNED BY public.source_documents.id;


--
-- Name: staging; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.staging (
    id integer NOT NULL,
    source text NOT NULL,
    source_id text NOT NULL,
    doi text,
    raw_data jsonb NOT NULL,
    processed boolean DEFAULT false,
    imported_at timestamp with time zone DEFAULT now(),
    raw_hash text,
    last_seen_at timestamp with time zone DEFAULT now(),
    meta_hash text,
    collection text
);


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
    id integer CONSTRAINT name_forms_id_not_null NOT NULL,
    structure_id integer CONSTRAINT name_forms_structure_id_not_null NOT NULL,
    form_text text CONSTRAINT name_forms_form_text_not_null NOT NULL,
    requires_context_of jsonb,
    is_active boolean DEFAULT true,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    is_word_boundary boolean DEFAULT false NOT NULL
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
    relation_type text NOT NULL
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
    created_at timestamp with time zone DEFAULT now()
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
-- Name: v_active_publications; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.v_active_publications AS
 SELECT id
   FROM public.publications
  WHERE (doc_type <> 'peer_review'::public.doc_type);


--
-- Name: wos_authorship_addresses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wos_authorship_addresses (
    id integer NOT NULL,
    wos_authorship_id integer NOT NULL,
    address_id integer NOT NULL
);


--
-- Name: wos_authorship_addresses_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.wos_authorship_addresses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: wos_authorship_addresses_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.wos_authorship_addresses_id_seq OWNED BY public.wos_authorship_addresses.id;


--
-- Name: wos_authorships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wos_authorships (
    id integer NOT NULL,
    author_position smallint,
    is_corresponding boolean DEFAULT false,
    raw_affiliation text,
    is_uca boolean DEFAULT false,
    excluded boolean DEFAULT false,
    structure_ids integer[],
    countries text[],
    person_id integer,
    author_name_normalized text,
    wos_institution_ids integer[],
    source_document_id integer NOT NULL,
    roles text[],
    source_author_id integer NOT NULL
);


--
-- Name: wos_authorships_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.wos_authorships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: wos_authorships_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.wos_authorships_id_seq OWNED BY public.wos_authorships.id;


--
-- Name: wos_organizations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wos_organizations (
    id integer CONSTRAINT wos_institutions_id_not_null NOT NULL,
    name text CONSTRAINT wos_institutions_name_not_null NOT NULL,
    ror_id text,
    country text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: wos_organizations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.wos_organizations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: wos_organizations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.wos_organizations_id_seq OWNED BY public.wos_organizations.id;


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
-- Name: authorships id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorships ALTER COLUMN id SET DEFAULT nextval('public.authorships_id_seq'::regclass);


--
-- Name: country_name_forms id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.country_name_forms ALTER COLUMN id SET DEFAULT nextval('public.country_name_forms_id_seq'::regclass);


--
-- Name: distinct_persons id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distinct_persons ALTER COLUMN id SET DEFAULT nextval('public.distinct_persons_id_seq'::regclass);


--
-- Name: distinct_publications id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.distinct_publications ALTER COLUMN id SET DEFAULT nextval('public.distinct_publications_id_seq'::regclass);


--
-- Name: hal_authorships id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hal_authorships ALTER COLUMN id SET DEFAULT nextval('public.hal_authorships_id_seq'::regclass);


--
-- Name: hal_structures id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hal_structures ALTER COLUMN id SET DEFAULT nextval('public.hal_structures_id_seq'::regclass);


--
-- Name: journal_name_forms id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journal_name_forms ALTER COLUMN id SET DEFAULT nextval('public.journal_name_forms_id_seq'::regclass);


--
-- Name: journals id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.journals ALTER COLUMN id SET DEFAULT nextval('public.journals_id_seq'::regclass);


--
-- Name: openalex_authorship_addresses id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openalex_authorship_addresses ALTER COLUMN id SET DEFAULT nextval('public.openalex_authorship_addresses_id_seq'::regclass);


--
-- Name: openalex_authorships id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openalex_authorships ALTER COLUMN id SET DEFAULT nextval('public.openalex_authorships_id_seq'::regclass);


--
-- Name: openalex_institutions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openalex_institutions ALTER COLUMN id SET DEFAULT nextval('public.openalex_institutions_id_seq'::regclass);


--
-- Name: perimeters id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.perimeters ALTER COLUMN id SET DEFAULT nextval('public.perimeters_id_seq'::regclass);


--
-- Name: person_identifiers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_identifiers ALTER COLUMN id SET DEFAULT nextval('public.person_identifiers_id_seq'::regclass);


--
-- Name: person_name_forms id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_name_forms ALTER COLUMN id SET DEFAULT nextval('public.person_name_forms_id_seq'::regclass);


--
-- Name: persons id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persons ALTER COLUMN id SET DEFAULT nextval('public.persons_id_seq'::regclass);


--
-- Name: persons_rh id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.persons_rh ALTER COLUMN id SET DEFAULT nextval('public.persons_rh_id_seq'::regclass);


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
-- Name: scanr_authorship_addresses id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scanr_authorship_addresses ALTER COLUMN id SET DEFAULT nextval('public.scanr_authorship_addresses_id_seq'::regclass);


--
-- Name: scanr_authorships id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scanr_authorships ALTER COLUMN id SET DEFAULT nextval('public.scanr_authorships_id_seq'::regclass);


--
-- Name: source_authors id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_authors ALTER COLUMN id SET DEFAULT nextval('public.source_authors_id_seq'::regclass);


--
-- Name: source_documents id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_documents ALTER COLUMN id SET DEFAULT nextval('public.source_documents_id_seq'::regclass);


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
-- Name: wos_authorship_addresses id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wos_authorship_addresses ALTER COLUMN id SET DEFAULT nextval('public.wos_authorship_addresses_id_seq'::regclass);


--
-- Name: wos_authorships id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wos_authorships ALTER COLUMN id SET DEFAULT nextval('public.wos_authorships_id_seq'::regclass);


--
-- Name: wos_organizations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wos_organizations ALTER COLUMN id SET DEFAULT nextval('public.wos_organizations_id_seq'::regclass);


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
-- Name: addresses addresses_raw_text_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.addresses
    ADD CONSTRAINT addresses_raw_text_key UNIQUE (raw_text);


--
-- Name: apc_payments apc_payments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.apc_payments
    ADD CONSTRAINT apc_payments_pkey PRIMARY KEY (id);


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
-- Name: country_name_forms country_name_forms_form_normalized_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.country_name_forms
    ADD CONSTRAINT country_name_forms_form_normalized_key UNIQUE (form_normalized);


--
-- Name: country_name_forms country_name_forms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.country_name_forms
    ADD CONSTRAINT country_name_forms_pkey PRIMARY KEY (id);


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
-- Name: hal_authorships hal_authorships_doc_author_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hal_authorships
    ADD CONSTRAINT hal_authorships_doc_author_key UNIQUE (source_document_id, source_author_id);


--
-- Name: hal_authorships hal_authorships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hal_authorships
    ADD CONSTRAINT hal_authorships_pkey PRIMARY KEY (id);


--
-- Name: hal_structures hal_structures_hal_struct_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hal_structures
    ADD CONSTRAINT hal_structures_hal_struct_id_key UNIQUE (hal_struct_id);


--
-- Name: hal_structures hal_structures_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hal_structures
    ADD CONSTRAINT hal_structures_pkey PRIMARY KEY (id);


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
-- Name: structure_name_forms name_forms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structure_name_forms
    ADD CONSTRAINT name_forms_pkey PRIMARY KEY (id);


--
-- Name: openalex_authorship_addresses openalex_authorship_addresses_openalex_authorship_id_addres_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openalex_authorship_addresses
    ADD CONSTRAINT openalex_authorship_addresses_openalex_authorship_id_addres_key UNIQUE (openalex_authorship_id, address_id);


--
-- Name: openalex_authorship_addresses openalex_authorship_addresses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openalex_authorship_addresses
    ADD CONSTRAINT openalex_authorship_addresses_pkey PRIMARY KEY (id);


--
-- Name: openalex_authorships openalex_authorships_doc_author_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openalex_authorships
    ADD CONSTRAINT openalex_authorships_doc_author_key UNIQUE (source_document_id, source_author_id);


--
-- Name: openalex_authorships openalex_authorships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openalex_authorships
    ADD CONSTRAINT openalex_authorships_pkey PRIMARY KEY (id);


--
-- Name: openalex_institutions openalex_institutions_openalex_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openalex_institutions
    ADD CONSTRAINT openalex_institutions_openalex_id_key UNIQUE (openalex_id);


--
-- Name: openalex_institutions openalex_institutions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openalex_institutions
    ADD CONSTRAINT openalex_institutions_pkey PRIMARY KEY (id);


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
-- Name: person_name_forms person_name_forms_name_form_uq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_name_forms
    ADD CONSTRAINT person_name_forms_name_form_uq UNIQUE (name_form);


--
-- Name: person_name_forms person_name_forms_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_name_forms
    ADD CONSTRAINT person_name_forms_pkey PRIMARY KEY (id);


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
-- Name: scanr_authorship_addresses scanr_authorship_addresses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scanr_authorship_addresses
    ADD CONSTRAINT scanr_authorship_addresses_pkey PRIMARY KEY (id);


--
-- Name: scanr_authorship_addresses scanr_authorship_addresses_scanr_authorship_id_address_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scanr_authorship_addresses
    ADD CONSTRAINT scanr_authorship_addresses_scanr_authorship_id_address_id_key UNIQUE (scanr_authorship_id, address_id);


--
-- Name: scanr_authorships scanr_authorships_doc_author_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scanr_authorships
    ADD CONSTRAINT scanr_authorships_doc_author_key UNIQUE (source_document_id, source_author_id);


--
-- Name: scanr_authorships scanr_authorships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scanr_authorships
    ADD CONSTRAINT scanr_authorships_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: source_authors source_authors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_authors
    ADD CONSTRAINT source_authors_pkey PRIMARY KEY (id);


--
-- Name: source_authors source_authors_source_source_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_authors
    ADD CONSTRAINT source_authors_source_source_id_key UNIQUE (source, source_id);


--
-- Name: source_documents source_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_documents
    ADD CONSTRAINT source_documents_pkey PRIMARY KEY (id);


--
-- Name: source_documents source_documents_source_source_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_documents
    ADD CONSTRAINT source_documents_source_source_id_key UNIQUE (source, source_id);


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
-- Name: wos_authorship_addresses wos_authorship_addresses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wos_authorship_addresses
    ADD CONSTRAINT wos_authorship_addresses_pkey PRIMARY KEY (id);


--
-- Name: wos_authorship_addresses wos_authorship_addresses_wos_authorship_id_address_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wos_authorship_addresses
    ADD CONSTRAINT wos_authorship_addresses_wos_authorship_id_address_id_key UNIQUE (wos_authorship_id, address_id);


--
-- Name: wos_authorships wos_authorships_doc_author_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wos_authorships
    ADD CONSTRAINT wos_authorships_doc_author_key UNIQUE (source_document_id, source_author_id);


--
-- Name: wos_authorships wos_authorships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wos_authorships
    ADD CONSTRAINT wos_authorships_pkey PRIMARY KEY (id);


--
-- Name: wos_organizations wos_institutions_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wos_organizations
    ADD CONSTRAINT wos_institutions_name_key UNIQUE (name);


--
-- Name: wos_organizations wos_institutions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wos_organizations
    ADD CONSTRAINT wos_institutions_pkey PRIMARY KEY (id);


--
-- Name: idx_addr_norm_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_addr_norm_trgm ON public.addresses USING gin (normalized_text public.gin_trgm_ops);


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
-- Name: idx_addresses_normalized; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_addresses_normalized ON public.addresses USING btree (normalized_text);


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
-- Name: idx_authorships_corresponding_uca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorships_corresponding_uca ON public.authorships USING btree (publication_id) WHERE ((is_corresponding = true) AND (is_uca = true));


--
-- Name: idx_authorships_hal_as; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorships_hal_as ON public.authorships USING btree (hal_authorship_id) WHERE (hal_authorship_id IS NOT NULL);


--
-- Name: idx_authorships_oa_as; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorships_oa_as ON public.authorships USING btree (openalex_authorship_id) WHERE (openalex_authorship_id IS NOT NULL);


--
-- Name: idx_authorships_person; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorships_person ON public.authorships USING btree (person_id) WHERE (person_id IS NOT NULL);


--
-- Name: idx_authorships_pub; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorships_pub ON public.authorships USING btree (publication_id);


--
-- Name: idx_authorships_scanr; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorships_scanr ON public.authorships USING btree (scanr_authorship_id) WHERE (scanr_authorship_id IS NOT NULL);


--
-- Name: idx_authorships_structs; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorships_structs ON public.authorships USING gin (structure_ids) WHERE (structure_ids IS NOT NULL);


--
-- Name: idx_authorships_uca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorships_uca ON public.authorships USING btree (is_uca) WHERE (is_uca = true);


--
-- Name: idx_authorships_wos_as; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_authorships_wos_as ON public.authorships USING btree (wos_authorship_id) WHERE (wos_authorship_id IS NOT NULL);


--
-- Name: idx_cnf_iso; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cnf_iso ON public.country_name_forms USING btree (iso_code);


--
-- Name: idx_distinct_pubs_a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_distinct_pubs_a ON public.distinct_publications USING btree (pub_id_a);


--
-- Name: idx_distinct_pubs_b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_distinct_pubs_b ON public.distinct_publications USING btree (pub_id_b);


--
-- Name: idx_hal_as_name_norm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hal_as_name_norm ON public.hal_authorships USING btree (author_name_normalized) WHERE (author_name_normalized IS NOT NULL);


--
-- Name: idx_hal_as_person; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hal_as_person ON public.hal_authorships USING btree (person_id) WHERE (person_id IS NOT NULL);


--
-- Name: idx_hal_as_source_author; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hal_as_source_author ON public.hal_authorships USING btree (source_author_id);


--
-- Name: idx_hal_as_source_doc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hal_as_source_doc ON public.hal_authorships USING btree (source_document_id);


--
-- Name: idx_hal_as_source_doc_uca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hal_as_source_doc_uca ON public.hal_authorships USING btree (source_document_id) INCLUDE (structure_ids) WHERE (is_uca = true);


--
-- Name: idx_hal_as_structs; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hal_as_structs ON public.hal_authorships USING gin (structure_ids) WHERE (structure_ids IS NOT NULL);


--
-- Name: idx_hal_as_uca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hal_as_uca ON public.hal_authorships USING btree (is_uca) WHERE (is_uca = true);


--
-- Name: idx_hal_struct_local; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hal_struct_local ON public.hal_structures USING btree (structure_id) WHERE (structure_id IS NOT NULL);


--
-- Name: idx_hal_struct_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hal_struct_name ON public.hal_structures USING btree (lower(name));


--
-- Name: idx_hal_struct_parent_ids; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hal_struct_parent_ids ON public.hal_structures USING gin (parent_ids);


--
-- Name: idx_hal_struct_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hal_struct_type ON public.hal_structures USING btree (type);


--
-- Name: idx_hal_struct_valid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_hal_struct_valid ON public.hal_structures USING btree (valid);


--
-- Name: idx_jnl_nf_journal; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jnl_nf_journal ON public.journal_name_forms USING btree (journal_id);


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
-- Name: idx_oa_as_name_norm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oa_as_name_norm ON public.openalex_authorships USING btree (author_name_normalized) WHERE (author_name_normalized IS NOT NULL);


--
-- Name: idx_oa_as_person; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oa_as_person ON public.openalex_authorships USING btree (person_id) WHERE (person_id IS NOT NULL);


--
-- Name: idx_oa_as_pos_affil; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oa_as_pos_affil ON public.openalex_authorships USING btree (source_document_id, author_position) WHERE ((is_uca = false) AND (raw_affiliation IS NOT NULL) AND (raw_affiliation <> ''::text));


--
-- Name: idx_oa_as_source_author; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oa_as_source_author ON public.openalex_authorships USING btree (source_author_id);


--
-- Name: idx_oa_as_source_doc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oa_as_source_doc ON public.openalex_authorships USING btree (source_document_id);


--
-- Name: idx_oa_as_source_doc_uca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oa_as_source_doc_uca ON public.openalex_authorships USING btree (source_document_id) INCLUDE (structure_ids) WHERE (is_uca = true);


--
-- Name: idx_oa_as_structs; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oa_as_structs ON public.openalex_authorships USING gin (structure_ids) WHERE (structure_ids IS NOT NULL);


--
-- Name: idx_oa_as_uca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oa_as_uca ON public.openalex_authorships USING btree (is_uca) WHERE (is_uca = true);


--
-- Name: idx_oa_inst_ror; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oa_inst_ror ON public.openalex_institutions USING btree (ror_id) WHERE (ror_id IS NOT NULL);


--
-- Name: idx_oa_inst_struct; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oa_inst_struct ON public.openalex_institutions USING btree (structure_id) WHERE (structure_id IS NOT NULL);


--
-- Name: idx_oaa_address; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_oaa_address ON public.openalex_authorship_addresses USING btree (address_id);


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
-- Name: idx_pnf_person_ids; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pnf_person_ids ON public.person_name_forms USING gin (person_ids);


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
-- Name: idx_publications_doi; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publications_doi ON public.publications USING btree (lower(doi)) WHERE (doi IS NOT NULL);


--
-- Name: idx_publications_journal; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publications_journal ON public.publications USING btree (journal_id);


--
-- Name: idx_publications_sources; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publications_sources ON public.publications USING gin (sources);


--
-- Name: idx_publications_title_norm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_publications_title_norm ON public.publications USING btree (title_normalized);


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
-- Name: idx_saa_address; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_saa_address ON public.scanr_authorship_addresses USING btree (address_id);


--
-- Name: idx_scanr_as_name_norm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scanr_as_name_norm ON public.scanr_authorships USING btree (author_name_normalized) WHERE (author_name_normalized IS NOT NULL);


--
-- Name: idx_scanr_as_person; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scanr_as_person ON public.scanr_authorships USING btree (person_id) WHERE (person_id IS NOT NULL);


--
-- Name: idx_scanr_as_source_author; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scanr_as_source_author ON public.scanr_authorships USING btree (source_author_id);


--
-- Name: idx_scanr_as_source_doc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scanr_as_source_doc ON public.scanr_authorships USING btree (source_document_id);


--
-- Name: idx_scanr_as_structs; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scanr_as_structs ON public.scanr_authorships USING gin (structure_ids) WHERE (structure_ids IS NOT NULL);


--
-- Name: idx_scanr_as_uca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scanr_as_uca ON public.scanr_authorships USING btree (is_uca) WHERE (is_uca = true);


--
-- Name: idx_source_authors_idref; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_authors_idref ON public.source_authors USING btree (idref) WHERE (idref IS NOT NULL);


--
-- Name: idx_source_authors_orcid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_authors_orcid ON public.source_authors USING btree (orcid) WHERE (orcid IS NOT NULL);


--
-- Name: idx_source_authors_person; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_authors_person ON public.source_authors USING btree (person_id) WHERE (person_id IS NOT NULL);


--
-- Name: idx_source_authors_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_authors_source ON public.source_authors USING btree (source);


--
-- Name: idx_source_docs_collections; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_docs_collections ON public.source_documents USING gin (collections) WHERE (collections IS NOT NULL);


--
-- Name: idx_source_docs_countries; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_docs_countries ON public.source_documents USING gin (countries) WHERE (countries IS NOT NULL);


--
-- Name: idx_source_docs_doi; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_docs_doi ON public.source_documents USING btree (doi) WHERE (doi IS NOT NULL);


--
-- Name: idx_source_docs_external_ids; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_docs_external_ids ON public.source_documents USING gin (external_ids) WHERE (external_ids IS NOT NULL);


--
-- Name: idx_source_docs_pub; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_docs_pub ON public.source_documents USING btree (publication_id) WHERE (publication_id IS NOT NULL);


--
-- Name: idx_source_docs_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_docs_source ON public.source_documents USING btree (source);


--
-- Name: idx_source_docs_staging; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_source_docs_staging ON public.source_documents USING btree (staging_id) WHERE (staging_id IS NOT NULL);


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
-- Name: idx_structure_name_forms_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_structure_name_forms_active ON public.structure_name_forms USING btree (is_active) WHERE (is_active = true);


--
-- Name: idx_structure_name_forms_structure; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_structure_name_forms_structure ON public.structure_name_forms USING btree (structure_id);


--
-- Name: idx_structures_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_structures_type ON public.structures USING btree (structure_type);


--
-- Name: idx_wos_aa_address; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wos_aa_address ON public.wos_authorship_addresses USING btree (address_id);


--
-- Name: idx_wos_aa_authorship; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wos_aa_authorship ON public.wos_authorship_addresses USING btree (wos_authorship_id);


--
-- Name: idx_wos_as_name_norm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wos_as_name_norm ON public.wos_authorships USING btree (author_name_normalized) WHERE (author_name_normalized IS NOT NULL);


--
-- Name: idx_wos_as_person; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wos_as_person ON public.wos_authorships USING btree (person_id) WHERE (person_id IS NOT NULL);


--
-- Name: idx_wos_as_pos_affil; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wos_as_pos_affil ON public.wos_authorships USING btree (source_document_id, author_position) WHERE ((is_uca = false) AND (raw_affiliation IS NOT NULL) AND (raw_affiliation <> ''::text));


--
-- Name: idx_wos_as_source_author; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wos_as_source_author ON public.wos_authorships USING btree (source_author_id);


--
-- Name: idx_wos_as_source_doc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wos_as_source_doc ON public.wos_authorships USING btree (source_document_id);


--
-- Name: idx_wos_as_source_doc_uca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wos_as_source_doc_uca ON public.wos_authorships USING btree (source_document_id) INCLUDE (structure_ids) WHERE (is_uca = true);


--
-- Name: idx_wos_as_structs; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wos_as_structs ON public.wos_authorships USING gin (structure_ids) WHERE (structure_ids IS NOT NULL);


--
-- Name: idx_wos_as_uca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wos_as_uca ON public.wos_authorships USING btree (is_uca) WHERE (is_uca = true);


--
-- Name: idx_wos_org_ror; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_wos_org_ror ON public.wos_organizations USING btree (ror_id) WHERE (ror_id IS NOT NULL);


--
-- Name: publications_doi_lower_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX publications_doi_lower_key ON public.publications USING btree (lower(doi)) WHERE (doi IS NOT NULL);


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
-- Name: authorships authorships_hal_authorship_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorships
    ADD CONSTRAINT authorships_hal_authorship_id_fkey FOREIGN KEY (hal_authorship_id) REFERENCES public.hal_authorships(id) ON DELETE SET NULL;


--
-- Name: authorships authorships_openalex_authorship_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorships
    ADD CONSTRAINT authorships_openalex_authorship_id_fkey FOREIGN KEY (openalex_authorship_id) REFERENCES public.openalex_authorships(id) ON DELETE SET NULL;


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
-- Name: authorships authorships_scanr_authorship_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorships
    ADD CONSTRAINT authorships_scanr_authorship_id_fkey FOREIGN KEY (scanr_authorship_id) REFERENCES public.scanr_authorships(id) ON DELETE SET NULL;


--
-- Name: authorships authorships_wos_authorship_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.authorships
    ADD CONSTRAINT authorships_wos_authorship_id_fkey FOREIGN KEY (wos_authorship_id) REFERENCES public.wos_authorships(id) ON DELETE SET NULL;


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
-- Name: hal_authorships hal_authorships_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hal_authorships
    ADD CONSTRAINT hal_authorships_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.persons(id) ON DELETE SET NULL;


--
-- Name: hal_authorships hal_authorships_source_author_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hal_authorships
    ADD CONSTRAINT hal_authorships_source_author_id_fkey FOREIGN KEY (source_author_id) REFERENCES public.source_authors(id) ON DELETE CASCADE;


--
-- Name: hal_authorships hal_authorships_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hal_authorships
    ADD CONSTRAINT hal_authorships_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.source_documents(id) ON DELETE CASCADE;


--
-- Name: hal_structures hal_structures_structure_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hal_structures
    ADD CONSTRAINT hal_structures_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES public.structures(id) ON DELETE SET NULL;


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
-- Name: structure_name_forms name_forms_structure_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.structure_name_forms
    ADD CONSTRAINT name_forms_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES public.structures(id) ON DELETE CASCADE;


--
-- Name: openalex_authorship_addresses openalex_authorship_addresses_address_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openalex_authorship_addresses
    ADD CONSTRAINT openalex_authorship_addresses_address_id_fkey FOREIGN KEY (address_id) REFERENCES public.addresses(id) ON DELETE CASCADE;


--
-- Name: openalex_authorship_addresses openalex_authorship_addresses_openalex_authorship_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openalex_authorship_addresses
    ADD CONSTRAINT openalex_authorship_addresses_openalex_authorship_id_fkey FOREIGN KEY (openalex_authorship_id) REFERENCES public.openalex_authorships(id) ON DELETE CASCADE;


--
-- Name: openalex_authorships openalex_authorships_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openalex_authorships
    ADD CONSTRAINT openalex_authorships_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.persons(id) ON DELETE SET NULL;


--
-- Name: openalex_authorships openalex_authorships_source_author_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openalex_authorships
    ADD CONSTRAINT openalex_authorships_source_author_id_fkey FOREIGN KEY (source_author_id) REFERENCES public.source_authors(id) ON DELETE CASCADE;


--
-- Name: openalex_authorships openalex_authorships_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openalex_authorships
    ADD CONSTRAINT openalex_authorships_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.source_documents(id) ON DELETE CASCADE;


--
-- Name: openalex_institutions openalex_institutions_structure_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openalex_institutions
    ADD CONSTRAINT openalex_institutions_structure_id_fkey FOREIGN KEY (structure_id) REFERENCES public.structures(id) ON DELETE SET NULL;


--
-- Name: person_identifiers person_identifiers_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.person_identifiers
    ADD CONSTRAINT person_identifiers_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.persons(id) ON DELETE CASCADE;


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
-- Name: scanr_authorship_addresses scanr_authorship_addresses_address_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scanr_authorship_addresses
    ADD CONSTRAINT scanr_authorship_addresses_address_id_fkey FOREIGN KEY (address_id) REFERENCES public.addresses(id) ON DELETE CASCADE;


--
-- Name: scanr_authorship_addresses scanr_authorship_addresses_scanr_authorship_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scanr_authorship_addresses
    ADD CONSTRAINT scanr_authorship_addresses_scanr_authorship_id_fkey FOREIGN KEY (scanr_authorship_id) REFERENCES public.scanr_authorships(id) ON DELETE CASCADE;


--
-- Name: scanr_authorships scanr_authorships_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scanr_authorships
    ADD CONSTRAINT scanr_authorships_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.persons(id) ON DELETE SET NULL;


--
-- Name: scanr_authorships scanr_authorships_source_author_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scanr_authorships
    ADD CONSTRAINT scanr_authorships_source_author_id_fkey FOREIGN KEY (source_author_id) REFERENCES public.source_authors(id) ON DELETE CASCADE;


--
-- Name: scanr_authorships scanr_authorships_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scanr_authorships
    ADD CONSTRAINT scanr_authorships_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.source_documents(id) ON DELETE CASCADE;


--
-- Name: source_authors source_authors_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_authors
    ADD CONSTRAINT source_authors_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.persons(id) ON DELETE SET NULL;


--
-- Name: source_documents source_documents_publication_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_documents
    ADD CONSTRAINT source_documents_publication_id_fkey FOREIGN KEY (publication_id) REFERENCES public.publications(id) ON DELETE SET NULL;


--
-- Name: source_documents source_documents_staging_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.source_documents
    ADD CONSTRAINT source_documents_staging_id_fkey FOREIGN KEY (staging_id) REFERENCES public.staging(id);


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
-- Name: wos_authorship_addresses wos_authorship_addresses_address_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wos_authorship_addresses
    ADD CONSTRAINT wos_authorship_addresses_address_id_fkey FOREIGN KEY (address_id) REFERENCES public.addresses(id) ON DELETE CASCADE;


--
-- Name: wos_authorship_addresses wos_authorship_addresses_wos_authorship_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wos_authorship_addresses
    ADD CONSTRAINT wos_authorship_addresses_wos_authorship_id_fkey FOREIGN KEY (wos_authorship_id) REFERENCES public.wos_authorships(id) ON DELETE CASCADE;


--
-- Name: wos_authorships wos_authorships_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wos_authorships
    ADD CONSTRAINT wos_authorships_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.persons(id) ON DELETE SET NULL;


--
-- Name: wos_authorships wos_authorships_source_author_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wos_authorships
    ADD CONSTRAINT wos_authorships_source_author_id_fkey FOREIGN KEY (source_author_id) REFERENCES public.source_authors(id) ON DELETE CASCADE;


--
-- Name: wos_authorships wos_authorships_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wos_authorships
    ADD CONSTRAINT wos_authorships_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.source_documents(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict 0ine58ZG8V6UOyW7Eb9A1hjkTdmyPjCaYkkIYc0srG2sMLT0c7lqJmkAMWbwucm

