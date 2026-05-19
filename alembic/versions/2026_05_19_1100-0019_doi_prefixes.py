"""doi_prefixes : table de mapping préfixe DOI → Registration Agency + publisher

Phase 1 du chantier `METIER_doi-ra-datacite.md`. Un préfixe DOI (`10.xxxx`) = un registrant = une RA permanente. Cette table permet :
- de filtrer `get_cross_import_dois('crossref')` pour ne taper l'API Crossref que sur les préfixes effectivement Crossref (~12 % d'appels économisés et disparition des stubs `not_found=TRUE` pour les DOI DataCite),
- de remplacer `publishers.doi_prefix` (mono-valeur) par un mapping many-to-one (un publisher peut avoir N préfixes),
- de préparer l'ingestion DataCite (phase 2) en isolant les préfixes DataCite.

Le retrait de `publishers.doi_prefix` est traité dans une migration séparée (0020), après adaptation des consommateurs côté API/UI.

Le peuplement initial se fait via le one-shot `interfaces/cli/oneshot/seed_doi_prefixes.py` à partir des caches du spike (Phase 0), pas dans cette migration : DDL only ici.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-19 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE doi_prefixes (
            prefix text PRIMARY KEY,
            ra text NOT NULL,
            publisher_id integer REFERENCES publishers(id) ON DELETE SET NULL,
            publisher_name_raw text,
            publisher_name_normalized text,
            crossref_member_id integer,
            fetched_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.create_index("idx_doi_prefixes_ra", "doi_prefixes", ["ra"])
    op.execute(
        """
        CREATE INDEX idx_doi_prefixes_publisher
            ON doi_prefixes (publisher_id)
            WHERE publisher_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_doi_prefixes_publisher_name_normalized
            ON doi_prefixes (publisher_name_normalized)
            WHERE publisher_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("idx_doi_prefixes_publisher_name_normalized", table_name="doi_prefixes")
    op.drop_index("idx_doi_prefixes_publisher", table_name="doi_prefixes")
    op.drop_index("idx_doi_prefixes_ra", table_name="doi_prefixes")
    op.drop_table("doi_prefixes")
