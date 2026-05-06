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
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    Numeric,
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
