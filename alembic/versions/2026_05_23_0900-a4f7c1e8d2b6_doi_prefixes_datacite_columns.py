"""doi_prefixes : colonnes DataCite (client_name_*, datacite_client_symbol)

Phase 2 du chantier `METIER_doi-ra-datacite.md`. Trois colonnes nullable peuplées uniquement pour les rows `ra='DataCite'` :

- `client_name_raw` / `client_name_normalized` : nom du DataCite client (= repository : Zenodo, NAKALA, INRAE, …) renvoyé par `api.datacite.org/prefixes/{p}?include=clients,providers`.
- `datacite_client_symbol` : identifiant stable assigné par DataCite (ex. `cern.zenodo`, `inist.inra`), conservé pour identification durable au-delà des renommages.

Le provider DataCite (organisation-mère) est stocké dans les colonnes `publisher_*` existantes — mêmes règles de matching/création que pour le publisher Crossref.

Revision ID: a4f7c1e8d2b6
Revises: f8e2c4d1a5b9
Create Date: 2026-05-23 09:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a4f7c1e8d2b6"
down_revision: str | Sequence[str] | None = "f8e2c4d1a5b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE doi_prefixes
            ADD COLUMN client_name_raw text,
            ADD COLUMN client_name_normalized text,
            ADD COLUMN datacite_client_symbol text
        """
    )
    op.execute(
        """
        CREATE INDEX idx_doi_prefixes_client_name_normalized
            ON doi_prefixes (client_name_normalized)
            WHERE client_name_normalized IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_doi_prefixes_datacite_client_symbol
            ON doi_prefixes (datacite_client_symbol)
            WHERE datacite_client_symbol IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("idx_doi_prefixes_datacite_client_symbol", table_name="doi_prefixes")
    op.drop_index("idx_doi_prefixes_client_name_normalized", table_name="doi_prefixes")
    op.execute(
        """
        ALTER TABLE doi_prefixes
            DROP COLUMN datacite_client_symbol,
            DROP COLUMN client_name_normalized,
            DROP COLUMN client_name_raw
        """
    )
