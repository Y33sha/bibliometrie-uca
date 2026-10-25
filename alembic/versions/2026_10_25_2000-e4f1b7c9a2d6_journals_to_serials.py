"""Revues renommées : publications en série (serials)

Revision ID: e4f1b7c9a2d6
Revises: c2e8a4d6f913
Create Date: 2026-10-25 20:00:00.000000

`journals` réunit revues, collections d'ouvrages, séries d'actes et médias : la table devient `serials`, ses tables satellites `serial_issns`, `serial_name_forms` et `serial_doi_namespaces`, la colonne `journal_id` des tables qui la référencent `serial_id`, son type `serial_type`. Suivent les séquences, contraintes et index qui portent ces noms, et les valeurs stockées qui nomment l'entité : marqueur de saisie manuelle, type d'entité des redirections, événements du journal d'audit, clés et règles des corrections, clés des métriques de l'historique des exécutions de phase.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e4f1b7c9a2d6"
down_revision: str | Sequence[str] | None = "c2e8a4d6f913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_P = "publishing"

# Tables : (ancien nom, nouveau nom), dans le schéma `publishing`.
_TABLES = [
    ("journals", "serials"),
    ("journal_issns", "serial_issns"),
    ("journal_name_forms", "serial_name_forms"),
    ("journal_doi_namespaces", "serial_doi_namespaces"),
]

# Colonnes : (table nouvellement nommée, ancien nom, nouveau nom).
_COLUMNS = [
    ("publications.publications", "journal_id", "serial_id"),
    ("sources.source_records", "journal_id", "serial_id"),
    (f"{_P}.monographs", "journal_id", "serial_id"),
    (f"{_P}.apc_payments", "journal_id", "serial_id"),
    (f"{_P}.serial_issns", "journal_id", "serial_id"),
    (f"{_P}.serial_name_forms", "journal_id", "serial_id"),
    (f"{_P}.serial_doi_namespaces", "journal_id", "serial_id"),
    (f"{_P}.serials", "journal_type", "serial_type"),
]

_SEQUENCES = [
    ("journals_id_seq", "serials_id_seq"),
    ("journal_issns_id_seq", "serial_issns_id_seq"),
    ("journal_name_forms_id_seq", "serial_name_forms_id_seq"),
]

# Contraintes : (table nouvellement nommée, ancien nom, nouveau nom). Renommer une contrainte d'unicité ou de clé primaire renomme son index.
_CONSTRAINTS = [
    (f"{_P}.apc_payments", "apc_payments_journal_id_fkey", "apc_payments_serial_id_fkey"),
    (
        f"{_P}.serial_doi_namespaces",
        "journal_doi_namespaces_dois_not_null",
        "serial_doi_namespaces_dois_not_null",
    ),
    (
        f"{_P}.serial_doi_namespaces",
        "journal_doi_namespaces_journal_id_fkey",
        "serial_doi_namespaces_serial_id_fkey",
    ),
    (
        f"{_P}.serial_doi_namespaces",
        "journal_doi_namespaces_journal_id_not_null",
        "serial_doi_namespaces_serial_id_not_null",
    ),
    (
        f"{_P}.serial_doi_namespaces",
        "journal_doi_namespaces_namespace_not_null",
        "serial_doi_namespaces_namespace_not_null",
    ),
    (f"{_P}.serial_doi_namespaces", "journal_doi_namespaces_pkey", "serial_doi_namespaces_pkey"),
    (
        f"{_P}.serial_doi_namespaces",
        "journal_doi_namespaces_share_not_null",
        "serial_doi_namespaces_share_not_null",
    ),
    (f"{_P}.serial_issns", "journal_issns_id_not_null", "serial_issns_id_not_null"),
    (f"{_P}.serial_issns", "journal_issns_issn_not_null", "serial_issns_issn_not_null"),
    (f"{_P}.serial_issns", "journal_issns_journal_id_fkey", "serial_issns_serial_id_fkey"),
    (f"{_P}.serial_issns", "journal_issns_linking_not_null", "serial_issns_linking_not_null"),
    (f"{_P}.serial_issns", "journal_issns_pkey", "serial_issns_pkey"),
    (f"{_P}.serial_issns", "journal_issns_status_not_null", "serial_issns_status_not_null"),
    (f"{_P}.serial_issns", "uq_journal_issns_issn_journal", "uq_serial_issns_issn_serial"),
    (
        f"{_P}.serial_name_forms",
        "journal_name_forms_form_normalized_not_null",
        "serial_name_forms_form_normalized_not_null",
    ),
    (f"{_P}.serial_name_forms", "journal_name_forms_id_not_null", "serial_name_forms_id_not_null"),
    (
        f"{_P}.serial_name_forms",
        "journal_name_forms_journal_id_fkey",
        "serial_name_forms_serial_id_fkey",
    ),
    (
        f"{_P}.serial_name_forms",
        "journal_name_forms_journal_id_not_null",
        "serial_name_forms_serial_id_not_null",
    ),
    (f"{_P}.serial_name_forms", "journal_name_forms_pkey", "serial_name_forms_pkey"),
    (
        f"{_P}.serial_name_forms",
        "uq_jnl_nf_form_publisher",
        "uq_serial_name_forms_form_publisher",
    ),
    (
        f"{_P}.serial_name_forms",
        "journal_name_forms_publisher_id_fkey",
        "serial_name_forms_publisher_id_fkey",
    ),
    (f"{_P}.serials", "journals_id_not_null", "serials_id_not_null"),
    (f"{_P}.serials", "journals_manual_fields_not_null", "serials_manual_fields_not_null"),
    (f"{_P}.serials", "journals_openalex_id_key", "serials_openalex_id_key"),
    (f"{_P}.serials", "journals_pkey", "serials_pkey"),
    (f"{_P}.serials", "journals_publication_count_not_null", "serials_publication_count_not_null"),
    (f"{_P}.serials", "journals_publisher_id_fkey", "serials_publisher_id_fkey"),
    (f"{_P}.serials", "journals_title_normalized_not_null", "serials_title_normalized_not_null"),
    (f"{_P}.serials", "journals_title_not_null", "serials_title_not_null"),
    (f"{_P}.monographs", "monographs_journal_id_fkey", "monographs_serial_id_fkey"),
    ("publications.publications", "publications_journal_id_fkey", "publications_serial_id_fkey"),
    ("sources.source_records", "source_records_journal_id_fkey", "source_records_serial_id_fkey"),
]

# Index sans contrainte : (schéma, ancien nom, nouveau nom).
_INDEXES = [
    (_P, "idx_jnl_nf_journal", "idx_serial_name_forms_serial"),
    (_P, "idx_journals_publisher", "idx_serials_publisher"),
    (_P, "idx_journals_titlenorm", "idx_serials_titlenorm"),
    (_P, "idx_journal_issns_journal", "idx_serial_issns_serial"),
    (_P, "uq_journal_issns_linking", "uq_serial_issns_linking"),
    (_P, "ix_journal_doi_namespaces_journal_id", "ix_serial_doi_namespaces_serial_id"),
    (_P, "idx_monographs_journal", "idx_monographs_serial"),
    (
        "publications",
        "idx_publications_in_perimeter_journal",
        "idx_publications_in_perimeter_serial",
    ),
    ("publications", "idx_publications_journal", "idx_publications_serial"),
    ("sources", "idx_source_records_journal", "idx_source_records_serial"),
]

# Valeurs des règles de correction qui nomment l'entité : (ancienne, nouvelle).
_RULES = [
    ("JOURNAL_BY_DOI_NAMESPACE", "SERIAL_BY_DOI_NAMESPACE"),
    ("JOURNAL_TYPE_MEDIA_TO_MEDIA", "SERIAL_TYPE_MEDIA_TO_MEDIA"),
    ("JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT", "SERIAL_TYPE_PREPRINT_SERVER_TO_PREPRINT"),
    ("JOURNAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER", "SERIAL_TYPE_PROCEEDINGS_TO_CONFERENCE_PAPER"),
    ("THESIS_WITH_JOURNAL_TO_ARTICLE", "THESIS_WITH_SERIAL_TO_ARTICLE"),
]

# Clés des métriques de l'historique des exécutions de phase : (ancienne, nouvelle).
_METRICS = [
    ("journals_merged", "serials_merged"),
    ("journals_deleted", "serials_deleted"),
    ("journals_typed_proceedings", "serials_typed_proceedings"),
    ("journal_doi_namespaces", "serial_doi_namespaces"),
]


def _rewrite_jsonb_sql(table: str, column: str, pairs: list[tuple[str, str]]) -> str:
    """Remplace, dans la colonne jsonb `column` de `table`, chaque texte ancien de `pairs` par le nouveau."""
    expression = f"{column}::text"
    for old, new in pairs:
        expression = f"replace({expression}, '{old}', '{new}')"
    pattern = "|".join(old for old, _ in pairs)
    return f"UPDATE {table} SET {column} = CAST({expression} AS jsonb) WHERE {column}::text ~ '{pattern}'"


def _statements(*, up: bool) -> list[str]:
    def pair(old: str, new: str) -> tuple[str, str]:
        return (old, new) if up else (new, old)

    tables = ["ALTER TABLE {}.{} RENAME TO {}".format(_P, *pair(old, new)) for old, new in _TABLES]
    columns = [
        "ALTER TABLE {} RENAME COLUMN {} TO {}".format(table, *pair(old, new))
        for table, old, new in _COLUMNS
    ]
    sequences = [
        "ALTER SEQUENCE {}.{} RENAME TO {}".format(_P, *pair(old, new)) for old, new in _SEQUENCES
    ]
    constraints = [
        "ALTER TABLE {} RENAME CONSTRAINT {} TO {}".format(table, *pair(old, new))
        for table, old, new in _CONSTRAINTS
    ]
    indexes = [
        "ALTER INDEX {}.{} RENAME TO {}".format(schema, *pair(old, new))
        for schema, old, new in _INDEXES
    ]
    serial_type = pair("journal_type", "serial_type")
    entity = pair("journal", "serial")
    correction_pairs = [pair('"journal_id":', '"serial_id":'), *(pair(o, n) for o, n in _RULES)]
    metric_pairs = [pair(f'"{o}":', f'"{n}":') for o, n in _METRICS]
    values = [
        "ALTER TYPE public.{} RENAME TO {}".format(*serial_type),
        "ALTER TYPE public.merged_entity RENAME VALUE '{}' TO '{}'".format(*entity),
        # À la montée comme à la descente, les valeurs se réécrivent quand la table s'appelle `serials`.
        "UPDATE {}.serials SET manual_fields = array_replace(manual_fields, '{}', '{}')".format(
            _P, *serial_type
        ),
        "UPDATE ops.audit_log SET event_type = replace(event_type, '{0}.', '{1}.'), aggregate_type = '{1}' "
        "WHERE aggregate_type = '{0}'".format(*entity),
        "UPDATE ops.audit_log SET payload = (payload - '{0}') || jsonb_build_object('{1}', payload->'{0}') "
        "WHERE payload ? '{0}'".format(*serial_type),
        _rewrite_jsonb_sql("sources.source_records", "corrections", correction_pairs),
        _rewrite_jsonb_sql("publications.publications", "corrections", correction_pairs),
        _rewrite_jsonb_sql("ops.pipeline_phase_executions", "metrics", metric_pairs),
    ]
    if up:
        return tables + columns + sequences + constraints + indexes + values
    return values + indexes + constraints + sequences + columns + tables


def upgrade() -> None:
    op.execute(";\n".join(_statements(up=True)))


def downgrade() -> None:
    op.execute(";\n".join(_statements(up=False)))
