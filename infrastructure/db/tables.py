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
    ARRAY,
    Column,
    DateTime,
    Integer,
    MetaData,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()


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
