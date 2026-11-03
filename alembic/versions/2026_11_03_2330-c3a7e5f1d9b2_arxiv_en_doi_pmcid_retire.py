"""Identifiants arXiv convertis en DOI, PMCID retirés des identifiants

Un identifiant arXiv équivaut au DOI du dépôt (`10.48550/arxiv.<identifiant>`) : il devient ce DOI, avec le rôle le plus fort des deux. Un PMCID désigne la page de l'article sur PubMed Central, localisation de l'enregistrement source : il quitte les identifiants. Les valeurs `arxiv_id` et `pmcid` quittent `source_identifier_type`, et `known_dois` sa branche arXiv. Les enregistrements sources concernés passent en file de réconciliation.

Revision ID: c3a7e5f1d9b2
Revises: b8f2d4a6c1e9
Create Date: 2026-11-03 23:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3a7e5f1d9b2"
down_revision: str | Sequence[str] | None = "b8f2d4a6c1e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KNOWN_DOIS = """
    CREATE VIEW sources.known_dois AS
     SELECT i.id_value AS doi, sp.source, sp.publication_id
       FROM sources.source_records sp
       JOIN sources.source_record_identifiers i ON i.source_record_id = sp.id
      WHERE i.id_type = 'doi' AND i.removed_by IS NULL
    UNION
     SELECT pr.target_doi AS doi, NULL::public.source_type AS source,
            pr.from_publication_id AS publication_id
       FROM publications.publication_relations pr
      WHERE pr.target_doi IS NOT NULL
"""

_ARXIV_BRANCH = """
    UNION
     SELECT '10.48550/arxiv.' || lower(i.id_value) AS doi, sp.source, sp.publication_id
       FROM sources.source_records sp
       JOIN sources.source_record_identifiers i ON i.source_record_id = sp.id
      WHERE i.id_type = 'arxiv_id' AND i.removed_by IS NULL
"""

_CANDIDATE_DOIS = """
    CREATE VIEW sources.candidate_dois AS
     SELECT DISTINCT k.doi, k.source, k.publication_id
       FROM sources.known_dois k
       JOIN publications.publications p ON p.id = k.publication_id
      WHERE p.in_perimeter
"""


def _drop_views() -> None:
    op.execute("DROP VIEW sources.candidate_dois")
    op.execute("DROP VIEW sources.known_dois")


def _recreate_type(values: Sequence[str]) -> None:
    op.execute("ALTER TYPE public.source_identifier_type RENAME TO source_identifier_type_old")
    op.execute(
        "CREATE TYPE public.source_identifier_type AS ENUM ("
        + ", ".join(f"'{v}'" for v in values)
        + ")"
    )
    op.execute("""
        ALTER TABLE sources.source_record_identifiers
        ALTER COLUMN id_type TYPE public.source_identifier_type
        USING id_type::text::public.source_identifier_type
    """)
    op.execute("DROP TYPE public.source_identifier_type_old")


def upgrade() -> None:
    op.execute("""
        CREATE TEMP TABLE arxiv_identifiers ON COMMIT DROP AS
        SELECT source_record_id, '10.48550/arxiv.' || lower(id_value) AS doi, role
        FROM sources.source_record_identifiers WHERE id_type = 'arxiv_id'
    """)
    op.execute("""
        CREATE TEMP TABLE converted_records ON COMMIT DROP AS
        SELECT DISTINCT source_record_id AS id FROM sources.source_record_identifiers
        WHERE id_type IN ('arxiv_id', 'pmcid')
    """)
    op.execute(
        "DELETE FROM sources.source_record_identifiers WHERE id_type IN ('arxiv_id', 'pmcid')"
    )
    # Le DOI prend le rôle le plus fort de ses deux formes, dans l'ordre de l'enum `source_identifier_role`.
    op.execute("""
        INSERT INTO sources.source_record_identifiers (source_record_id, id_type, id_value, role)
        SELECT DISTINCT ON (source_record_id, doi) source_record_id, 'doi', doi, role
        FROM arxiv_identifiers
        ORDER BY source_record_id, doi, role
        ON CONFLICT (source_record_id, id_type, id_value)
        DO UPDATE SET role = LEAST(sources.source_record_identifiers.role, EXCLUDED.role)
    """)
    op.execute("""
        INSERT INTO queues.source_record_keys_queue (id)
        SELECT id FROM converted_records
        ON CONFLICT (id) DO UPDATE SET seq = DEFAULT
    """)
    _drop_views()
    _recreate_type(("doi", "hal_id", "nnt", "pmid", "isbn", "eisbn"))
    op.execute(_KNOWN_DOIS)
    op.execute(_CANDIDATE_DOIS)
    op.execute("""
        COMMENT ON VIEW sources.known_dois IS 'Tous les DOI connus : DOI actifs des enregistrements sources, cibles des relations. publication_id est la publication de l''enregistrement source, ou la publication d''origine de la relation ; NULL pour un enregistrement source orphelin.'
    """)


def downgrade() -> None:
    # Le downgrade rend les valeurs d'enum et la branche arXiv de `known_dois`. Les identifiants convertis restent des DOI.
    _drop_views()
    _recreate_type(("doi", "hal_id", "nnt", "pmid", "pmcid", "arxiv_id", "isbn", "eisbn"))
    op.execute(_KNOWN_DOIS + _ARXIV_BRANCH)
    op.execute(_CANDIDATE_DOIS)
    op.execute("""
        COMMENT ON VIEW sources.known_dois IS 'Tous les DOI connus : DOI actifs des enregistrements sources, cibles des relations, DOI DataCite déduits des identifiants arXiv. publication_id est la publication de l''enregistrement source, ou la publication d''origine de la relation ; NULL pour un enregistrement source orphelin.'
    """)
