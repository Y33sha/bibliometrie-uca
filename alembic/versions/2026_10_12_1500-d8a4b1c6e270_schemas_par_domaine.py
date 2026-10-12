"""Un schéma PostgreSQL par domaine

Les tables, vues et vues matérialisées quittent `public` pour le schéma de leur domaine. Les types énumérés, les extensions et `alembic_version` restent dans `public`.

Le `search_path` de la base liste les schémas : les requêtes ne qualifient pas les noms de table. Les rôles de l'API et du pipeline, s'ils existent, reçoivent `USAGE` sur chaque schéma et les privilèges par défaut que `roles.sql` pose dans `public`. Les droits sur les tables suivent les tables.

Revision ID: d8a4b1c6e270
Revises: c7f3a0b5d469
Create Date: 2026-10-12 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d8a4b1c6e270"
down_revision: str | Sequence[str] | None = "c7f3a0b5d469"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Schéma de chaque relation, par nature de relation (`TABLE`, `VIEW`, `MATERIALIZED VIEW`).
SCHEMAS: dict[str, dict[str, tuple[str, ...]]] = {
    "sources": {
        "TABLE": (
            "staging",
            "source_publications",
            "source_authorships",
            "author_identifying_keys",
            "source_authorship_addresses",
            "source_authorship_rors",
            "failed_lookups",
        ),
        "VIEW": ("candidate_dois",),
        "MATERIALIZED VIEW": ("source_authorship_structures",),
    },
    "publications": {
        "TABLE": (
            "publications",
            "publications_detail",
            "authorships",
            "publication_relations",
            "publication_subjects",
            "subjects",
        ),
        "MATERIALIZED VIEW": (
            "subject_cooccurrences",
            "authorship_structures",
            "publication_structures",
        ),
    },
    "persons": {
        "TABLE": (
            "persons",
            "persons_rh",
            "person_identifiers",
            "person_name_forms",
            "distinct_persons",
            "rejected_authorships",
            "confirmed_authorships",
        ),
    },
    "publishing": {
        "TABLE": (
            "journals",
            "journal_issns",
            "journal_name_forms",
            "journal_doi_namespaces",
            "publishers",
            "publisher_name_forms",
            "monographs",
            "doi_prefixes",
            "apc_payments",
        ),
    },
    "structures": {
        "TABLE": (
            "structures",
            "structure_name_forms",
            "structure_tutelles",
            "perimeters",
            "perimeter_structures",
            "addresses",
            "address_structures",
        ),
    },
    "ref": {
        "TABLE": (
            "countries",
            "languages",
            "language_forms",
            "place_name_forms",
            "ror_organizations",
            "ror_relations",
            "ror_dump_imports",
        ),
    },
    "ops": {
        "TABLE": ("config", "audit_log", "pipeline_phase_executions"),
    },
}

SEARCH_PATH = ", ".join([*SCHEMAS, "public"])

# Privilèges par défaut de chaque rôle sur les tables et les séquences, ceux que `roles.sql` accorde.
_DEFAULT_PRIVILEGES = {
    "bibliometrie_app": ("SELECT", "USAGE, SELECT"),
    "bibliometrie_pipeline": (
        "SELECT, INSERT, UPDATE, DELETE, TRUNCATE, MAINTAIN",
        "USAGE, SELECT, UPDATE",
    ),
}


def _set_search_path(value: str) -> None:
    op.execute(
        f"DO $$ BEGIN EXECUTE format('ALTER DATABASE %I SET search_path = {value}', "
        "current_database()); END $$"
    )
    op.execute(f"SET search_path = {value}")


def _for_existing_role(role: str, statements: list[str]) -> None:
    """Exécute `statements` si le rôle existe : `roles.sql` le crée, et une base peut en être dépourvue."""
    body = "; ".join(statements)
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
        f"THEN {body}; END IF; END $$"
    )


def upgrade() -> None:
    for schema, relations in SCHEMAS.items():
        op.execute(f"CREATE SCHEMA {schema}")
        for kind, names in relations.items():
            for name in names:
                op.execute(f"ALTER {kind} public.{name} SET SCHEMA {schema}")
    _set_search_path(SEARCH_PATH)

    for role, (tables, sequences) in _DEFAULT_PRIVILEGES.items():
        _for_existing_role(
            role,
            [
                statement
                for schema in SCHEMAS
                for statement in (
                    f"GRANT USAGE ON SCHEMA {schema} TO {role}",
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT {tables} ON TABLES TO {role}",
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT {sequences} ON SEQUENCES TO {role}",
                )
            ],
        )


def downgrade() -> None:
    for role, (tables, sequences) in _DEFAULT_PRIVILEGES.items():
        _for_existing_role(
            role,
            [
                statement
                for schema in SCHEMAS
                for statement in (
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE {tables} ON TABLES FROM {role}",
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE {sequences} ON SEQUENCES FROM {role}",
                )
            ],
        )
    for schema, relations in SCHEMAS.items():
        for kind, names in relations.items():
            for name in names:
                op.execute(f"ALTER {kind} {schema}.{name} SET SCHEMA public")
    op.execute(
        "DO $$ BEGIN EXECUTE format('ALTER DATABASE %I RESET search_path', current_database()); "
        "END $$"
    )
    op.execute("RESET search_path")
    for schema in SCHEMAS:
        op.execute(f"DROP SCHEMA {schema}")
