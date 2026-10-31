"""Réponses des services externes sur chaque DOI, dans `sources.dois`

La table réunit, pour chaque DOI de publication, le verdict d'Unpaywall et l'adresse enregistrée chez doi.org, chacun daté. Elle reprend les verdicts de `sources.unpaywall`, qui est supprimée.

Revision ID: 9662296ecd54
Revises: 9a4e2c7b5f13
Create Date: 2026-10-31 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9662296ecd54"
down_revision: str | Sequence[str] | None = "9a4e2c7b5f13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE sources.dois (
            doi text PRIMARY KEY,
            unpaywall_oa_status public.oa_type,
            unpaywall_checked_at timestamptz,
            registered_url text,
            resolved_at timestamptz,
            CONSTRAINT dois_unpaywall_dated
                CHECK (unpaywall_oa_status IS NULL OR unpaywall_checked_at IS NOT NULL),
            CONSTRAINT dois_registered_url_dated
                CHECK (registered_url IS NULL OR resolved_at IS NOT NULL)
        )
    """)
    op.execute("""
        COMMENT ON TABLE sources.dois IS
        'Réponses des services externes sur chaque DOI de publication : verdict d''Unpaywall, adresse enregistrée chez doi.org.'
    """)
    op.execute("""
        COMMENT ON COLUMN sources.dois.unpaywall_oa_status IS
        'Statut open access donné par Unpaywall. NULL avec une date : DOI absent d''Unpaywall.'
    """)
    op.execute("""
        COMMENT ON COLUMN sources.dois.unpaywall_checked_at IS
        'Date du verdict d''Unpaywall. Le DOI est réinterrogé au-delà du délai unpaywall_recheck_after_days.'
    """)
    op.execute("""
        COMMENT ON COLUMN sources.dois.registered_url IS
        'Adresse enregistrée du DOI, lue dans l''API des handles de doi.org. NULL avec une date : DOI inconnu de doi.org.'
    """)
    op.execute("COMMENT ON COLUMN sources.dois.resolved_at IS 'Date de la lecture chez doi.org.'")
    op.execute("""
        INSERT INTO sources.dois (doi, unpaywall_oa_status, unpaywall_checked_at)
        SELECT doi, oa_status, checked_at FROM sources.unpaywall
    """)
    op.execute("DROP TABLE sources.unpaywall")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE sources.unpaywall (
            doi text PRIMARY KEY,
            oa_status public.oa_type,
            checked_at timestamptz NOT NULL
        )
    """)
    op.execute("""
        COMMENT ON TABLE sources.unpaywall IS
        'Verdict d''Unpaywall pour chaque DOI interrogé par la phase oa_status. Le DOI est réinterrogé quand checked_at date de plus que le délai unpaywall_recheck_after_days.'
    """)
    op.execute("""
        COMMENT ON COLUMN sources.unpaywall.oa_status IS
        'Statut open access donné par Unpaywall. NULL : DOI absent d''Unpaywall.'
    """)
    op.execute("""
        INSERT INTO sources.unpaywall (doi, oa_status, checked_at)
        SELECT doi, unpaywall_oa_status, unpaywall_checked_at FROM sources.dois
        WHERE unpaywall_checked_at IS NOT NULL
    """)
    op.execute("DROP TABLE sources.dois")
