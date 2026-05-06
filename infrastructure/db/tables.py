"""MetaData SQLAlchemy — description explicite des tables Postgres.

Source de vérité pour SQLAlchemy Core (chantier
docs/chantiers/sqlalchemy-core-adoption.md). Conserve la structure des
tables côté Python pour permettre l'autocomplete IDE et la
construction de requêtes typées (`select(config.c.key)…`).

La vraie source de vérité du schéma reste `infrastructure/db/schema.sql`
(snapshot) et les migrations versionnées dans
`infrastructure/db/migrations/`. À chaque migration affectant l'une
de ces tables, mettre ce module à jour. Un test d'intégration
(`tests/integration/infrastructure/db/test_metadata_consistency.py`)
vérifie la cohérence entre cette MetaData et la DB réelle.

Phase 0 du chantier : seules trois tables pilotes sont décrites
(config, perimeters, structures). Les autres tables seront ajoutées
au fur et à mesure des phases suivantes.
"""

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import ENUM as PgEnum

metadata = MetaData()


audit_log = Table(
    "audit_log",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("event_type", Text, nullable=False),
    Column("aggregate_type", Text, nullable=False),
    Column("aggregate_id", Integer),
    Column("payload", JSONB, nullable=False, server_default="{}"),
    Column("user_id", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)


config = Table(
    "config",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", JSONB, nullable=False),
    Column("description", Text),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)


perimeters = Table(
    "perimeters",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("code", Text, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column(
        "structure_ids",
        ARRAY(Integer),
        nullable=False,
        server_default="{}",
    ),
)


# Enum Postgres `structure_type` — déclaré tel quel côté SA pour que les
# inserts produisent un cast typé (sinon Postgres rejette VARCHAR ↛ enum).
# `create_type=False` : l'enum est créé par les migrations SQL, pas par SA.
structure_type_enum = PgEnum(
    "universite",
    "__epst_deprecated",
    "chu",
    "ecole",
    "labo",
    "equipe",
    "site",
    "autre",
    "onr",
    name="structure_type",
    create_type=False,
)


structures = Table(
    "structures",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("code", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("acronym", Text),
    Column("structure_type", structure_type_enum, nullable=False),
    Column("ror_id", Text),
    Column("rnsr_id", Text),
    Column("hal_collection", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("api_ids", JSONB),
)


structure_relations = Table(
    "structure_relations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("parent_id", Integer, nullable=False),
    Column("child_id", Integer, nullable=False),
    Column("relation_type", Text, nullable=False),
)


structure_name_forms = Table(
    "structure_name_forms",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("structure_id", Integer, nullable=False),
    Column("form_text", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("is_word_boundary", Boolean, nullable=False, server_default="false"),
    Column("requires_context_of", ARRAY(Integer)),
    Column("is_excluding", Boolean, nullable=False, server_default="false"),
)


journals = Table(
    "journals",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("title", Text, nullable=False),
    Column("title_normalized", Text, nullable=False),
    Column("issn", Text),
    Column("eissn", Text),
    Column("issnl", Text),
    Column("publisher_id", Integer),
    Column("openalex_id", Text),
    Column("is_in_doaj", Boolean, server_default="false"),
    Column("is_predatory", Boolean, server_default="false"),
    Column("apc_amount", Numeric(10, 2)),
    Column("apc_currency", Text, server_default="EUR"),
    Column("oa_model", Text),
    Column("notes", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    Column("journal_type", Text, server_default="journal"),
    Column("is_academic", Boolean, server_default="true"),
    Column("doi_prefix", Text),
)


journal_name_forms = Table(
    "journal_name_forms",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("journal_id", Integer, nullable=False),
    Column("form_normalized", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("publisher_id", Integer),
)


publishers = Table(
    "publishers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("name_normalized", Text, nullable=False),
    Column("openalex_id", Text),
    Column("country", Text),
    Column("is_predatory", Boolean, server_default="false"),
    Column("notes", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    Column("doi_prefix", Text),
)


publisher_name_forms = Table(
    "publisher_name_forms",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("publisher_id", Integer, nullable=False),
    Column("form_normalized", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)


# ── Enums Postgres communs ────────────────────────────────────────


identifier_status_enum = PgEnum(
    "pending",
    "confirmed",
    "rejected",
    name="identifier_status",
    create_type=False,
)

source_type_enum = PgEnum(
    "hal",
    "openalex",
    "wos",
    "scanr",
    "theses",
    "crossref",
    name="source_type",
    create_type=False,
)

oa_type_enum = PgEnum(
    "gold",
    "hybrid",
    "bronze",
    "green",
    "closed",
    "unknown",
    "diamond",
    name="oa_type",
    create_type=False,
)

doc_type_enum = PgEnum(
    "article",
    "conference_paper",
    "book",
    "book_chapter",
    "thesis",
    "ongoing_thesis",
    "preprint",
    "review",
    "editorial",
    "report",
    "peer_review",
    "other",
    "dataset",
    "software",
    "patent",
    "hdr",
    "memoir",
    "poster",
    "letter",
    "erratum",
    "retraction",
    "book_review",
    "data_paper",
    "proceedings",
    name="doc_type",
    create_type=False,
)


# ── Adresses ──────────────────────────────────────────────────────


addresses = Table(
    "addresses",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("raw_text", Text, nullable=False),
    Column("normalized_text", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("pub_count", Integer, server_default="0"),
    Column("countries", ARRAY(CHAR(2))),
    Column("suggested_countries", ARRAY(CHAR(2))),
    Column("resolved_at", DateTime(timezone=True)),
)


address_structures = Table(
    "address_structures",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("address_id", Integer, nullable=False),
    Column("structure_id", Integer, nullable=False),
    Column("matched_form_id", Integer),
    Column("is_confirmed", Boolean),
)


# ── Authorships (vérité + sources) ────────────────────────────────


authorships = Table(
    "authorships",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("publication_id", Integer, nullable=False),
    Column("person_id", Integer),
    Column("author_position", SmallInteger),
    Column("in_perimeter", Boolean, server_default="false"),
    Column("source_manual", Boolean, server_default="false"),
    Column("excluded", Boolean, server_default="false"),
    Column("notes", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    Column("structure_ids", ARRAY(Integer)),
    Column("is_corresponding", Boolean),
    Column("roles", ARRAY(Text)),
)


source_authorships = Table(
    "source_authorships",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", Text, nullable=False),
    Column("source_publication_id", Integer, nullable=False),
    Column("source_person_id", Integer),
    Column("author_position", SmallInteger),
    Column("in_perimeter", Boolean, server_default="false"),
    Column("excluded", Boolean, server_default="false"),
    Column("structure_ids", ARRAY(Integer)),
    Column("source_struct_ids", ARRAY(Integer)),
    Column("countries", ARRAY(Text)),
    Column("person_id", Integer),
    Column("author_name_normalized", Text),
    Column("is_corresponding", Boolean, server_default="false"),
    Column("roles", ARRAY(Text), server_default="{author}"),
    Column("source_data", JSONB),
    Column("authorship_id", Integer),
    Column("raw_author_name", Text),
    Column("identifiers", JSONB),
)


source_authorship_addresses = Table(
    "source_authorship_addresses",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source_authorship_id", Integer, nullable=False),
    Column("address_id", Integer, nullable=False),
)


# ── Personnes ─────────────────────────────────────────────────────


persons = Table(
    "persons",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("last_name", Text, nullable=False),
    Column("first_name", Text, nullable=False),
    Column("last_name_normalized", Text, nullable=False),
    Column("first_name_normalized", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    Column("rejected", Boolean, server_default="false"),
)


persons_rh = Table(
    "persons_rh",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("person_id", Integer, nullable=False),
    Column("email", Text),
    Column("role_title", Text),
    Column("department_name", Text),
    Column("structure_id", Integer),
    Column("start_date", Date),
    Column("end_date", Date),
    Column("hr_export_date", Date),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)


person_identifiers = Table(
    "person_identifiers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("person_id", Integer, nullable=False),
    Column("id_type", Text, nullable=False),
    Column("id_value", Text, nullable=False),
    Column("source", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("status", identifier_status_enum, nullable=False, server_default="pending"),
)


person_name_forms = Table(
    "person_name_forms",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name_form", Text, nullable=False),
    Column("person_ids", ARRAY(Integer), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    Column("sources", ARRAY(Text)),
)


source_persons = Table(
    "source_persons",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", Text, nullable=False),
    Column("source_id", Text, nullable=False),
    Column("full_name", Text, nullable=False),
    Column("last_name", Text),
    Column("first_name", Text),
    Column("orcid", Text),
    Column("idref", Text),
    Column("person_id", Integer),
    Column("source_ids", JSONB),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)


# ── Publications ──────────────────────────────────────────────────


publications = Table(
    "publications",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("title", Text, nullable=False),
    Column("title_normalized", Text),
    Column("doc_type", doc_type_enum, server_default="other"),
    Column("pub_year", SmallInteger, nullable=False),
    Column("doi", Text),
    Column("oa_status", oa_type_enum, server_default="unknown"),
    Column("journal_id", Integer),
    Column("container_title", Text),
    Column("language", Text),
    Column("notes", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    Column("countries", ARRAY(Text)),
    Column("sources", ARRAY(source_type_enum), nullable=False, server_default="{}"),
    Column("meta", JSONB),
    Column("is_retracted", Boolean, nullable=False, server_default="false"),
    Column("abstract", Text),
    Column("keywords", ARRAY(Text)),
    Column("topics", JSONB),
    Column("biblio", JSONB),
)


source_publications = Table(
    "source_publications",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", Text, nullable=False),
    Column("source_id", Text, nullable=False),
    Column("doi", Text),
    Column("title", Text, nullable=False),
    Column("pub_year", SmallInteger),
    Column("doc_type", Text),
    Column("publication_id", Integer),
    Column("staging_id", Integer),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("countries", ARRAY(Text)),
    Column("hal_collections", ARRAY(Text)),
    Column("external_ids", JSONB),
    Column("urls", ARRAY(Text)),
    Column("cited_by_count", Integer),
    Column("journal_id", Integer),
    Column("oa_status", Text),
    Column("language", Text),
    Column("container_title", Text),
    Column("is_retracted", Boolean),
    Column("abstract", Text),
    Column("keywords", ARRAY(Text)),
    Column("topics", JSONB),
    Column("biblio", JSONB),
    Column("meta", JSONB),
)


distinct_persons = Table(
    "distinct_persons",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("person_id_a", Integer, nullable=False),
    Column("person_id_b", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)


distinct_publications = Table(
    "distinct_publications",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("pub_id_a", Integer, nullable=False),
    Column("pub_id_b", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)
